"""
Unit tests for the new RuntimeEvalSettings config block.

These guarantee:
  - Settings exposes a `runtime_eval` block (distinct from `deepeval`).
  - Defaults match the design (enabled=False, eval_model='gpt-4.1-mini',
    metrics list, thresholds).
  - The env_prefix `RUNTIME_EVAL_` toggles fields as expected.
"""

import importlib

import pytest


@pytest.fixture
def reload_config(monkeypatch):
    """
    Reload config.py inside the test so env-var overrides take effect.

    Settings reads env via Pydantic Settings; we need to clear the lru_cache
    so a fresh Settings instance is built per test.
    """
    import config as cfg

    importlib.reload(cfg)
    if hasattr(cfg, "get_settings") and hasattr(cfg.get_settings, "cache_clear"):
        cfg.get_settings.cache_clear()
    yield cfg
    importlib.reload(cfg)
    if hasattr(cfg, "get_settings") and hasattr(cfg.get_settings, "cache_clear"):
        cfg.get_settings.cache_clear()


class TestRuntimeEvalSettings:
    def test_settings_exposes_runtime_eval_block(self, reload_config):
        s = reload_config.Settings()
        assert hasattr(s, "runtime_eval")

    def test_enabled_defaults_to_false(self, reload_config):
        s = reload_config.Settings()
        assert s.runtime_eval.enabled is False

    def test_eval_model_default(self, reload_config):
        s = reload_config.Settings()
        assert s.runtime_eval.eval_model == "gpt-4.1-mini"

    def test_default_metrics(self, reload_config):
        s = reload_config.Settings()
        assert s.runtime_eval.metrics == [
            "faithfulness",
            "answer_relevancy",
            "hallucination",
        ]

    def test_default_thresholds(self, reload_config):
        s = reload_config.Settings()
        assert s.runtime_eval.faithfulness_threshold == 0.7
        assert s.runtime_eval.answer_relevancy_threshold == 0.7
        assert s.runtime_eval.hallucination_threshold == 0.5

    def test_default_sampling_rate(self, reload_config):
        s = reload_config.Settings()
        assert s.runtime_eval.sampling_rate == 1.0

    def test_default_judge_timeout(self, reload_config):
        s = reload_config.Settings()
        assert s.runtime_eval.judge_timeout_seconds == 30

    def test_env_var_enables_runtime_eval(self, monkeypatch, reload_config):
        monkeypatch.setenv("RUNTIME_EVAL_ENABLED", "true")
        importlib.reload(reload_config)
        s = reload_config.Settings()
        assert s.runtime_eval.enabled is True

    def test_deepeval_block_still_present_for_ci_gate(self, reload_config):
        """The CI gate still imports DeepEvalSettings; it must not be removed."""
        s = reload_config.Settings()
        assert hasattr(s, "deepeval")

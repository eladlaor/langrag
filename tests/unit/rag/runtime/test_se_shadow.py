"""
Unit tests for the SE shadow scorer.

The shadow scorer runs ALONGSIDE the LLM judge as a pure observability sink:
  1. Disabled (default) -> instant None, NO model calls, NO taste import.
  2. Enabled -> generates N independent samples, computes SE via taste,
     writes SE / n_clusters / n_samples / escalation to Langfuse, returns a
     sink dict, and NEVER mutates the conversation answer.
  3. Any failure (model or taste) is fail-soft: swallowed, returns None.

The lazy `from taste import ...` inside shadow_score_se is the ONLY coupling to
taste, so we inject a fake `taste` module via sys.modules — no real torch or
network needed. SE-ONLY is encoded by asserting every Sample carries empty
token_logprobs and only the SE detector is passed.
"""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from constants import SeShadowKey


# --------------------------------------------------------------------------- #
# Fake taste module (injected via sys.modules so the in-function lazy import
# `from taste import ...` resolves to these objects without importing torch).
# --------------------------------------------------------------------------- #


class _FakeDetectorName:
    SEMANTIC_ENTROPY = "semantic_entropy"


class _FakeSample:
    def __init__(self, text):
        self.text = text
        # Mirrors taste.Sample default: empty logprobs => PE impossible, SE-only.
        self.token_logprobs = []


class _FakeSampleSet:
    def __init__(self, prompt, samples):
        self.prompt = prompt
        self.samples = samples


class _FakeSemanticEntropyDetector:
    name = _FakeDetectorName.SEMANTIC_ENTROPY


class _FakeSingleDetector:
    def __init__(self, name, threshold):
        self.name = name
        self.threshold = threshold


def _make_fake_taste(*, se_score=1.5, n_clusters=3, escalated=True, evaluate_side_effect=None):
    """Build a fake taste module object with a recording evaluate_responses."""
    evaluate_responses = MagicMock()
    if evaluate_side_effect is not None:
        evaluate_responses.side_effect = evaluate_side_effect
    else:
        evaluate_responses.return_value = SimpleNamespace(
            detector_scores={_FakeDetectorName.SEMANTIC_ENTROPY: se_score},
            clusters=list(range(n_clusters)),
            escalated=escalated,
        )

    return SimpleNamespace(
        DetectorName=_FakeDetectorName,
        Sample=_FakeSample,
        SampleSet=_FakeSampleSet,
        SemanticEntropyDetector=_FakeSemanticEntropyDetector,
        SingleDetector=_FakeSingleDetector,
        evaluate_responses=evaluate_responses,
    )


# --------------------------------------------------------------------------- #
# Settings + collaborator fixtures
# --------------------------------------------------------------------------- #


def _make_settings(
    *,
    enabled=True,
    sample_n=5,
    temperature=1.0,
    threshold=1.0,
    sampling_rate=1.0,
):
    runtime_eval = SimpleNamespace(
        se_shadow_enabled=enabled,
        se_shadow_sample_n=sample_n,
        se_shadow_temperature=temperature,
        se_shadow_threshold=threshold,
        se_shadow_sampling_rate=sampling_rate,
    )
    rag = SimpleNamespace(rag_llm_model="gpt-test", rag_llm_provider="openai")
    return SimpleNamespace(runtime_eval=runtime_eval, rag=rag)


@pytest.fixture
def mock_langfuse_client():
    client = MagicMock()
    client.score = MagicMock()
    return client


@pytest.fixture
def patched_se_shadow_env(mock_langfuse_client):
    """
    Patch the se_shadow module's collaborators and inject a fake taste module.

    Yields a dict of the patched objects so individual tests can tweak settings,
    swap the fake taste, or inspect calls.
    """
    fake_taste = _make_fake_taste()

    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=SimpleNamespace(content="sample text"))
    create_chat_model = MagicMock(return_value=llm)

    settings_obj = _make_settings()

    def _get_settings():
        return settings_obj

    with (
        patch("rag.evaluation.runtime.se_shadow.get_settings", side_effect=_get_settings),
        patch("rag.evaluation.runtime.se_shadow.get_langfuse_client", return_value=mock_langfuse_client),
        patch.dict(sys.modules, {"taste": fake_taste}),
        patch("utils.llm.chat_model_factory.create_chat_model", create_chat_model),
        patch("rag.generation.rag_chain._build_messages", return_value=["msg"]),
    ):
        yield {
            "fake_taste": fake_taste,
            "llm": llm,
            "create_chat_model": create_chat_model,
            "langfuse": mock_langfuse_client,
            "settings": settings_obj,
        }


def _set_settings(env, **overrides):
    """Replace the settings object returned by the patched get_settings."""
    env["settings"].runtime_eval = _make_settings(**overrides).runtime_eval


async def _call(env):
    from rag.evaluation.runtime.se_shadow import shadow_score_se

    return await shadow_score_se(
        evaluation_id="eval-1",
        session_id="sess-1",
        query="what is langgraph?",
        contexts=["ctx a", "ctx b"],
        conversation_history=None,
        langfuse_trace_id="trace-1",
    )


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


class TestShadowScoreSe:
    async def test_disabled_returns_none_and_imports_no_taste(self, patched_se_shadow_env):
        env = patched_se_shadow_env
        _set_settings(env, enabled=False)

        result = await _call(env)

        assert result is None
        env["create_chat_model"].assert_not_called()
        env["fake_taste"].evaluate_responses.assert_not_called()

    async def test_sampling_rate_zero_returns_none(self, patched_se_shadow_env):
        env = patched_se_shadow_env
        _set_settings(env, enabled=True, sampling_rate=0.0)

        with patch("rag.evaluation.runtime.se_shadow.random.random", return_value=1.0):
            result = await _call(env)

        assert result is None
        env["create_chat_model"].assert_not_called()
        env["fake_taste"].evaluate_responses.assert_not_called()

    async def test_enabled_generates_n_samples_and_writes_sink(self, patched_se_shadow_env):
        env = patched_se_shadow_env
        _set_settings(env, enabled=True, sample_n=5)
        env["fake_taste"].evaluate_responses.return_value = SimpleNamespace(
            detector_scores={_FakeDetectorName.SEMANTIC_ENTROPY: 1.5},
            clusters=[0, 1, 2],
            escalated=True,
        )

        result = await _call(env)

        # N independent model calls.
        assert env["llm"].ainvoke.await_count == 5

        # taste invoked once, in shadow mode, over a 5-sample SampleSet.
        env["fake_taste"].evaluate_responses.assert_called_once()
        kwargs = env["fake_taste"].evaluate_responses.call_args.kwargs
        assert kwargs["judge"] is None
        sample_set = kwargs["samples"]
        assert len(sample_set.samples) == 5
        assert all(s.token_logprobs == [] for s in sample_set.samples)

        # Langfuse sink: one score per SeShadowKey.
        names_posted = {c.kwargs["name"] for c in env["langfuse"].score.call_args_list}
        assert names_posted == {
            str(SeShadowKey.SE_SCORE),
            str(SeShadowKey.N_CLUSTERS),
            str(SeShadowKey.N_SAMPLES),
            str(SeShadowKey.ESCALATION_FLAG),
        }

        # Returned sink dict carries the expected values.
        assert result is not None
        assert result[str(SeShadowKey.SE_SCORE)] == 1.5
        assert result[str(SeShadowKey.N_CLUSTERS)] == 3
        assert result[str(SeShadowKey.N_SAMPLES)] == 5

    async def test_fail_soft_on_taste_error(self, patched_se_shadow_env):
        env = patched_se_shadow_env
        _set_settings(env, enabled=True, sample_n=3)
        env["fake_taste"].evaluate_responses.side_effect = RuntimeError("taste exploded")

        result = await _call(env)

        assert result is None  # swallowed, not propagated

    async def test_fail_soft_on_model_error(self, patched_se_shadow_env):
        env = patched_se_shadow_env
        _set_settings(env, enabled=True, sample_n=3)
        env["llm"].ainvoke.side_effect = RuntimeError("model down")

        result = await _call(env)

        assert result is None
        env["fake_taste"].evaluate_responses.assert_not_called()

    async def test_pe_never_used(self, patched_se_shadow_env):
        env = patched_se_shadow_env
        _set_settings(env, enabled=True, sample_n=4)

        await _call(env)

        kwargs = env["fake_taste"].evaluate_responses.call_args.kwargs
        detectors = kwargs["detectors"]
        # Only the SE detector is passed.
        assert len(detectors) == 1
        assert detectors[0].name == _FakeDetectorName.SEMANTIC_ENTROPY
        # Every sample has empty logprobs => PE is impossible by construction.
        assert all(s.token_logprobs == [] for s in kwargs["samples"].samples)

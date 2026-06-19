"""
Pure-unit validation tests for RAG preferences models (no DB required).

Covers plan TDD criterion 5 (fail-fast on out-of-range lambda) at the model
boundary that backs both the API body (422) and the repository write.
"""

import pytest
from pydantic import ValidationError

from custom_types.db_schemas import RagPreferences


class TestRagPreferencesModel:
    def test_defaults_mirror_config(self):
        prefs = RagPreferences()
        assert prefs.mmr_lambda == 0.7
        assert prefs.enable_mmr_diversity is True

    @pytest.mark.parametrize("ok", [0.0, 0.5, 1.0])
    def test_boundary_values_accepted(self, ok):
        assert RagPreferences(mmr_lambda=ok, enable_mmr_diversity=True).mmr_lambda == ok

    @pytest.mark.parametrize("bad", [-0.1, 1.1, 2.0, -1.0])
    def test_out_of_range_rejected(self, bad):
        with pytest.raises(ValidationError):
            RagPreferences(mmr_lambda=bad, enable_mmr_diversity=True)


class TestRagPreferencesUpdateApiModel:
    def test_api_update_model_enforces_bounds(self):
        from api.agent_chat import RagPreferencesUpdate

        assert RagPreferencesUpdate(mmr_lambda=0.0, enable_mmr_diversity=False).mmr_lambda == 0.0
        with pytest.raises(ValidationError):
            RagPreferencesUpdate(mmr_lambda=1.5, enable_mmr_diversity=True)

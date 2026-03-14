"""
Unit tests for SLM Provider (Ollama).

Tests cover:
- Provider initialization
- Health check behavior
- Completion API
- Error handling and retries
- Fail-soft behavior when unavailable
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from custom_types.slm_schemas import SLMHealthStatus


class TestOllamaProviderInit:
    """Test OllamaProvider initialization."""

    def test_provider_uses_config_defaults(self):
        """Test that provider uses settings from config when no args provided."""
        with patch("core.slm.provider.get_settings") as mock_settings:
            mock_slm = MagicMock()
            mock_slm.base_url = "http://test:11434"
            mock_slm.model = "test-model"
            mock_slm.fallback_model = "fallback-model"
            mock_slm.request_timeout_seconds = 30
            mock_slm.temperature = 0.1
            mock_slm.max_tokens = 50
            mock_slm.max_retries = 2
            mock_settings.return_value.slm = mock_slm

            from core.slm.provider import OllamaProvider
            provider = OllamaProvider()

            assert provider.base_url == "http://test:11434"
            assert provider.model == "test-model"
            assert provider.fallback_model == "fallback-model"
            assert provider.timeout_seconds == 30

    def test_provider_accepts_override_args(self):
        """Test that provider accepts override arguments."""
        with patch("core.slm.provider.get_settings") as mock_settings:
            mock_slm = MagicMock()
            mock_slm.base_url = "http://default:11434"
            mock_slm.model = "default-model"
            mock_slm.fallback_model = "default-fallback"
            mock_slm.request_timeout_seconds = 30
            mock_slm.temperature = 0.1
            mock_slm.max_tokens = 50
            mock_slm.max_retries = 2
            mock_settings.return_value.slm = mock_slm

            from core.slm.provider import OllamaProvider
            provider = OllamaProvider(
                base_url="http://custom:11434",
                model="custom-model",
                timeout_seconds=60,
            )

            assert provider.base_url == "http://custom:11434"
            assert provider.model == "custom-model"
            assert provider.timeout_seconds == 60


class TestOllamaProviderHealthCheck:
    """Test OllamaProvider.health_check() method."""

    @pytest.mark.asyncio
    async def test_health_check_returns_available_when_ollama_responds(self):
        """Test health check returns available=True when Ollama responds."""
        with patch("core.slm.provider.get_settings") as mock_settings:
            mock_slm = MagicMock()
            mock_slm.base_url = "http://ollama:11434"
            mock_slm.model = "phi3"
            mock_slm.fallback_model = "gemma2"
            mock_slm.request_timeout_seconds = 30
            mock_slm.temperature = 0.1
            mock_slm.max_tokens = 50
            mock_slm.max_retries = 2
            mock_settings.return_value.slm = mock_slm

            from core.slm.provider import OllamaProvider

            mock_response = MagicMock()
            mock_response.json.return_value = {
                "models": [{"name": "phi3:latest"}]
            }
            mock_response.raise_for_status = MagicMock()

            with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = mock_response

                provider = OllamaProvider()
                provider._client = httpx.AsyncClient(base_url="http://ollama:11434")

                health = await provider.health_check()

                assert health.available is True
                await provider.close()

    @pytest.mark.asyncio
    async def test_health_check_returns_unavailable_on_connection_error(self):
        """Test health check returns available=False on connection error."""
        with patch("core.slm.provider.get_settings") as mock_settings:
            mock_slm = MagicMock()
            mock_slm.base_url = "http://ollama:11434"
            mock_slm.model = "phi3"
            mock_slm.fallback_model = "gemma2"
            mock_slm.request_timeout_seconds = 30
            mock_slm.temperature = 0.1
            mock_slm.max_tokens = 50
            mock_slm.max_retries = 2
            mock_settings.return_value.slm = mock_slm

            from core.slm.provider import OllamaProvider

            with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
                mock_get.side_effect = httpx.ConnectError("Connection refused")

                provider = OllamaProvider()
                provider._client = httpx.AsyncClient(base_url="http://ollama:11434")

                health = await provider.health_check()

                assert health.available is False
                assert "Cannot connect" in health.error_message
                await provider.close()

    @pytest.mark.asyncio
    async def test_health_check_model_loaded_detection(self):
        """Test health check correctly detects if target model is loaded."""
        with patch("core.slm.provider.get_settings") as mock_settings:
            mock_slm = MagicMock()
            mock_slm.base_url = "http://ollama:11434"
            mock_slm.model = "phi3:3.8b-mini-instruct-4k-q4_K_M"
            mock_slm.fallback_model = "gemma2:2b"
            mock_slm.request_timeout_seconds = 30
            mock_slm.temperature = 0.1
            mock_slm.max_tokens = 50
            mock_slm.max_retries = 2
            mock_settings.return_value.slm = mock_slm

            from core.slm.provider import OllamaProvider

            mock_response = MagicMock()
            mock_response.json.return_value = {
                "models": [
                    {"name": "phi3:3.8b-mini-instruct-4k-q4_K_M"},
                    {"name": "llama2:7b"},
                ]
            }
            mock_response.raise_for_status = MagicMock()

            with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = mock_response

                provider = OllamaProvider()
                provider._client = httpx.AsyncClient(base_url="http://ollama:11434")

                health = await provider.health_check()

                assert health.available is True
                assert health.model_loaded is True
                assert "phi3" in health.model_name
                await provider.close()

    @pytest.mark.asyncio
    async def test_health_check_uses_fallback_model(self):
        """Test health check uses fallback model when primary not available."""
        with patch("core.slm.provider.get_settings") as mock_settings:
            mock_slm = MagicMock()
            mock_slm.base_url = "http://ollama:11434"
            mock_slm.model = "phi3"  # Not available
            mock_slm.fallback_model = "gemma2"  # Available
            mock_slm.request_timeout_seconds = 30
            mock_slm.temperature = 0.1
            mock_slm.max_tokens = 50
            mock_slm.max_retries = 2
            mock_settings.return_value.slm = mock_slm

            from core.slm.provider import OllamaProvider

            mock_response = MagicMock()
            mock_response.json.return_value = {
                "models": [{"name": "gemma2:2b-instruct-q4_K_M"}]
            }
            mock_response.raise_for_status = MagicMock()

            with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = mock_response

                provider = OllamaProvider()
                provider._client = httpx.AsyncClient(base_url="http://ollama:11434")

                health = await provider.health_check()

                assert health.available is True
                assert health.model_loaded is True
                assert "gemma2" in health.model_name
                await provider.close()


class TestOllamaProviderComplete:
    """Test OllamaProvider.complete() method."""

    @pytest.mark.asyncio
    async def test_complete_returns_response_text(self):
        """Test complete() returns the response text from Ollama."""
        with patch("core.slm.provider.get_settings") as mock_settings:
            mock_slm = MagicMock()
            mock_slm.base_url = "http://ollama:11434"
            mock_slm.model = "phi3"
            mock_slm.fallback_model = "gemma2"
            mock_slm.request_timeout_seconds = 30
            mock_slm.temperature = 0.1
            mock_slm.max_tokens = 50
            mock_slm.max_retries = 2
            mock_settings.return_value.slm = mock_slm

            from core.slm.provider import OllamaProvider

            mock_response = MagicMock()
            mock_response.json.return_value = {"response": "KEEP - technical discussion"}
            mock_response.raise_for_status = MagicMock()

            with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
                mock_post.return_value = mock_response

                provider = OllamaProvider()
                provider._client = httpx.AsyncClient(base_url="http://ollama:11434")
                provider._active_model = "phi3"

                result = await provider.complete("Test prompt")

                assert result == "KEEP - technical discussion"
                await provider.close()

    @pytest.mark.asyncio
    async def test_complete_raises_on_timeout(self):
        """Test complete() raises RuntimeError on timeout after retries."""
        with patch("core.slm.provider.get_settings") as mock_settings:
            mock_slm = MagicMock()
            mock_slm.base_url = "http://ollama:11434"
            mock_slm.model = "phi3"
            mock_slm.fallback_model = "gemma2"
            mock_slm.request_timeout_seconds = 1
            mock_slm.temperature = 0.1
            mock_slm.max_tokens = 50
            mock_slm.max_retries = 1
            mock_settings.return_value.slm = mock_slm

            from core.slm.provider import OllamaProvider

            with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
                mock_post.side_effect = httpx.TimeoutException("Request timed out")

                provider = OllamaProvider()
                provider._client = httpx.AsyncClient(base_url="http://ollama:11434")
                provider._active_model = "phi3"

                with pytest.raises(RuntimeError, match="timed out"):
                    await provider.complete("Test prompt")

                await provider.close()


class TestSLMHealthStatus:
    """Test SLMHealthStatus schema."""

    def test_health_status_default_values(self):
        """Test SLMHealthStatus has correct default values."""
        status = SLMHealthStatus()

        assert status.available is False
        assert status.model_loaded is False
        assert status.model_name is None
        assert status.error_message is None

    def test_health_status_with_values(self):
        """Test SLMHealthStatus with provided values."""
        status = SLMHealthStatus(
            available=True,
            model_loaded=True,
            model_name="phi3:latest",
            response_time_ms=150.5,
        )

        assert status.available is True
        assert status.model_loaded is True
        assert status.model_name == "phi3:latest"
        assert status.response_time_ms == 150.5


class TestGetSLMProvider:
    """Test get_slm_provider() singleton function."""

    def test_get_slm_provider_returns_same_instance(self):
        """Test get_slm_provider() returns the same instance on multiple calls."""
        with patch("core.slm.provider.get_settings") as mock_settings:
            mock_slm = MagicMock()
            mock_slm.base_url = "http://ollama:11434"
            mock_slm.model = "phi3"
            mock_slm.fallback_model = "gemma2"
            mock_slm.request_timeout_seconds = 30
            mock_slm.temperature = 0.1
            mock_slm.max_tokens = 50
            mock_slm.max_retries = 2
            mock_settings.return_value.slm = mock_slm

            # Reset singleton
            import core.slm.provider as provider_module
            provider_module._provider_instance = None

            from core.slm.provider import get_slm_provider

            provider1 = get_slm_provider()
            provider2 = get_slm_provider()

            assert provider1 is provider2

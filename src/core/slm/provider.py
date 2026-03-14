"""
Ollama SLM Provider

OpenAI-compatible interface to Ollama for local SLM inference.
Provides health checks, model management, and async completion API.
"""

import asyncio
import logging
import threading
import time

import httpx

from config import get_settings
from custom_types.slm_schemas import SLMHealthStatus

logger = logging.getLogger(__name__)


class OllamaProvider:
    """
    OpenAI-compatible interface to Ollama SLM.

    Provides async completion API with health checks and automatic fallback.
    Uses httpx for async HTTP requests to the Ollama API.

    Usage:
        provider = OllamaProvider()
        health = await provider.health_check()
        if health.available and health.model_loaded:
            response = await provider.complete("Your prompt here")
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        fallback_model: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        """
        Initialize the Ollama provider.

        Args:
            base_url: Ollama API base URL (default from config)
            model: Primary model name (default from config)
            fallback_model: Fallback model if primary unavailable (default from config)
            timeout_seconds: Request timeout (default from config)
        """
        settings = get_settings()
        slm_settings = settings.slm

        self.base_url = (base_url or slm_settings.base_url).rstrip("/")
        self.model = model or slm_settings.model
        self.fallback_model = fallback_model or slm_settings.fallback_model
        self.timeout_seconds = timeout_seconds or slm_settings.request_timeout_seconds
        self.temperature = slm_settings.temperature
        self.max_tokens = slm_settings.max_tokens
        self.max_retries = slm_settings.max_retries

        self._client: httpx.AsyncClient | None = None
        self._active_model: str | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout_seconds),
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _model_matches(self, target: str, available: str) -> bool:
        """
        Check if an available model matches the target model name.

        Handles Ollama's model naming with tags (e.g., phi3:latest, phi3:3.8b-mini-instruct-4k-q4_K_M).

        Args:
            target: The model name we're looking for
            available: The model name available in Ollama

        Returns:
            True if models match
        """
        # Extract base name (before first colon) for comparison
        target_base = target.split(":")[0].lower()
        available_base = available.split(":")[0].lower()

        # Exact match on base name, or full name match
        if target_base == available_base:
            return True
        if target.lower() == available.lower():
            return True

        return False

    async def health_check(self) -> SLMHealthStatus:
        """
        Check if Ollama service is available and model is loaded.

        Returns:
            SLMHealthStatus with availability info
        """
        start_time = time.time()
        status = SLMHealthStatus()

        try:
            client = await self._get_client()

            # Check if Ollama is responding
            response = await client.get("/api/tags")
            response.raise_for_status()

            status.available = True
            data = response.json()
            models = data.get("models", [])
            model_names = [m.get("name", "") for m in models]

            # Check if our target model is loaded
            for name in model_names:
                if self._model_matches(self.model, name):
                    status.model_loaded = True
                    status.model_name = name
                    self._active_model = name
                    break

            # Try fallback model if primary not available
            if not status.model_loaded and self.fallback_model:
                for name in model_names:
                    if self._model_matches(self.fallback_model, name):
                        status.model_loaded = True
                        status.model_name = name
                        self._active_model = name
                        logger.info(f"Using fallback SLM model: {name}")
                        break

            status.response_time_ms = (time.time() - start_time) * 1000

            if not status.model_loaded:
                status.error_message = f"Model '{self.model}' not loaded. " f"Available models: {model_names}. " f"Run: docker exec langtalks-ollama ollama pull {self.model}"
                logger.info(f"SLM model not loaded: {status.error_message}")

        except httpx.ConnectError as e:
            status.available = False
            status.error_message = f"Cannot connect to Ollama at {self.base_url}: {e}"
            logger.info(f"SLM service unavailable: {status.error_message}")

        except httpx.TimeoutException as e:
            status.available = False
            status.error_message = f"Ollama health check timed out: {e}"
            logger.info(f"SLM health check timeout: {status.error_message}")

        except Exception as e:
            status.available = False
            status.error_message = f"Ollama health check failed: {e}"
            logger.error(f"SLM health check error: {status.error_message}", exc_info=True)

        return status

    async def complete(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """
        Generate completion using Ollama.

        Uses the /api/generate endpoint for single-turn completions.

        Args:
            prompt: The prompt to complete
            model: Override model (default: active model from health check)
            temperature: Override temperature (default from config)
            max_tokens: Override max tokens (default from config)

        Returns:
            Generated text response

        Raises:
            RuntimeError: If Ollama is unavailable or generation fails after retries
        """
        use_model = model or self._active_model or self.model
        use_temperature = temperature if temperature is not None else self.temperature
        use_max_tokens = max_tokens if max_tokens is not None else self.max_tokens

        client = await self._get_client()

        payload = {
            "model": use_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": use_temperature,
                "num_predict": use_max_tokens,
            },
        }

        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = await client.post("/api/generate", json=payload)
                response.raise_for_status()

                data = response.json()
                return data.get("response", "").strip()

            except httpx.TimeoutException as e:
                last_error = e
                if attempt < self.max_retries:
                    wait_time = (attempt + 1) * 2
                    logger.warning(f"Ollama request timed out (attempt {attempt + 1}/{self.max_retries + 1}), " f"model={use_model}, retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                # Final attempt failed
                break

            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code >= 500 and attempt < self.max_retries:
                    wait_time = (attempt + 1) * 2
                    logger.warning(f"Ollama server error {e.response.status_code} (attempt {attempt + 1}/{self.max_retries + 1}), " f"model={use_model}, retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                # Client error or final attempt failed
                raise RuntimeError(f"Ollama API error: status={e.response.status_code}, " f"model={use_model}, response={e.response.text}") from e

            except Exception as e:
                # Unexpected error - don't retry
                raise RuntimeError(f"Ollama completion failed unexpectedly: {e}, model={use_model}") from e

        # All retries exhausted
        raise RuntimeError(f"Ollama request failed after {self.max_retries + 1} attempts: {last_error}, model={use_model}")

    async def ensure_model_loaded(self) -> bool:
        """
        Ensure the target model is loaded and ready.

        If model is not loaded, attempts to pull it (which may take time).

        Returns:
            True if model is ready, False otherwise
        """
        health = await self.health_check()

        if health.model_loaded:
            return True

        # Attempt to pull the model
        logger.info(f"Attempting to pull SLM model: {self.model} (this may take several minutes on first run)")

        try:
            client = await self._get_client()
            response = await client.post(
                "/api/pull",
                json={"name": self.model, "stream": False},
                timeout=httpx.Timeout(600.0),  # Model pull can take a while
            )
            response.raise_for_status()

            result = response.json()
            logger.info(f"SLM model pull completed: status={result.get('status', 'unknown')}")

            # Verify model is now available
            health = await self.health_check()
            return health.model_loaded

        except Exception as e:
            logger.error(f"Failed to pull SLM model {self.model}: {e}", exc_info=True)
            return False


# Thread-safe singleton provider instance
_provider_instance: OllamaProvider | None = None
_provider_lock = threading.Lock()


def get_slm_provider() -> OllamaProvider:
    """
    Get the singleton SLM provider instance.

    Thread-safe implementation using double-checked locking.

    Returns:
        OllamaProvider instance
    """
    global _provider_instance

    if _provider_instance is None:
        with _provider_lock:
            # Double-check after acquiring lock
            if _provider_instance is None:
                _provider_instance = OllamaProvider()

    return _provider_instance


async def reset_slm_provider() -> None:
    """Reset the singleton provider (useful for testing)."""
    global _provider_instance

    with _provider_lock:
        if _provider_instance is not None:
            await _provider_instance.close()
            _provider_instance = None

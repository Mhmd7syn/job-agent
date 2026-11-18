import os
import time
import random
import logging
from typing import Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash")

_RETRYABLE_PATTERNS = [
    "429",
    "503",
    "quota",
    "resource_exhausted",
    "resourceexhausted",
    "unavailable",
    "high demand",
    "spikes in demand",
    "overloaded",
    "10051",
    "10053",
    "10054",
    "10060",
    "getaddrinfo",
    "timeout",
    "timed out",
    "connection reset",
    "deadline exceeded",
]


def is_retryable_gemini_error(error: Exception) -> bool:
    """Checks whether an exception represents a retryable rate limit or transient glitch."""
    err_str = str(error).lower()
    return any(pattern in err_str for pattern in _RETRYABLE_PATTERNS)


def get_gemini_client(api_key: Optional[str] = None) -> Any:
    """
    Initializes and returns a Google GenAI Client with automatic decryption from config.
    Returns None if no valid API key is available or initialization fails.
    """
    raw_key = api_key or os.getenv("GEMINI_API_KEY")
    if not raw_key or raw_key.strip() in ("", "Your_GEMINI_API_KEY_Here"):
        return None

    try:
        from core.config import decrypt_value
        decrypted_key = decrypt_value(raw_key)
    except Exception:
        decrypted_key = raw_key

    if not decrypted_key or decrypted_key.strip() in ("", "Your_GEMINI_API_KEY_Here"):
        return None

    try:
        from google import genai
        return genai.Client(api_key=decrypted_key)
    except Exception as e:
        logger.warning(f"Failed to initialize google-genai Client: {e}")
        return None


def resolve_model_cascade(
    preferred_model: Optional[str] = None,
    models_to_try: Optional[List[str]] = None,
) -> List[str]:
    """Resolves an ordered, de-duplicated list of models to attempt."""
    if models_to_try:
        cascade = list(models_to_try)
    else:
        primary = preferred_model or DEFAULT_MODEL
        cascade = [primary]
        for candidate in (DEFAULT_MODEL, FALLBACK_MODEL):
            if candidate not in cascade:
                cascade.append(candidate)

    # De-duplicate while preserving order
    seen = set()
    result = []
    for m in cascade:
        if m and m not in seen:
            seen.add(m)
            result.append(m)
    return result


def _prepare_call_config(model_name: str, config: Any) -> Any:
    """Ensures models with reasoning capabilities (like gemini-2.5-flash) do not exhaust max_output_tokens on thinking."""
    if not config or "2.5-flash" not in model_name:
        return config

    try:
        import copy
        from google.genai import types
        # If thinking_config is not explicitly configured, disable thinking budget to prevent truncation
        if hasattr(config, "thinking_config") and config.thinking_config is None:
            config_copy = copy.copy(config)
            config_copy.thinking_config = types.ThinkingConfig(thinking_budget=0)
            return config_copy
    except Exception:
        pass
    return config


def generate_content_resilient(
    contents: Any,
    config: Any = None,
    client: Any = None,
    preferred_model: Optional[str] = None,
    models_to_try: Optional[List[str]] = None,
    max_retries_per_model: int = 2,
    base_delay: float = 1.0,
) -> Tuple[Any, str]:
    """
    Executes content generation across a tiered model cascade with exponential backoff and jitter.

    Returns:
        (response, model_name) on success.
    Raises:
        RuntimeError: if no client is available or all models and retries are exhausted.
    """
    active_client = client if client is not None else get_gemini_client()
    if active_client is None:
        raise RuntimeError("Gemini client is not initialized or GEMINI_API_KEY is missing.")

    cascade = resolve_model_cascade(
        preferred_model=preferred_model,
        models_to_try=models_to_try,
    )

    last_error: Optional[Exception] = None

    for model_name in cascade:
        call_config = _prepare_call_config(model_name, config)
        for attempt in range(max_retries_per_model):
            try:
                response = active_client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=call_config,
                )
                return response, model_name
            except Exception as e:
                last_error = e
                if is_retryable_gemini_error(e):
                    if attempt < max_retries_per_model - 1:
                        jitter = random.uniform(0.1, 0.4)
                        wait_time = (base_delay * (2 ** attempt)) + jitter
                        logger.warning(
                            f"Gemini API rate limit or transient issue on {model_name} "
                            f"(attempt {attempt + 1}/{max_retries_per_model}): {e}. Retrying in {wait_time:.2f}s..."
                        )
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.warning(
                            f"Exhausted {max_retries_per_model} attempts on {model_name} ({e}). "
                            "Failing over to next model in cascade..."
                        )
                        break
                else:
                    logger.warning(
                        f"Non-retryable or fatal error on model {model_name}: {e}. "
                        "Failing over to next model if available..."
                    )
                    break

    raise RuntimeError(
        f"All Gemini models exhausted ({cascade}). Last error: {last_error}"
    ) from last_error

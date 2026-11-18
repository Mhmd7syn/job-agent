import os
import pytest
from unittest.mock import MagicMock, patch

from core.gemini_client import (
    is_retryable_gemini_error,
    resolve_model_cascade,
    get_gemini_client,
    generate_content_resilient,
    DEFAULT_MODEL,
    FALLBACK_MODEL,
)


def test_is_retryable_gemini_error():
    assert is_retryable_gemini_error(Exception("429 ResourceExhausted")) is True
    assert is_retryable_gemini_error(Exception("Quota exceeded for quota metric")) is True
    assert is_retryable_gemini_error(Exception("503 UNAVAILABLE: high demand")) is True
    assert is_retryable_gemini_error(Exception("WinError 10054 Connection reset")) is True
    assert is_retryable_gemini_error(ValueError("Invalid argument: prompt is required")) is False


def test_resolve_model_cascade():
    cascade = resolve_model_cascade()
    assert cascade[0] == DEFAULT_MODEL
    assert FALLBACK_MODEL in cascade

    custom_cascade = resolve_model_cascade(preferred_model="gemini-custom-model")
    assert custom_cascade[0] == "gemini-custom-model"
    assert FALLBACK_MODEL in custom_cascade

    fallback_preferred = resolve_model_cascade(preferred_model=FALLBACK_MODEL)
    assert fallback_preferred == [FALLBACK_MODEL, DEFAULT_MODEL]

    explicit = resolve_model_cascade(models_to_try=["model-a", "model-b"])
    assert explicit == ["model-a", "model-b"]


def test_generate_content_resilient_success_first_try():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '{"status": "ok"}'
    mock_client.models.generate_content.return_value = mock_response

    resp, model_used = generate_content_resilient(
        contents="Hello",
        client=mock_client,
        preferred_model="gemini-flash-lite-latest",
        base_delay=0.01,
    )

    assert resp == mock_response
    assert model_used == "gemini-flash-lite-latest"
    mock_client.models.generate_content.assert_called_once()
    assert mock_client.models.generate_content.call_args[1]["model"] == "gemini-flash-lite-latest"


def test_generate_content_resilient_falls_back_on_quota():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '{"status": "success from fallback"}'

    def mock_generate(model, contents, config=None):
        if model == "gemini-flash-lite-latest":
            raise RuntimeError("429 RESOURCE_EXHAUSTED: rate limit exceeded")
        return mock_response

    mock_client.models.generate_content.side_effect = mock_generate

    resp, model_used = generate_content_resilient(
        contents="Test prompt",
        client=mock_client,
        preferred_model="gemini-flash-lite-latest",
        models_to_try=["gemini-flash-lite-latest", "gemini-2.5-flash"],
        max_retries_per_model=2,
        base_delay=0.01,
    )

    assert resp == mock_response
    assert model_used == "gemini-2.5-flash"
    # Primary model called max_retries (2 times) + secondary model called 1 time = 3 calls
    assert mock_client.models.generate_content.call_count == 3


def test_generate_content_resilient_all_models_exhausted():
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError("429 Quota exhausted")

    with pytest.raises(RuntimeError) as exc_info:
        generate_content_resilient(
            contents="Test prompt",
            client=mock_client,
            models_to_try=["model-1", "model-2"],
            max_retries_per_model=1,
            base_delay=0.01,
        )

    assert "All Gemini models exhausted" in str(exc_info.value)
    assert "Quota exhausted" in str(exc_info.value)


def test_generate_content_resilient_missing_client():
    with patch("core.gemini_client.get_gemini_client", return_value=None):
        with pytest.raises(RuntimeError) as exc_info:
            generate_content_resilient(
                contents="Test prompt",
                client=None,
            )
        assert "not initialized" in str(exc_info.value)


def test_get_gemini_client_missing_key():
    with patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=True):
        client = get_gemini_client(api_key="")
        assert client is None

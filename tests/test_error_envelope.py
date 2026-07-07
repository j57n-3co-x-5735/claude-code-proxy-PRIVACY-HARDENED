"""Tests for Anthropic error envelope format (plan item 1.2)."""
import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from src.main import app


def make_headers():
    return {"x-api-key": "test-key", "content-type": "application/json"}


def assert_anthropic_envelope(response_json, expected_type):
    assert response_json["type"] == "error"
    assert "error" in response_json
    assert response_json["error"]["type"] == expected_type
    assert "message" in response_json["error"]


@pytest.mark.asyncio
async def test_auth_error_returns_envelope():
    """401 auth error returns authentication_error envelope."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("src.api.endpoints.config") as mock_config:
            mock_config.anthropic_api_key = "real-key"
            mock_config.validate_client_api_key = MagicMock(return_value=False)

            response = await client.post(
                "/v1/messages",
                json={"model": "test", "max_tokens": 100, "messages": [{"role": "user", "content": "hi"}]},
                headers={"x-api-key": "wrong-key", "content-type": "application/json"},
            )
            assert response.status_code == 401
            assert_anthropic_envelope(response.json(), "authentication_error")


@pytest.mark.asyncio
async def test_validation_error_returns_envelope():
    """Pydantic validation error returns invalid_request_error envelope."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/messages",
            json={"model": "test"},
            headers=make_headers(),
        )
        assert response.status_code == 400
        data = response.json()
        assert_anthropic_envelope(data, "invalid_request_error")
        assert "loc" not in json.dumps(data)


@pytest.mark.asyncio
async def test_500_error_returns_envelope():
    """Internal server error returns api_error envelope."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("src.api.endpoints.convert_claude_to_openai", side_effect=RuntimeError("kaboom")):
            response = await client.post(
                "/v1/messages",
                json={"model": "test", "max_tokens": 100, "messages": [{"role": "user", "content": "hi"}]},
                headers=make_headers(),
            )
            assert response.status_code == 500
            data = response.json()
            assert_anthropic_envelope(data, "api_error")
            assert "kaboom" not in data["error"]["message"]


@pytest.mark.asyncio
async def test_client_exception_sanitized():
    """Generic exceptions in OpenAIClient go through classify_openai_error."""
    from src.core.client import OpenAIClient

    obj = OpenAIClient.__new__(OpenAIClient)
    result = obj.classify_openai_error("some random fireworks error with account_id=abc123")
    assert result == "Backend API error. Check proxy logs for details."


@pytest.mark.asyncio
async def test_streaming_setup_error_type_mapping():
    """Streaming setup errors use correct Anthropic error type per status code."""
    from fastapi import HTTPException

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch(
            "src.api.endpoints.openai_client.create_chat_completion_stream",
            side_effect=HTTPException(status_code=401, detail="Invalid API key"),
        ):
            response = await client.post(
                "/v1/messages",
                json={"model": "test", "max_tokens": 100, "messages": [{"role": "user", "content": "hi"}], "stream": True},
                headers=make_headers(),
            )
            assert response.status_code == 401
            data = response.json()
            assert_anthropic_envelope(data, "authentication_error")


@pytest.mark.asyncio
async def test_streaming_error_no_leak():
    """Streaming errors in response_converter don't leak raw exception text."""
    from src.conversion.response_converter import convert_openai_streaming_to_claude_with_cancellation
    from src.models.claude import ClaudeMessagesRequest

    request = ClaudeMessagesRequest(
        model="test", max_tokens=100, messages=[{"role": "user", "content": "hi"}]
    )

    async def failing_stream():
        yield "data: bad json that will cause an error"
        raise RuntimeError("secret internal error details")

    mock_logger = MagicMock()
    mock_http_request = AsyncMock()
    mock_http_request.is_disconnected = AsyncMock(return_value=False)
    mock_client = MagicMock()

    events = []
    async for event_str in convert_openai_streaming_to_claude_with_cancellation(
        failing_stream(), request, mock_logger, mock_http_request, mock_client, "req-1"
    ):
        events.append(event_str)

    all_text = "".join(events)
    assert "secret internal error details" not in all_text
    assert "Check proxy logs" in all_text


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code,expected_type", [
    (400, "invalid_request_error"),
    (401, "authentication_error"),
    (403, "permission_error"),
    (404, "not_found_error"),
    (429, "rate_limit_error"),
    (500, "api_error"),
    (502, "api_error"),
])
async def test_http_exception_envelope_by_status_code(status_code, expected_type):
    """Each HTTP status code maps to the correct Anthropic error type."""
    from src.main import http_exception_handler
    from fastapi import HTTPException, Request

    exc = HTTPException(status_code=status_code, detail="test error")
    response = await http_exception_handler(None, exc)
    data = json.loads(response.body)
    assert_anthropic_envelope(data, expected_type)

"""Tests for request conversion (tool_choice, metadata, message handling)."""
import json
import pytest
from unittest.mock import MagicMock

from src.conversion.request_converter import convert_claude_to_openai
from src.models.claude import ClaudeMessagesRequest


def make_model_manager(model="test-model"):
    mgr = MagicMock()
    mgr.map_claude_model_to_openai.return_value = model
    return mgr


def make_request(**kwargs):
    defaults = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 100,
        "messages": [{"role": "user", "content": "hello"}],
    }
    defaults.update(kwargs)
    return ClaudeMessagesRequest(**defaults)


def test_tool_choice_any_maps_to_required():
    request = make_request(
        tools=[{"name": "fn", "input_schema": {"type": "object"}}],
        tool_choice={"type": "any"},
    )
    result = convert_claude_to_openai(request, make_model_manager())
    assert result["tool_choice"] == "required"


def test_tool_choice_auto_maps_to_auto():
    request = make_request(
        tools=[{"name": "fn", "input_schema": {"type": "object"}}],
        tool_choice={"type": "auto"},
    )
    result = convert_claude_to_openai(request, make_model_manager())
    assert result["tool_choice"] == "auto"


def test_tool_choice_tool_maps_to_function():
    request = make_request(
        tools=[{"name": "read_file", "input_schema": {"type": "object"}}],
        tool_choice={"type": "tool", "name": "read_file"},
    )
    result = convert_claude_to_openai(request, make_model_manager())
    assert result["tool_choice"] == {"type": "function", "function": {"name": "read_file"}}


def test_tool_choice_unknown_defaults_to_auto():
    request = make_request(
        tools=[{"name": "fn", "input_schema": {"type": "object"}}],
        tool_choice={"type": "something_new"},
    )
    result = convert_claude_to_openai(request, make_model_manager())
    assert result["tool_choice"] == "auto"


def test_metadata_user_id_mapped_to_user():
    request = make_request(metadata={"user_id": "user-123"})
    result = convert_claude_to_openai(request, make_model_manager())
    assert result["user"] == "user-123"


def test_metadata_without_user_id_no_user_field():
    request = make_request(metadata={"some_other": "value"})
    result = convert_claude_to_openai(request, make_model_manager())
    assert "user" not in result


def test_no_metadata_no_user_field():
    request = make_request()
    result = convert_claude_to_openai(request, make_model_manager())
    assert "user" not in result


def test_string_content_converted():
    request = make_request(messages=[{"role": "user", "content": "hello world"}])
    result = convert_claude_to_openai(request, make_model_manager())
    user_msg = [m for m in result["messages"] if m["role"] == "user"][0]
    assert user_msg["content"] == "hello world"


def test_system_string_becomes_system_message():
    request = make_request(system="You are helpful.")
    result = convert_claude_to_openai(request, make_model_manager())
    assert result["messages"][0]["role"] == "system"
    assert result["messages"][0]["content"] == "You are helpful."


def test_system_list_joined():
    request = make_request(system=[{"type": "text", "text": "Part one."}, {"type": "text", "text": "Part two."}])
    result = convert_claude_to_openai(request, make_model_manager())
    assert result["messages"][0]["role"] == "system"
    assert "Part one." in result["messages"][0]["content"]
    assert "Part two." in result["messages"][0]["content"]


def test_thinking_config_passed_through():
    request = make_request(thinking={"type": "enabled", "budget_tokens": 5000})
    result = convert_claude_to_openai(request, make_model_manager())
    assert result["thinking"] == {"type": "enabled", "budget_tokens": 5000}


def test_thinking_disabled_not_passed():
    request = make_request(thinking={"type": "disabled"})
    result = convert_claude_to_openai(request, make_model_manager())
    assert "thinking" not in result

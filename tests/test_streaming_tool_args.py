"""Tests for streaming tool argument delta emission (plan item 1.3)."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.conversion.response_converter import convert_openai_streaming_to_claude_with_cancellation
from src.models.claude import ClaudeMessagesRequest


def make_request(model="claude-sonnet-4-20250514"):
    return ClaudeMessagesRequest(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": "test"}],
    )


def chunk_line(delta, finish_reason=None, usage=None):
    chunk = {
        "choices": [{"delta": delta, "finish_reason": finish_reason}],
    }
    if usage:
        chunk["usage"] = usage
    return f"data: {json.dumps(chunk)}"


async def collect_events(stream_lines, request=None):
    request = request or make_request()
    mock_logger = MagicMock()
    mock_http_request = AsyncMock()
    mock_http_request.is_disconnected = AsyncMock(return_value=False)
    mock_client = MagicMock()

    async def mock_stream():
        for line in stream_lines:
            yield line

    events = []
    async for event_str in convert_openai_streaming_to_claude_with_cancellation(
        mock_stream(), request, mock_logger, mock_http_request, mock_client, "req-1"
    ):
        for part in event_str.strip().split("\n\n"):
            if part.startswith("event: "):
                lines = part.split("\n")
                event_type = lines[0].replace("event: ", "")
                data = json.loads(lines[1].replace("data: ", ""))
                events.append((event_type, data))
    return events


@pytest.mark.asyncio
async def test_single_tool_call_incremental_deltas():
    """Each non-empty argument fragment produces a content_block_delta."""
    lines = [
        chunk_line({"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": ""}}]}),
        chunk_line({"tool_calls": [{"index": 0, "function": {"arguments": '{"pa'}}]}),
        chunk_line({"tool_calls": [{"index": 0, "function": {"arguments": 'th":'}}]}),
        chunk_line({"tool_calls": [{"index": 0, "function": {"arguments": ' "test.py"}'}}]}),
        chunk_line({}, finish_reason="tool_calls", usage={"prompt_tokens": 10, "completion_tokens": 5}),
    ]
    events = await collect_events(lines)

    tool_deltas = [
        (et, d) for et, d in events
        if et == "content_block_delta" and d.get("delta", {}).get("type") == "input_json_delta"
    ]
    assert len(tool_deltas) == 3
    assert tool_deltas[0][1]["delta"]["partial_json"] == '{"pa'
    assert tool_deltas[1][1]["delta"]["partial_json"] == 'th":'
    assert tool_deltas[2][1]["delta"]["partial_json"] == ' "test.py"}'


@pytest.mark.asyncio
async def test_empty_argument_fragments_skipped():
    """Empty string arguments should not produce a delta event."""
    lines = [
        chunk_line({"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "fn", "arguments": ""}}]}),
        chunk_line({"tool_calls": [{"index": 0, "function": {"arguments": ""}}]}),
        chunk_line({"tool_calls": [{"index": 0, "function": {"arguments": "{}"}}]}),
        chunk_line({}, finish_reason="tool_calls", usage={"prompt_tokens": 10, "completion_tokens": 5}),
    ]
    events = await collect_events(lines)

    tool_deltas = [
        (et, d) for et, d in events
        if et == "content_block_delta" and d.get("delta", {}).get("type") == "input_json_delta"
    ]
    assert len(tool_deltas) == 1
    assert tool_deltas[0][1]["delta"]["partial_json"] == "{}"


@pytest.mark.asyncio
async def test_null_argument_fragments_skipped():
    """None arguments should not produce a delta event."""
    lines = [
        chunk_line({"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "fn", "arguments": None}}]}),
        chunk_line({"tool_calls": [{"index": 0, "function": {"arguments": "{}"}}]}),
        chunk_line({}, finish_reason="tool_calls", usage={"prompt_tokens": 10, "completion_tokens": 5}),
    ]
    events = await collect_events(lines)

    tool_deltas = [
        (et, d) for et, d in events
        if et == "content_block_delta" and d.get("delta", {}).get("type") == "input_json_delta"
    ]
    assert len(tool_deltas) == 1


@pytest.mark.asyncio
async def test_tool_call_sse_sequence():
    """Verify the complete SSE event sequence for a tool call."""
    lines = [
        chunk_line({"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "fn", "arguments": ""}}]}),
        chunk_line({"tool_calls": [{"index": 0, "function": {"arguments": '{"x": 1}'}}]}),
        chunk_line({}, finish_reason="tool_calls", usage={"prompt_tokens": 10, "completion_tokens": 5}),
    ]
    events = await collect_events(lines)

    event_types = [et for et, _ in events]
    assert "message_start" in event_types
    assert "content_block_start" in event_types
    assert "content_block_delta" in event_types
    assert "content_block_stop" in event_types
    assert "message_delta" in event_types
    assert "message_stop" in event_types

    block_starts = [(et, d) for et, d in events if et == "content_block_start"]
    tool_start = [d for _, d in block_starts if d["content_block"]["type"] == "tool_use"]
    assert len(tool_start) == 1
    assert tool_start[0]["content_block"]["name"] == "fn"
    assert tool_start[0]["content_block"]["id"] == "call_1"


@pytest.mark.asyncio
async def test_multiple_concurrent_tool_calls():
    """Multiple tool calls get correct block indices."""
    lines = [
        chunk_line({"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "fn1", "arguments": ""}}]}),
        chunk_line({"tool_calls": [{"index": 1, "id": "call_2", "type": "function", "function": {"name": "fn2", "arguments": ""}}]}),
        chunk_line({"tool_calls": [{"index": 0, "function": {"arguments": '{"a": 1}'}}]}),
        chunk_line({"tool_calls": [{"index": 1, "function": {"arguments": '{"b": 2}'}}]}),
        chunk_line({}, finish_reason="tool_calls", usage={"prompt_tokens": 10, "completion_tokens": 5}),
    ]
    events = await collect_events(lines)

    block_starts = [(et, d) for et, d in events if et == "content_block_start" and d["content_block"]["type"] == "tool_use"]
    assert len(block_starts) == 2
    indices = [d["index"] for _, d in block_starts]
    assert indices[0] != indices[1]

    tool_deltas = [
        d for et, d in events
        if et == "content_block_delta" and d.get("delta", {}).get("type") == "input_json_delta"
    ]
    assert len(tool_deltas) == 2
    delta_indices = {d["index"] for d in tool_deltas}
    assert delta_indices == set(indices)


@pytest.mark.asyncio
async def test_thinking_block_offset():
    """Tool call block indices account for thinking block offset."""
    lines = [
        chunk_line({"reasoning_content": "Let me think..."}),
        chunk_line({"content": "Here's the result"}),
        chunk_line({"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "fn", "arguments": ""}}]}),
        chunk_line({"tool_calls": [{"index": 0, "function": {"arguments": "{}"}}]}),
        chunk_line({}, finish_reason="tool_calls", usage={"prompt_tokens": 10, "completion_tokens": 5}),
    ]
    events = await collect_events(lines)

    block_starts = [(et, d) for et, d in events if et == "content_block_start"]
    assert len(block_starts) == 3

    thinking_idx = block_starts[0][1]["index"]
    text_idx = block_starts[1][1]["index"]
    tool_idx = block_starts[2][1]["index"]
    assert thinking_idx == 0
    assert text_idx == 1
    assert tool_idx == 2


@pytest.mark.asyncio
async def test_text_block_closed_before_tool_block_starts():
    """Text content_block_stop must appear before tool content_block_start."""
    lines = [
        chunk_line({"content": "I'll use a tool"}),
        chunk_line({"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "fn", "arguments": ""}}]}),
        chunk_line({"tool_calls": [{"index": 0, "function": {"arguments": "{}"}}]}),
        chunk_line({}, finish_reason="tool_calls", usage={"prompt_tokens": 10, "completion_tokens": 5}),
    ]
    events = await collect_events(lines)

    event_types_with_indices = [
        (et, d.get("index"), d.get("content_block", {}).get("type", ""))
        for et, d in events
        if et in ("content_block_start", "content_block_stop")
    ]

    text_stop_pos = None
    tool_start_pos = None
    for i, (et, idx, block_type) in enumerate(event_types_with_indices):
        if et == "content_block_stop" and idx == 0:
            text_stop_pos = i
        if et == "content_block_start" and block_type == "tool_use":
            tool_start_pos = i

    assert text_stop_pos is not None, "text block was never closed"
    assert tool_start_pos is not None, "tool block was never started"
    assert text_stop_pos < tool_start_pos, f"text block closed at position {text_stop_pos} but tool started at {tool_start_pos}"

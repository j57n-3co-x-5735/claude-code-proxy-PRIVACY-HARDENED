import json
import logging
import uuid
from fastapi import HTTPException, Request
from src.core.constants import Constants
from src.models.claude import ClaudeMessagesRequest

_logger = logging.getLogger(__name__)


def convert_openai_to_claude_response(
    openai_response: dict, original_request: ClaudeMessagesRequest
) -> dict:
    """Convert OpenAI response to Claude format."""

    # Extract response data
    choices = openai_response.get("choices", [])
    if not choices:
        raise HTTPException(status_code=500, detail="No choices in OpenAI response")

    choice = choices[0]
    message = choice.get("message", {})

    # Build Claude content blocks
    content_blocks = []

    # Add reasoning/thinking content if present
    reasoning = message.get("reasoning_content")
    if reasoning:
        content_blocks.append({"type": "thinking", "thinking": reasoning, "signature": ""})

    # Add text content
    text_content = message.get("content")
    if text_content is not None:
        content_blocks.append({"type": Constants.CONTENT_TEXT, "text": text_content})

    # Add tool calls
    tool_calls = message.get("tool_calls", []) or []
    for tool_call in tool_calls:
        if tool_call.get("type") == Constants.TOOL_FUNCTION:
            function_data = tool_call.get(Constants.TOOL_FUNCTION, {})
            try:
                arguments = json.loads(function_data.get("arguments", "{}"))
            except json.JSONDecodeError:
                arguments = {"raw_arguments": function_data.get("arguments", "")}

            content_blocks.append(
                {
                    "type": Constants.CONTENT_TOOL_USE,
                    "id": tool_call.get("id", f"tool_{uuid.uuid4()}"),
                    "name": function_data.get("name", ""),
                    "input": arguments,
                }
            )

    if message.get("citations") or message.get("annotations"):
        _logger.debug("Upstream response contained citation/annotation data that was not converted")

    # Ensure at least one content block
    if not content_blocks:
        content_blocks.append({"type": Constants.CONTENT_TEXT, "text": ""})

    # Map finish reason
    finish_reason = choice.get("finish_reason", "stop")
    stop_reason_map = {
        "stop": Constants.STOP_END_TURN,
        "length": Constants.STOP_MAX_TOKENS,
        "tool_calls": Constants.STOP_TOOL_USE,
        "function_call": Constants.STOP_TOOL_USE,
        "content_filter": Constants.STOP_END_TURN,
    }
    stop_reason = stop_reason_map.get(finish_reason)
    if stop_reason is None:
        _logger.warning(f"Unknown finish_reason from upstream: {finish_reason}, defaulting to end_turn")
        stop_reason = Constants.STOP_END_TURN
    elif finish_reason == "content_filter":
        _logger.warning("Upstream returned content_filter finish_reason — response was truncated by safety filtering, mapped to end_turn")

    # Build Claude response
    claude_response = {
        "id": openai_response.get("id", f"msg_{uuid.uuid4()}"),
        "type": "message",
        "role": Constants.ROLE_ASSISTANT,
        "model": original_request.model,
        "content": content_blocks,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": openai_response.get("usage", {}).get("prompt_tokens", 0),
            "output_tokens": openai_response.get("usage", {}).get(
                "completion_tokens", 0
            ),
            "cache_read_input_tokens": openai_response.get("usage", {}).get(
                "prompt_tokens_details", {}
            ).get("cached_tokens", 0) if openai_response.get("usage", {}).get("prompt_tokens_details") else 0,
        },
    }

    return claude_response


async def convert_openai_streaming_to_claude_with_cancellation(
    openai_stream,
    original_request: ClaudeMessagesRequest,
    logger,
    http_request: Request,
    openai_client,
    request_id: str,
):
    """Convert OpenAI streaming response to Claude streaming format with cancellation support."""

    message_id = f"msg_{uuid.uuid4().hex[:24]}"

    # Send initial SSE events
    yield f"event: {Constants.EVENT_MESSAGE_START}\ndata: {json.dumps({'type': Constants.EVENT_MESSAGE_START, 'message': {'id': message_id, 'type': 'message', 'role': Constants.ROLE_ASSISTANT, 'model': original_request.model, 'content': [], 'stop_reason': None, 'stop_sequence': None, 'usage': {'input_tokens': 0, 'output_tokens': 0}}}, ensure_ascii=False)}\n\n"

    yield f"event: {Constants.EVENT_PING}\ndata: {json.dumps({'type': Constants.EVENT_PING}, ensure_ascii=False)}\n\n"

    # Process streaming chunks
    thinking_block_started = False
    thinking_block_index = -1
    text_block_started = False
    text_block_index = -1
    next_block_index = 0
    current_tool_calls = {}
    final_stop_reason = Constants.STOP_END_TURN
    usage_data = {"input_tokens": 0, "output_tokens": 0}

    try:
        async for line in openai_stream:
            # Check if client disconnected
            if await http_request.is_disconnected():
                logger.info(f"Client disconnected, cancelling request {request_id}")
                openai_client.cancel_request(request_id)
                break

            if line.strip():
                if line.startswith("data: "):
                    chunk_data = line[6:]
                    if chunk_data.strip() == "[DONE]":
                        break

                    try:
                        chunk = json.loads(chunk_data)
                        usage = chunk.get("usage", None)
                        if usage:
                            cache_read_input_tokens = 0
                            prompt_tokens_details = usage.get('prompt_tokens_details', {})
                            if prompt_tokens_details:
                                cache_read_input_tokens = prompt_tokens_details.get('cached_tokens', 0)
                            usage_data = {
                                'input_tokens': usage.get('prompt_tokens', 0),
                                'output_tokens': usage.get('completion_tokens', 0),
                                'cache_read_input_tokens': cache_read_input_tokens
                            }
                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                    except json.JSONDecodeError as e:
                        logger.warning(
                            f"Failed to parse chunk: {chunk_data}, error: {e}"
                        )
                        continue

                    choice = choices[0]
                    delta = choice.get("delta", {})
                    finish_reason = choice.get("finish_reason")

                    # Handle reasoning/thinking delta (arrives before content)
                    if delta and "reasoning_content" in delta and delta["reasoning_content"] is not None:
                        if not thinking_block_started:
                            thinking_block_index = next_block_index
                            next_block_index += 1
                            thinking_block_started = True
                            yield f"event: {Constants.EVENT_CONTENT_BLOCK_START}\ndata: {json.dumps({'type': Constants.EVENT_CONTENT_BLOCK_START, 'index': thinking_block_index, 'content_block': {'type': 'thinking', 'thinking': '', 'signature': ''}}, ensure_ascii=False)}\n\n"
                        yield f"event: {Constants.EVENT_CONTENT_BLOCK_DELTA}\ndata: {json.dumps({'type': Constants.EVENT_CONTENT_BLOCK_DELTA, 'index': thinking_block_index, 'delta': {'type': 'thinking_delta', 'thinking': delta['reasoning_content']}}, ensure_ascii=False)}\n\n"

                    # Handle text delta
                    if delta and "content" in delta and delta["content"] is not None:
                        if not text_block_started:
                            if thinking_block_started:
                                yield f"event: {Constants.EVENT_CONTENT_BLOCK_STOP}\ndata: {json.dumps({'type': Constants.EVENT_CONTENT_BLOCK_STOP, 'index': thinking_block_index}, ensure_ascii=False)}\n\n"
                            text_block_index = next_block_index
                            next_block_index += 1
                            text_block_started = True
                            yield f"event: {Constants.EVENT_CONTENT_BLOCK_START}\ndata: {json.dumps({'type': Constants.EVENT_CONTENT_BLOCK_START, 'index': text_block_index, 'content_block': {'type': Constants.CONTENT_TEXT, 'text': ''}}, ensure_ascii=False)}\n\n"
                        yield f"event: {Constants.EVENT_CONTENT_BLOCK_DELTA}\ndata: {json.dumps({'type': Constants.EVENT_CONTENT_BLOCK_DELTA, 'index': text_block_index, 'delta': {'type': Constants.DELTA_TEXT, 'text': delta['content']}}, ensure_ascii=False)}\n\n"

                    # Handle tool call deltas with improved incremental processing
                    if "tool_calls" in delta and delta["tool_calls"]:
                        for tc_delta in delta["tool_calls"]:
                            tc_index = tc_delta.get("index", 0)

                            if tc_index not in current_tool_calls:
                                current_tool_calls[tc_index] = {
                                    "id": None,
                                    "name": None,
                                    "claude_index": None,
                                    "started": False,
                                }

                            tool_call = current_tool_calls[tc_index]

                            if tc_delta.get("id"):
                                tool_call["id"] = tc_delta["id"]

                            function_data = tc_delta.get(Constants.TOOL_FUNCTION, {})
                            if function_data.get("name"):
                                tool_call["name"] = function_data["name"]

                            if (tool_call["id"] and tool_call["name"] and not tool_call["started"]):
                                if text_block_started:
                                    yield f"event: {Constants.EVENT_CONTENT_BLOCK_STOP}\ndata: {json.dumps({'type': Constants.EVENT_CONTENT_BLOCK_STOP, 'index': text_block_index}, ensure_ascii=False)}\n\n"
                                    text_block_started = False
                                elif thinking_block_started:
                                    yield f"event: {Constants.EVENT_CONTENT_BLOCK_STOP}\ndata: {json.dumps({'type': Constants.EVENT_CONTENT_BLOCK_STOP, 'index': thinking_block_index}, ensure_ascii=False)}\n\n"
                                    thinking_block_started = False

                                claude_index = next_block_index
                                next_block_index += 1
                                tool_call["claude_index"] = claude_index
                                tool_call["started"] = True

                                yield f"event: {Constants.EVENT_CONTENT_BLOCK_START}\ndata: {json.dumps({'type': Constants.EVENT_CONTENT_BLOCK_START, 'index': claude_index, 'content_block': {'type': Constants.CONTENT_TOOL_USE, 'id': tool_call['id'], 'name': tool_call['name'], 'input': {}}}, ensure_ascii=False)}\n\n"

                            if tool_call["started"] and function_data.get("arguments"):
                                yield f"event: {Constants.EVENT_CONTENT_BLOCK_DELTA}\ndata: {json.dumps({'type': Constants.EVENT_CONTENT_BLOCK_DELTA, 'index': tool_call['claude_index'], 'delta': {'type': Constants.DELTA_INPUT_JSON, 'partial_json': function_data['arguments']}}, ensure_ascii=False)}\n\n"

                    # Handle finish reason
                    if finish_reason:
                        reason_map = {
                            "stop": Constants.STOP_END_TURN,
                            "length": Constants.STOP_MAX_TOKENS,
                            "tool_calls": Constants.STOP_TOOL_USE,
                            "function_call": Constants.STOP_TOOL_USE,
                            "content_filter": Constants.STOP_END_TURN,
                        }
                        mapped = reason_map.get(finish_reason)
                        if mapped is None:
                            logger.warning(f"Unknown finish_reason from upstream: {finish_reason}, defaulting to end_turn")
                            final_stop_reason = Constants.STOP_END_TURN
                        else:
                            if finish_reason == "content_filter":
                                logger.warning("Upstream returned content_filter finish_reason — response was truncated by safety filtering, mapped to end_turn")
                            final_stop_reason = mapped

    except HTTPException as e:
        # Handle cancellation
        if e.status_code == 499:
            logger.info(f"Request {request_id} was cancelled")
            error_event = {
                "type": "error",
                "error": {
                    "type": "cancelled",
                    "message": "Request was cancelled by client",
                },
            }
            yield f"event: error\ndata: {json.dumps(error_event, ensure_ascii=False)}\n\n"
            return
        else:
            raise
    except Exception as e:
        logger.error(f"Streaming error: {e}")
        import traceback

        logger.error(traceback.format_exc())
        error_event = {
            "type": "error",
            "error": {"type": "api_error", "message": "A streaming error occurred. Check proxy logs for details."},
        }
        yield f"event: error\ndata: {json.dumps(error_event, ensure_ascii=False)}\n\n"
        return

    # Send final SSE events — close any open blocks
    if text_block_started:
        yield f"event: {Constants.EVENT_CONTENT_BLOCK_STOP}\ndata: {json.dumps({'type': Constants.EVENT_CONTENT_BLOCK_STOP, 'index': text_block_index}, ensure_ascii=False)}\n\n"
    elif thinking_block_started:
        yield f"event: {Constants.EVENT_CONTENT_BLOCK_STOP}\ndata: {json.dumps({'type': Constants.EVENT_CONTENT_BLOCK_STOP, 'index': thinking_block_index}, ensure_ascii=False)}\n\n"

    for tool_data in current_tool_calls.values():
        if tool_data.get("started") and tool_data.get("claude_index") is not None:
            yield f"event: {Constants.EVENT_CONTENT_BLOCK_STOP}\ndata: {json.dumps({'type': Constants.EVENT_CONTENT_BLOCK_STOP, 'index': tool_data['claude_index']}, ensure_ascii=False)}\n\n"

    yield f"event: {Constants.EVENT_MESSAGE_DELTA}\ndata: {json.dumps({'type': Constants.EVENT_MESSAGE_DELTA, 'delta': {'stop_reason': final_stop_reason, 'stop_sequence': None}, 'usage': usage_data}, ensure_ascii=False)}\n\n"
    yield f"event: {Constants.EVENT_MESSAGE_STOP}\ndata: {json.dumps({'type': Constants.EVENT_MESSAGE_STOP}, ensure_ascii=False)}\n\n"

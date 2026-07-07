from fastapi import APIRouter, HTTPException, Request, Header, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from datetime import datetime
import json
import uuid
from typing import Optional

from src.core.config import config
from src.core.logging import logger
from src.core.constants import ANTHROPIC_ERROR_TYPE_MAP
from src.core.client import OpenAIClient
from src.models.claude import ClaudeMessagesRequest, ClaudeTokenCountRequest
from src.conversion.request_converter import convert_claude_to_openai
from src.conversion.response_converter import (
    convert_openai_to_claude_response,
    convert_openai_streaming_to_claude_with_cancellation,
)
from src.core.model_manager import model_manager

router = APIRouter()

_tiktoken_enc = None
try:
    from src import _tiktoken_network_blocked
    if _tiktoken_network_blocked:
        import tiktoken
        _tiktoken_enc = tiktoken.get_encoding(config.tokenizer_encoding)
    else:
        logger.critical("tiktoken network block failed — using heuristic token counting")
except Exception as e:
    exc_name = type(e).__name__
    logger.warning(f"tiktoken encoder not available ({exc_name}): {e}")

# Get custom headers from config
custom_headers = config.get_custom_headers()

openai_client = OpenAIClient(
    config.openai_api_key,
    config.openai_base_url,
    config.request_timeout,
    api_version=config.azure_api_version,
    custom_headers=custom_headers,
    max_retries=config.max_retries,
    network_audit_log=config.network_audit_log,
)

async def validate_api_key(x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    """Validate the client's API key from either x-api-key header or Authorization header."""
    client_api_key = None
    
    # Extract API key from headers
    if x_api_key:
        client_api_key = x_api_key
    elif authorization and authorization.startswith("Bearer "):
        client_api_key = authorization.replace("Bearer ", "")
    
    # Skip validation if ANTHROPIC_API_KEY is not set in the environment
    if not config.anthropic_api_key:
        return
        
    # Validate the client API key
    if not client_api_key or not config.validate_client_api_key(client_api_key):
        logger.warning(f"Invalid API key provided by client")
        raise HTTPException(
            status_code=401,
            detail="Invalid API key. Please provide a valid Anthropic API key."
        )

@router.post("/v1/messages")
async def create_message(request: ClaudeMessagesRequest, http_request: Request, _: None = Depends(validate_api_key)):
    try:
        logger.debug(
            f"Processing Claude request: model={request.model}, stream={request.stream}"
        )

        # Generate unique request ID for cancellation tracking
        request_id = str(uuid.uuid4())

        # Convert Claude request to OpenAI format
        openai_request = convert_claude_to_openai(request, model_manager)

        # Check if client disconnected before processing
        if await http_request.is_disconnected():
            raise HTTPException(status_code=499, detail="Client disconnected")

        if request.stream:
            # Streaming response - wrap in error handling
            try:
                openai_stream = openai_client.create_chat_completion_stream(
                    openai_request, request_id
                )
                return StreamingResponse(
                    convert_openai_streaming_to_claude_with_cancellation(
                        openai_stream,
                        request,
                        logger,
                        http_request,
                        openai_client,
                        request_id,
                    ),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                    },
                )
            except HTTPException as e:
                logger.error(f"Streaming setup error: {e.detail}")
                import traceback

                logger.error(traceback.format_exc())
                error_type = ANTHROPIC_ERROR_TYPE_MAP.get(e.status_code, "api_error")
                error_message = openai_client.classify_openai_error(e.detail)
                error_response = {
                    "type": "error",
                    "error": {"type": error_type, "message": error_message},
                }
                return JSONResponse(status_code=e.status_code, content=error_response)
        else:
            # Non-streaming response
            openai_response = await openai_client.create_chat_completion(
                openai_request, request_id
            )
            claude_response = convert_openai_to_claude_response(
                openai_response, request
            )
            return claude_response
    except HTTPException:
        raise
    except Exception as e:
        import traceback

        logger.error(f"Unexpected error processing request: {e}")
        logger.error(traceback.format_exc())
        error_message = openai_client.classify_openai_error(str(e))
        raise HTTPException(status_code=500, detail=error_message)


def _count_tokens_heuristic(request: ClaudeTokenCountRequest) -> int:
    total_chars = 0
    if request.system:
        if isinstance(request.system, str):
            total_chars += len(request.system)
        elif isinstance(request.system, list):
            for block in request.system:
                if hasattr(block, "text"):
                    total_chars += len(block.text)
    for msg in request.messages:
        if msg.content is None:
            continue
        elif isinstance(msg.content, str):
            total_chars += len(msg.content)
        elif isinstance(msg.content, list):
            for block in msg.content:
                if hasattr(block, "type") and block.type == "thinking":
                    if hasattr(block, "thinking") and block.thinking:
                        total_chars += len(block.thinking)
                elif hasattr(block, "type") and block.type == "image":
                    total_chars += 85 * 4
                elif hasattr(block, "type") and block.type == "tool_use":
                    total_chars += len(json.dumps(block.input, ensure_ascii=False))
                elif hasattr(block, "type") and block.type == "tool_result":
                    content = block.content if isinstance(block.content, str) else json.dumps(block.content, ensure_ascii=False)
                    total_chars += len(content)
                elif hasattr(block, "text") and block.text is not None:
                    total_chars += len(block.text)
    if request.tools:
        for tool in request.tools:
            total_chars += len(json.dumps(
                {"name": tool.name, "description": tool.description or "", "parameters": tool.input_schema},
                ensure_ascii=False,
            ))
    return max(1, total_chars // 4)


def _count_tokens_tiktoken(request: ClaudeTokenCountRequest) -> int:
    if _tiktoken_enc is None:
        raise RuntimeError("tiktoken not cached")
    enc = _tiktoken_enc
    total = 0

    if request.system:
        if isinstance(request.system, str):
            total += len(enc.encode(request.system))
        elif isinstance(request.system, list):
            for block in request.system:
                if hasattr(block, "text"):
                    total += len(enc.encode(block.text))
        total += config.token_overhead_per_message

    for msg in request.messages:
        total += config.token_overhead_per_message
        if msg.content is None:
            continue
        elif isinstance(msg.content, str):
            total += len(enc.encode(msg.content))
        elif isinstance(msg.content, list):
            for block in msg.content:
                if hasattr(block, "type") and block.type == "thinking":
                    if hasattr(block, "thinking") and block.thinking:
                        total += len(enc.encode(block.thinking))
                elif hasattr(block, "type") and block.type == "image":
                    total += 85
                    logger.debug("Image block counted as fixed 85-token estimate")
                elif hasattr(block, "type") and block.type == "tool_use":
                    total += len(enc.encode(json.dumps(block.input, ensure_ascii=False)))
                elif hasattr(block, "type") and block.type == "tool_result":
                    content = block.content if isinstance(block.content, str) else json.dumps(block.content, ensure_ascii=False)
                    total += len(enc.encode(content))
                elif hasattr(block, "text") and block.text is not None:
                    total += len(enc.encode(block.text))

    if request.tools:
        for tool in request.tools:
            tool_str = json.dumps(
                {"name": tool.name, "description": tool.description or "", "parameters": tool.input_schema},
                ensure_ascii=False,
            )
            total += len(enc.encode(tool_str))
            total += config.token_overhead_per_tool

    total += config.token_overhead_priming
    return max(1, total)


@router.post("/v1/messages/count_tokens")
async def count_tokens(request: ClaudeTokenCountRequest, _: None = Depends(validate_api_key)):
    try:
        try:
            estimated_tokens = _count_tokens_tiktoken(request)
        except Exception as e:
            logger.warning(f"tiktoken unavailable, falling back to heuristic: {e}")
            estimated_tokens = _count_tokens_heuristic(request)

        return {"input_tokens": estimated_tokens}

    except Exception as e:
        logger.error(f"Error counting tokens: {e}")
        raise HTTPException(status_code=500, detail="Token counting failed")


@router.get("/v1/models")
async def list_models(_: None = Depends(validate_api_key)):
    models = []
    seen = set()
    for model_id in [config.big_model, config.middle_model, config.small_model]:
        if model_id not in seen:
            seen.add(model_id)
            models.append({
                "id": model_id,
                "object": "model",
                "created": 0,
                "owned_by": "proxy",
            })
    return {"object": "list", "data": models}


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    from src import _tiktoken_downloads_blocked
    # Self-test at startup increments counter to 1. Anything above 1
    # means tiktoken attempted a real download during operation.
    runtime_blocked = max(0, _tiktoken_downloads_blocked - 1)
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "tiktoken_available": _tiktoken_enc is not None,
        "tiktoken_downloads_blocked": runtime_blocked,
    }


@router.api_route("/", methods=["GET", "HEAD"])
async def root():
    """Root endpoint"""
    return {
        "message": "Claude-to-OpenAI API Proxy v1.0.0",
        "status": "running",
        "endpoints": {
            "messages": "/v1/messages",
            "count_tokens": "/v1/messages/count_tokens",
            "models": "/v1/models",
            "health": "/health",
        },
    }

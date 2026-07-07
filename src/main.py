import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse
from src.api.endpoints import router as api_router
import uvicorn
import sys
from src.core.config import config
from src.core.constants import ANTHROPIC_ERROR_TYPE_MAP

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Claude-to-OpenAI API Proxy",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    error_type = ANTHROPIC_ERROR_TYPE_MAP.get(exc.status_code, "api_error")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "type": "error",
            "error": {"type": error_type, "message": exc.detail},
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    message = errors[0]["msg"] if errors else "Invalid request"
    return JSONResponse(
        status_code=400,
        content={
            "type": "error",
            "error": {"type": "invalid_request_error", "message": message},
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "type": "error",
            "error": {"type": "api_error", "message": "Internal server error"},
        },
    )


app.include_router(api_router)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print("Claude-to-OpenAI API Proxy v1.0.0")
        print("")
        print("Usage: python src/main.py")
        print("")
        print("Required environment variables:")
        print("  OPENAI_API_KEY - Your OpenAI API key")
        print("")
        print("Optional environment variables:")
        print("  ANTHROPIC_API_KEY - Expected Anthropic API key for client validation")
        print("                      If set, clients must provide this exact API key")
        print(
            f"  OPENAI_BASE_URL - OpenAI API base URL (default: https://api.openai.com/v1)"
        )
        print(f"  BIG_MODEL - Model for opus requests (default: gpt-4o)")
        print(f"  MIDDLE_MODEL - Model for sonnet requests (default: BIG_MODEL value)")
        print(f"  SMALL_MODEL - Model for haiku requests (default: gpt-4o-mini)")
        print(f"  MODEL_PREFIX - Auto-prefix for bare deepseek-* names (default: accounts/fireworks/models/)")
        print(f"  HOST - Server host (default: 127.0.0.1)")
        print(f"  PORT - Server port (default: 3000)")
        print(f"  LOG_LEVEL - Logging level (default: INFO)")
        print(f"  MAX_TOKENS_LIMIT - Token limit (default: 4096)")
        print(f"  MIN_TOKENS_LIMIT - Minimum token limit (default: 100)")
        print(f"  REQUEST_TIMEOUT - Request timeout in seconds (default: 90)")
        print(f"  MAX_RETRIES - Upstream retry count with backoff (default: 10)")
        print(f"  NETWORK_AUDIT_LOG - File path for network audit log (default: disabled)")
        print(f"  TOKENIZER_ENCODING - tiktoken encoding (default: cl100k_base)")
        print(f"  TOKEN_OVERHEAD_PER_MESSAGE - Per-message token overhead (default: 4)")
        print(f"  TOKEN_OVERHEAD_PER_TOOL - Per-tool token overhead (default: 7)")
        print(f"  TOKEN_OVERHEAD_PRIMING - Reply priming overhead (default: 3)")
        print("")
        print("Model mapping:")
        print(f"  Claude haiku models -> {config.small_model}")
        print(f"  Claude sonnet models -> {config.middle_model}")
        print(f"  Claude opus models -> {config.big_model}")
        sys.exit(0)

    # Configuration summary — no sensitive values
    print("Claude-to-OpenAI API Proxy v1.0.0")
    print(f"  Server: {config.host}:{config.port}")
    print(f"  Client auth: {'enabled' if config.anthropic_api_key else 'disabled'}")
    if config.network_audit_log:
        print(f"  Network audit log: {config.network_audit_log}")
    print("")

    # Parse log level - extract just the first word to handle comments
    log_level = config.log_level.split()[0].lower()
    
    # Validate and set default if invalid
    valid_levels = ['debug', 'info', 'warning', 'error', 'critical']
    if log_level not in valid_levels:
        log_level = 'info'

    # Start server
    uvicorn.run(
        "src.main:app",
        host=config.host,
        port=config.port,
        log_level=log_level,
        reload=False,
    )


if __name__ == "__main__":
    main()

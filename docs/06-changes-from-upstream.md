# Changes from Upstream

Base: `github.com/fuergaosi233/claude-code-proxy` commit `7ea4177a`

## Code Changes

### `src/core/model_manager.py` — Fireworks model passthrough

Added `accounts/` prefix check at the top of `map_claude_model_to_openai()`. Model names like `accounts/fireworks/models/deepseek-v4-flash` now pass through as-is instead of falling through to the `big_model` default.

Without this fix, `SMALL_MODEL` was dead — every request silently routed to `BIG_MODEL`.

### `src/core/client.py` — Fingerprint stripping

Refactored. Added:
- `_strip_fingerprints()` httpx event hook that removes all `X-Stainless-*` headers AND the `User-Agent` header at the transport layer
- `httpx.AsyncClient` with the event hook wired in, passed to `AsyncOpenAI` via `http_client=`
- Removed custom `User-Agent: claude-proxy/1.0.0` from default headers

### `src/core/config.py` — API key validation + default bind

- Removed `startswith('sk-')` check from `validate_api_key()`. Fireworks keys use `fw_` prefix.
- Changed `HOST` default from `0.0.0.0` to `127.0.0.1` — loopback-only even without `.env`.

### `src/main.py` — Disabled auto-docs

Added `docs_url=None, redoc_url=None, openapi_url=None` to the `FastAPI()` constructor. Prevents `/docs`, `/redoc`, and `/openapi.json` from exposing the full API schema.

### `src/models/claude.py` — Thinking support

- `ClaudeThinkingConfig` now accepts `type` and `budget_tokens` (matching Anthropic format)
- Added `ClaudeContentBlockThinking` for thinking content blocks in messages

### `src/conversion/request_converter.py` — Thinking passthrough

When `thinking.type == "enabled"`, the proxy passes the `thinking` parameter directly to Fireworks (which accepts it natively on the OpenAI endpoint).

### `src/conversion/response_converter.py` — Reasoning content handling

- Non-streaming: `reasoning_content` from Fireworks → Anthropic `thinking` content block
- Streaming: `reasoning_content` deltas → `thinking_delta` SSE events, with proper block index management (thinking block first, then text block)

### `src/api/endpoints.py` — Endpoint hardening

- `GET /health`: Stripped `openai_api_configured`, `api_key_valid`, `client_api_key_validation` from response
- `GET /test-connection`: Removed entirely (burned tokens unauthenticated, leaked config)
- `GET /`: Stripped `openai_base_url`, model names, API key status from response
- Streaming responses: Removed `Access-Control-Allow-Origin: *` and `Access-Control-Allow-Headers: *`

### `src/conversion/request_converter.py` — Dead import

Deleted `from venv import logger` on line 3 (dead code, overwritten on line 9).

## Dependency Changes

### `requirements.txt` + `pyproject.toml`

- `fastapi[standard]` → `fastapi` (drops dnspython, email-validator, jinja2, and 9 other packages)
- `uvicorn` → `uvicorn[standard]` (keeps uvloop + httptools for performance)

### `uv.lock`

Regenerated to reflect new dependency tree. 12 packages removed:
`dnspython`, `email-validator`, `jinja2`, `markupsafe`, `fastapi-cli`, `rich`, `rich-toolkit`, `typer`, `shellingham`, `mdurl`, `markdown-it-py`, `python-multipart`

## New Files

| File | Purpose |
|---|---|
| `.env` | Fireworks configuration with privacy-hardened defaults |
| `docs/` | This documentation directory |

## External Changes

| File | Change |
|---|---|
| `~/.bashrc` | Replaced Bifrost aliases with `proxy-start` and `claude-fireworks` |

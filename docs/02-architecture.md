# Architecture

## What This Proxy Does

Translates Anthropic Messages API requests into OpenAI Chat Completions API format and back. This allows Claude Code (which speaks Anthropic format) to use any OpenAI-compatible backend (Fireworks AI, OpenRouter, Ollama, vLLM, etc.).

```
Claude Code                    Proxy (localhost:3000)              Fireworks AI
─────────                      ─────────────────────               ────────────
POST /v1/messages        →     Receive Anthropic request
(Anthropic format)              Convert to OpenAI format      →    POST /v1/chat/completions
                                                                   (OpenAI format)
                          ←     Convert response back          ←   Response
Claude response                 to Anthropic format                 (OpenAI format)
(Anthropic format)
```

## Request Flow

1. Claude Code sends a POST to `http://localhost:3000/v1/messages` with Anthropic-format JSON
2. `endpoints.py` validates the client API key (if `ANTHROPIC_API_KEY` is set)
3. `request_converter.py` transforms:
   - Anthropic `system` blocks → OpenAI `system` message
   - Anthropic `user`/`assistant` messages → OpenAI messages
   - Anthropic `tool_use`/`tool_result` → OpenAI `function`/`tool` calls
   - Anthropic tool definitions → OpenAI function definitions
4. `model_manager.py` maps the model name:
   - `accounts/...` paths → pass through as-is (Fireworks provider paths)
   - `gpt-*`, `o1-*`, `ep-*`, `doubao-*`, `deepseek-*` → pass through as-is
   - Names containing `haiku` → `SMALL_MODEL`
   - Names containing `sonnet` → `MIDDLE_MODEL`
   - Names containing `opus` → `BIG_MODEL`
   - Everything else → `BIG_MODEL`
5. `client.py` sends the OpenAI-format request to `OPENAI_BASE_URL` via the `openai` Python SDK
   - The httpx event hook strips `X-Stainless-*` headers before the request leaves the process
   - Custom headers from `CUSTOM_HEADER_*` env vars are included
6. For streaming: `response_converter.py` converts each OpenAI SSE chunk back to Anthropic SSE format
7. For non-streaming: `response_converter.py` converts the full OpenAI response to Anthropic format

## File Map

```
src/
├── main.py                        # FastAPI app, uvicorn startup
├── __init__.py                    # Package init
├── api/
│   └── endpoints.py               # Route handlers: /v1/messages, /health, /
├── core/
│   ├── client.py                  # OpenAI SDK wrapper + Stainless header stripping
│   ├── config.py                  # Environment variable loading + CUSTOM_HEADER_* parsing
│   ├── constants.py               # String constants (role names, content types)
│   ├── logging.py                 # Logger setup
│   └── model_manager.py           # Model name mapping (Claude → OpenAI/Fireworks)
├── conversion/
│   ├── request_converter.py       # Anthropic request → OpenAI request
│   └── response_converter.py      # OpenAI response → Anthropic response
└── models/
    ├── claude.py                  # Pydantic models for Anthropic request format
    └── openai.py                  # (empty — uses dict-based OpenAI format)
```

## Endpoints

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/v1/messages` | POST | Yes (if `ANTHROPIC_API_KEY` set) | Main translation endpoint |
| `/v1/messages/count_tokens` | POST | Yes | Token count estimation (tiktoken with heuristic fallback) |
| `/v1/models` | GET | Yes | Lists configured models (deduplicated) |
| `/health` | GET | No | Returns `status`, `timestamp`, `tiktoken_available`, `tiktoken_downloads_blocked` |
| `/` | GET | No | Returns version and endpoint list only |

## Streaming

The proxy supports full SSE streaming. The flow:

1. Claude Code sends `"stream": true` in the request
2. Proxy converts to OpenAI format with `stream: true` and `stream_options.include_usage: true`
3. Each OpenAI chunk is converted to Anthropic SSE event format in real-time
4. Cancellation is supported — if Claude Code disconnects, the proxy cancels the upstream request

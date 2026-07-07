# Claude Code Proxy — Privacy Hardened

A fork of [`fuergaosi233/claude-code-proxy`](https://github.com/fuergaosi233/claude-code-proxy) with privacy and security hardening applied. Enables Claude Code to work with any OpenAI-compatible backend (Fireworks AI, OpenRouter, Ollama, vLLM) while ensuring the proxy itself leaks nothing about your environment to the upstream provider.

## What This Fork Changes

The upstream proxy works but makes no effort to control what metadata leaves your machine. This fork fixes that:

### Privacy

- **SDK fingerprint stripping** — The `openai` Python SDK injects `X-Stainless-*` headers on every request, revealing your OS, CPU architecture, Python version, and SDK version to the backend. An httpx transport-layer hook strips all `X-Stainless-*` and `User-Agent` headers before requests leave the process.
- **Loopback-only by default** — Bind address defaults to `127.0.0.1` in both code and `.env`, not `0.0.0.0`. The proxy is not exposed to your LAN unless you explicitly opt in.
- **tiktoken network block** — tiktoken downloads encoding data from a Microsoft CDN on first use. A monkeypatch on `tiktoken.load.read_file` blocks all runtime HTTP downloads, with a self-test at import time, a defense-in-depth fallback, and a heuristic estimator as the final safety net. Encoding data is pre-cached locally at setup time.
- **No telemetry, no phone-home** — Zero telemetry frameworks, no background threads, no runtime-initiated network calls. Single outbound destination: `OPENAI_BASE_URL`, only in response to incoming requests.
- **Opt-in network audit logging** — Set `NETWORK_AUDIT_LOG` to a file path and every outbound request/response is logged (JSONL) with sensitive headers redacted. Disabled by default.

### Security

- **Wildcard CORS removed** — Upstream had `Access-Control-Allow-Origin: *` on streaming responses. Combined with a `0.0.0.0` bind, any website could make cross-origin requests through the proxy.
- **Info endpoints stripped** — `GET /` no longer leaks model names, base URL, or API key status. `GET /health` returns only operational status. `GET /test-connection` (unauthenticated, burned tokens) removed entirely.
- **FastAPI auto-docs disabled** — `/docs`, `/redoc`, and `/openapi.json` no longer expose the full API schema.
- **Dependency tree trimmed** — Replaced `fastapi[standard]` with plain `fastapi` + `uvicorn[standard]`, removing 12 packages including `dnspython` and `email-validator`.

### Functionality

- **Fireworks model passthrough** — Model names starting with `accounts/` pass through as-is instead of silently falling to the default. Without this, `SMALL_MODEL` was dead — every request routed to `BIG_MODEL`.
- **Three-tier model routing** — `opus` → `BIG_MODEL`, `sonnet` → `MIDDLE_MODEL`, `haiku` → `SMALL_MODEL`, with `MIDDLE_MODEL` defaulting to `BIG_MODEL` when unset. Bare `deepseek-*` names auto-prefix with `MODEL_PREFIX`.
- **Extended thinking** — Passes `thinking` config to Fireworks natively and converts `reasoning_content` back to Anthropic `thinking` content blocks in both streaming and non-streaming responses.
- **tiktoken token counting** — `/v1/messages/count_tokens` uses tiktoken with configurable per-message, per-tool, and priming overheads. Falls back to a character-count heuristic if tiktoken is unavailable.
- **Anthropic error envelopes** — All error paths return `{"type": "error", "error": {"type": "...", "message": "..."}}` matching the Anthropic API format Claude Code expects.
- **Lifecycle scripts** — `start.sh`, `stop.sh`, `restart.sh`, `logs.sh` for background operation with PID tracking and lock files.

See [docs/06-changes-from-upstream.md](docs/06-changes-from-upstream.md) for the complete diff from the base repo.

## Quick Start

```bash
git clone https://github.com/j57n-3co-x-5735/claude-code-proxy-PRIVACY-HARDENED
cd claude-code-proxy-PRIVACY-HARDENED
uv sync --locked
./scripts/update-tokenizer.sh   # pre-cache tiktoken data (required for token counting)
cp .env.example .env             # edit with your API key and models
./scripts/start.sh
```

Then in another terminal:

```bash
ANTHROPIC_BASE_URL=http://localhost:3000 \
  ANTHROPIC_AUTH_TOKEN=no-key-needed \
  ANTHROPIC_CUSTOM_MODEL_OPTION=accounts/fireworks/models/qwen3p7-plus \
  ANTHROPIC_SMALL_FAST_MODEL=accounts/fireworks/models/minimax-m3 \
  claude --model accounts/fireworks/models/qwen3p7-plus
```

See [docs/00-quickstart.md](docs/00-quickstart.md) for the full walkthrough including shell aliases.

## Testing

```bash
uv run pytest tests/ --ignore=tests/test_main.py -v
```

84 unit tests covering streaming tool deltas, error envelopes, token counting, model routing, and request conversion.

## Documentation

| Doc | Contents |
|-----|----------|
| [Quick Start](docs/00-quickstart.md) | 5-minute setup guide |
| [Setup](docs/01-setup.md) | Full configuration reference, all env vars, LAN access, troubleshooting |
| [Architecture](docs/02-architecture.md) | Request flow, file map, endpoints |
| [Privacy Hardening](docs/03-privacy-hardening.md) | Every finding, its mitigation, and how to verify it |
| [Fireworks Caching](docs/04-fireworks-caching.md) | Session affinity and KV cache |
| [Known Limitations](docs/05-known-limitations.md) | What isn't supported |
| [Changes from Upstream](docs/06-changes-from-upstream.md) | Complete diff from base repo |
| [Scripts](docs/07-scripts.md) | start/stop/restart/logs reference |

## License

MIT License

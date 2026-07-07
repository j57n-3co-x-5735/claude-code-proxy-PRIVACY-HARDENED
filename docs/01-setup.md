# Setup Guide

For a faster path, see [Quick Start](00-quickstart.md).

## Prerequisites

- Python >= 3.9
- [uv](https://docs.astral.sh/uv/) package manager

## Installation

```bash
git clone https://github.com/j57n-3co-x-5735/claude-code-proxy-PRIVACY-HARDENED
cd claude-code-proxy-PRIVACY-HARDENED
uv sync --locked
./scripts/update-tokenizer.sh
```

This installs all dependencies from the pinned lockfile (`uv.lock`) with hash verification. Do not use `pip install -r requirements.txt` — it bypasses the lockfile and uses floor-pinned versions. The tokenizer script downloads tiktoken's encoding data into a persistent local cache so the proxy never contacts the CDN at runtime.

## Configuration

All config is in `.env` at the project root:

```bash
cp .env.example .env
# Edit .env with your provider's API key and models
```

### Environment Variable Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes | — | API key for the upstream provider (Fireworks: `fw_...`) |
| `OPENAI_BASE_URL` | No | `https://api.openai.com/v1` | Upstream OpenAI-compatible endpoint |
| `BIG_MODEL` | No | `gpt-4o` | Model for opus-tier / default requests |
| `MIDDLE_MODEL` | No | Same as BIG_MODEL | Model for sonnet-tier requests |
| `SMALL_MODEL` | No | `gpt-4o-mini` | Model for haiku-tier / lightweight requests |
| `MODEL_PREFIX` | No | `accounts/fireworks/models/` | Auto-prefix for bare `deepseek-*` model names. Set `""` to disable. |
| `HOST` | No | `127.0.0.1` | Bind address. Use `0.0.0.0` for LAN access. |
| `PORT` | No | `3000` | Listening port |
| `MAX_TOKENS_LIMIT` | No | `4096` | Max tokens cap per request |
| `MIN_TOKENS_LIMIT` | No | `100` | Min tokens floor per request. Note: `.env.example` sets this to `4096` — see below. |
| `REQUEST_TIMEOUT` | No | `90` | Upstream request timeout in seconds |
| `MAX_RETRIES` | No | `10` | Upstream retry count with exponential backoff (0.5s → 8s cap, ~56s total). Respects `Retry-After` headers. Note: `.env.example` sets this to `2` — see below. |
| `ANTHROPIC_API_KEY` | No | — | If set, clients must send this value in `x-api-key` header |
| `NETWORK_AUDIT_LOG` | No | — | File path for network request/response audit log (JSONL). Disabled when unset. |
| `TIKTOKEN_CACHE_DIR` | No | `.tiktoken-cache/` (project root) | Persistent cache for tiktoken encoding data. Populated by `scripts/update-tokenizer.sh`. |
| `TOKENIZER_ENCODING` | No | `cl100k_base` | tiktoken encoding for token counting |
| `TOKEN_OVERHEAD_PER_MESSAGE` | No | `4` | Token overhead per message (tunable for non-OpenAI models) |
| `TOKEN_OVERHEAD_PER_TOOL` | No | `7` | Token overhead per tool definition |
| `TOKEN_OVERHEAD_PRIMING` | No | `3` | Token overhead for reply priming |
| `CUSTOM_HEADER_*` | No | — | Inject custom headers into upstream requests (see below) |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity: DEBUG, INFO, WARNING, ERROR |
| `AZURE_API_VERSION` | No | — | If set, uses Azure OpenAI client instead of standard |

### Custom Headers

Any env var starting with `CUSTOM_HEADER_` is injected into every upstream request. The prefix is stripped and underscores become hyphens:

```
CUSTOM_HEADER_X_SESSION_AFFINITY=session-primary
```

Sends `X-SESSION-AFFINITY: session-primary` to Fireworks on every request (the code converts underscores to hyphens but preserves the uppercase from the env var name). HTTP headers are case-insensitive per RFC 7230, so this works regardless of casing. This enables sticky session routing for prompt caching.

## Running

### Background (recommended)

```bash
./scripts/start.sh          # start
./scripts/stop.sh           # stop
./scripts/restart.sh        # restart
./scripts/logs.sh           # follow logs
```

See [Scripts](07-scripts.md) for details.

### Foreground

```bash
uv run start_proxy.py
```

### With Claude Code

Terminal 1:
```bash
./scripts/start.sh
```

Terminal 2:
```bash
claude-fireworks    # if you set up the alias (see below)
```

### Shell Aliases and Claude Code Environment Variables

See [Quick Start](00-quickstart.md#optional-shell-aliases) for shell alias setup and the Claude Code environment variables table.

### `.env.example` vs. Code Defaults

The defaults column in the table above reflects the code defaults in `config.py` — what you get if a variable is unset. The `.env.example` file overrides some of these with different values:

| Variable | Code default | `.env.example` value |
|---|---|---|
| `MIN_TOKENS_LIMIT` | `100` | `4096` |
| `MAX_RETRIES` | `10` | `2` |

If you copy `.env.example` to `.env` without editing, you get the `.env.example` values. The code defaults only apply when the variable is completely absent from `.env`.

## LAN Access

To expose the proxy to other machines on your LAN:

1. Change `HOST=0.0.0.0` in `.env`
2. Set `ANTHROPIC_API_KEY=some-shared-secret` in `.env` to enable client auth
3. Clients connect to `http://<your-lan-ip>:3000` and must send the secret in the `x-api-key` header

Only devices that speak Anthropic Messages API format benefit from the proxy. Devices that speak OpenAI format should talk to Fireworks directly.

## Troubleshooting

### Proxy starts but token counting returns rough estimates

The tiktoken cache is empty. Run `./scripts/update-tokenizer.sh` and restart the proxy. Verify with:

```bash
curl http://localhost:3000/health | python3 -c "import sys,json; print(json.load(sys.stdin)['tiktoken_available'])"
```

If this prints `False`, the cache wasn't populated or the encoding doesn't match `TOKENIZER_ENCODING` in your `.env`. Delete `.tiktoken-cache/` and re-run the update script.

### `OPENAI_API_KEY not found` on startup

The proxy requires `OPENAI_API_KEY` in the environment. This is the key for your upstream provider (Fireworks: `fw_...`, OpenRouter: `sk-or-...`, Ollama: any non-empty string). Set it in `.env` or export it in your shell.

### `Model not found` errors from upstream

The model name in your request must resolve to something the upstream provider accepts. Check:

1. Your `BIG_MODEL` / `MIDDLE_MODEL` / `SMALL_MODEL` values in `.env` match models available on your provider
2. If using `ANTHROPIC_CUSTOM_MODEL_OPTION` with Claude Code, the model name matches what the proxy maps to — use `curl http://localhost:3000/v1/models` to see configured models
3. For Fireworks, model names must include the full path (e.g., `accounts/fireworks/models/deepseek-v4-pro`). Bare `deepseek-*` names are auto-prefixed with `MODEL_PREFIX`.

### Frequent 429 (rate limit) errors

The proxy retries with exponential backoff (0.5s → 8s cap). Increase `MAX_RETRIES` in `.env` for heavy workloads. The default retry budget is ~56 seconds; multi-agent workflows with parallel tool calls can exhaust rate limits faster than single-turn usage.

### Proxy unreachable from another machine

The proxy binds to `127.0.0.1` (loopback) by default — only the local machine can connect. For LAN access, set `HOST=0.0.0.0` in `.env` and set `ANTHROPIC_API_KEY` to a shared secret (see [LAN Access](#lan-access) above).

### Request hangs then times out

The default `REQUEST_TIMEOUT` is 90 seconds. Some models (large reasoning models with extended thinking) can take longer. Increase `REQUEST_TIMEOUT` in `.env`. Also check that your upstream provider is reachable from the proxy host.

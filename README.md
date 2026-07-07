# Claude Code Proxy

A privacy-hardened proxy that enables Claude Code to work with OpenAI-compatible API providers. Translates Anthropic Messages API requests to OpenAI Chat Completions format and back.

## Features

- Full `/v1/messages` endpoint with streaming, tool use, and extended thinking
- Privacy hardened: strips SDK fingerprinting headers, no telemetry, loopback-only by default
- Network audit logging for empirical verification of outbound traffic
- Three-tier model routing: opus → `BIG_MODEL`, sonnet → `MIDDLE_MODEL`, haiku → `SMALL_MODEL`
- tiktoken-based token counting with configurable overheads
- Anthropic-format error envelopes on all error paths

## Quick Start

```bash
git clone https://github.com/j57n-3co-x-5735/claude-code-proxy
cd claude-code-proxy
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

## Model Mapping

| Claude Request | Mapped To | Environment Variable |
|---|---|---|
| Models with "haiku" | `SMALL_MODEL` | Default: `gpt-4o-mini` |
| Models with "sonnet" | `MIDDLE_MODEL` | Default: same as `BIG_MODEL` |
| Models with "opus" | `BIG_MODEL` | Default: `gpt-4o` |
| Bare `deepseek-*` names | Auto-prefixed with `MODEL_PREFIX` | Default: `accounts/fireworks/models/` |

## Testing

```bash
uv run pytest tests/ --ignore=tests/test_main.py -v
```

84 unit tests covering streaming tool deltas, error envelopes, token counting, model routing, and request conversion.

## Documentation

| Doc | Contents |
|-----|----------|
| [Quick Start](docs/00-quickstart.md) | 5-minute setup guide |
| [Setup](docs/01-setup.md) | Full configuration reference, all env vars, LAN access |
| [Architecture](docs/02-architecture.md) | Request flow, file map, endpoints |
| [Privacy Hardening](docs/03-privacy-hardening.md) | Privacy/security fixes and how to verify them |
| [Fireworks Caching](docs/04-fireworks-caching.md) | Session affinity and KV cache |
| [Known Limitations](docs/05-known-limitations.md) | What isn't supported |
| [Changes from Upstream](docs/06-changes-from-upstream.md) | Diff from base repo |
| [Scripts](docs/07-scripts.md) | start/stop/restart/logs reference |

## License

MIT License

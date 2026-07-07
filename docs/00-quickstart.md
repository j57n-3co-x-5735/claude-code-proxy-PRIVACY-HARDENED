# Quick Start

Get Claude Code running through the proxy in under 5 minutes.

## 1. Install

```bash
git clone https://github.com/j57n-3co-x-5735/claude-code-proxy-PRIVACY-HARDENED
cd claude-code-proxy-PRIVACY-HARDENED
uv sync --locked
./scripts/update-tokenizer.sh
```

## 2. Configure

```bash
cp .env.example .env
```

Edit `.env` with your provider's API key and models:

```
OPENAI_API_KEY=fw_your_key_here
OPENAI_BASE_URL=https://api.fireworks.ai/inference/v1
BIG_MODEL=accounts/fireworks/models/qwen3p7-plus
MIDDLE_MODEL=accounts/fireworks/models/qwen3p7-plus
SMALL_MODEL=accounts/fireworks/models/minimax-m3
```

## 3. Start the proxy

```bash
./scripts/start.sh
```

## 4. Launch Claude Code through the proxy

```bash
ANTHROPIC_BASE_URL=http://localhost:3000 \
  ANTHROPIC_AUTH_TOKEN=no-key-needed \
  ANTHROPIC_CUSTOM_MODEL_OPTION=accounts/fireworks/models/qwen3p7-plus \
  ANTHROPIC_CUSTOM_MODEL_OPTION_NAME="Qwen3p7 Plus (Fireworks)" \
  ANTHROPIC_SMALL_FAST_MODEL=accounts/fireworks/models/minimax-m3 \
  claude --model accounts/fireworks/models/qwen3p7-plus
```

That's it. Claude Code is now talking to your configured backend through the proxy.

## Optional: Shell aliases

Add these to your `~/.bashrc` or `~/.zshrc` so you don't have to type the above every time:

```bash
# Start the proxy (background, with logging)
alias proxy-start='/path/to/claude-code-proxy/scripts/start.sh'
alias proxy-stop='/path/to/claude-code-proxy/scripts/stop.sh'

# Launch Claude Code through the proxy
alias claude-fireworks='ANTHROPIC_BASE_URL=http://localhost:3000 \
  ANTHROPIC_AUTH_TOKEN=no-key-needed \
  ANTHROPIC_CUSTOM_MODEL_OPTION=accounts/fireworks/models/qwen3p7-plus \
  ANTHROPIC_CUSTOM_MODEL_OPTION_NAME="Qwen3p7 Plus (Fireworks)" \
  ANTHROPIC_SMALL_FAST_MODEL=accounts/fireworks/models/minimax-m3 \
  claude --model accounts/fireworks/models/qwen3p7-plus'
```

Replace `/path/to/claude-code-proxy` with your actual clone path. Update the model names to match your `.env` if you change them.

Then: `proxy-start` in one terminal, `claude-fireworks` in another.

## Claude Code environment variables

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_BASE_URL` | Points Claude Code at the proxy instead of Anthropic's API |
| `ANTHROPIC_AUTH_TOKEN` | Placeholder token (client auth is disabled by default) |
| `ANTHROPIC_CUSTOM_MODEL_OPTION` | The model name sent in requests — must match your `BIG_MODEL` |
| `ANTHROPIC_CUSTOM_MODEL_OPTION_NAME` | Display name shown in Claude Code's `/model` picker |
| `ANTHROPIC_SMALL_FAST_MODEL` | Model for background/lightweight tasks — should match your `SMALL_MODEL` |

## Verify it works

```bash
# Health check
curl http://localhost:3000/health

# Send a test message
curl http://localhost:3000/v1/messages \
  -H "Content-Type: application/json" \
  -d '{"model": "claude-sonnet-4-20250514", "max_tokens": 50, "messages": [{"role": "user", "content": "Say hello"}]}'
```

## Next steps

- [Setup guide](01-setup.md) — full configuration reference, LAN access, all env vars
- [Architecture](02-architecture.md) — how the proxy translates between API formats
- [Privacy hardening](03-privacy-hardening.md) — what the proxy strips and why
- [Scripts](07-scripts.md) — start/stop/restart/logs reference

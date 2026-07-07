# Known Limitations

## Extended Thinking / Reasoning

Supported. Fireworks accepts the Anthropic `thinking` parameter natively on their OpenAI-compatible endpoint. The proxy passes `thinking: {"type": "enabled", "budget_tokens": N}` through to Fireworks, and converts `reasoning_content` in responses back to Anthropic `thinking` content blocks.

In streaming mode, `reasoning_content` deltas arrive before `content` deltas. The proxy creates a `thinking` content block for reasoning tokens, then a `text` content block for the answer — matching the Anthropic SSE format Claude Code expects.

Limitations:
- `reasoning_history` (multi-turn reasoning preservation) is not yet wired through
- The proxy does not pass `reasoning_content` from previous assistant turns back to Fireworks — multi-turn reasoning context is lost between turns

## Token Counting

The `/v1/messages/count_tokens` endpoint uses tiktoken (`cl100k_base` encoding by default) for token estimation. It counts system messages, user/assistant message content, tool definitions, and tool results. Per-message, per-tool, and priming overhead values are configurable via `TOKEN_OVERHEAD_PER_MESSAGE`, `TOKEN_OVERHEAD_PER_TOOL`, and `TOKEN_OVERHEAD_PRIMING` env vars. Image blocks use a fixed 85-token estimate (low-detail baseline).

The overhead values are derived from OpenAI's GPT-4 tokenizer and may not exactly match DeepSeek V4's framing. If tiktoken is unavailable (import failure, air-gapped environment), the endpoint falls back to a rough 4-characters-per-token heuristic.

## Tool Choice

The `tool_choice` parameter from Anthropic format is mapped:
- `auto` → `auto`
- `any` → `required` (OpenAI's equivalent for "must use a tool")
- `tool` with name → `{"type": "function", "function": {"name": ...}}`

## Service Tier / Metadata

Anthropic's `service_tier`, `context_management`, and `container` parameters are silently dropped — Pydantic v2 ignores unknown fields by default, so these never reach the request converter. The `metadata.user_id` field is mapped to OpenAI's `user` parameter. Other metadata fields are dropped.

## Citations

Citation responses from the upstream model are not converted back to Anthropic format. A debug log is emitted if the upstream response contains `citations` or `annotations` fields. DeepSeek does not produce these.

## Rate Limit Handling

When the upstream provider returns 429 (rate limit), the OpenAI SDK retries with exponential backoff (0.5s, 1s, 2s, 4s, then 8s cap). The default `MAX_RETRIES=10` gives ~56 seconds of persistence before failing. The SDK also respects `Retry-After` headers from the provider (up to 60s per wait).

If all retries are exhausted, the error propagates to Claude Code as a failed request. Claude Code does not automatically retry from its end — the user must re-run the command. For heavy parallel workloads (e.g., multi-agent workflows), increase `MAX_RETRIES` in `.env` if you see frequent 429s.

## Pause/Refusal Stop Reasons

The `pause_turn` and `refusal` stop reasons have no Anthropic equivalent mapping. The `content_filter` finish reason is mapped to `end_turn` with a WARNING log noting safety filtering occurred. Unknown finish reasons are logged at WARNING and default to `end_turn`.

## Docker

The `docker-compose.yml` uses `env_file` to load `.env` and variable substitution for ports (`${PORT:-3000}`). The application's `load_dotenv()` call in `src/__init__.py` is safe alongside Docker's `env_file` — python-dotenv defaults to `override=False`.

## Model Routing

The model mapper passes through any model name starting with `accounts/` as-is. Bare model names starting with `deepseek-` are auto-prefixed with `MODEL_PREFIX` (default: `accounts/fireworks/models/`). Set `MODEL_PREFIX=""` to disable auto-prefixing for non-Fireworks providers. Claude model names (haiku/sonnet/opus) are mapped to the configured `SMALL_MODEL`, `MIDDLE_MODEL`, and `BIG_MODEL` respectively.

## Dependency Updates

All version constraints in `pyproject.toml` use `>=` floor pins. The `uv.lock` file pins exact versions. Always use `uv sync --locked` to install. To update dependencies:

```bash
uv lock          # regenerate lockfile with latest compatible versions
# review changes in uv.lock
uv sync --locked # install the new versions
```

After updating, re-verify that no new telemetry has been introduced (check for new packages, grep for telemetry patterns).

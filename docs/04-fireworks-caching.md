# Fireworks AI Prompt Caching

## How Fireworks Caching Works

Fireworks uses automatic prefix-based caching at the token level — no opt-in, no markers needed.

- Every request's prompt is cached as KV tensors on a GPU replica
- Subsequent requests that share the same token prefix reuse the cached tensors
- Even a single-token difference at any position invalidates the cache from that point onward
- LRU eviction policy — cached prompts persist minutes to hours depending on load
- No documented minimum prefix length (unlike OpenAI's 1,024 token floor)

## Session Affinity

Caching only works within a single replica. On Fireworks' serverless tier with multiple replicas, requests must be routed to the same replica to hit the cache.

The proxy injects an `X-Session-Affinity` header on every upstream request via:

```
CUSTOM_HEADER_X_SESSION_AFFINITY=session-primary
```

This tells Fireworks to route all requests with the same affinity value to the same replica.

### Why not use the Fireworks `user` field?

The `user` field in the request body achieves the same sticky routing, but the proxy doesn't inject body fields — only headers. The `CUSTOM_HEADER_*` mechanism works at the HTTP header level, which is simpler and doesn't require modifying the request body during conversion.

## What Caches Well (Within a Session)

| Component | Cacheable? | Notes |
|---|---|---|
| Tool definitions | Yes | Static across turns, position 0 |
| System prompt (static portion) | Yes | Identity, rules, tool usage (~2,300-3,600 tokens) |
| System prompt (dynamic portion) | Yes | Working dir, platform. Stable within a session. |
| Current date | Yes | Injected in messages array, not system prompt |
| Conversation history | Yes | Only appended — prefix grows but doesn't change |
| Thinking tokens | Yes | When passed back as input, cached normally |

## What Breaks the Cache

| Event | Impact |
|---|---|
| Context compression (~167K tokens) | Claude Code rewrites message history. Cache goes cold. |
| MCP tool changes mid-session | Tool definitions change at position 0, invalidating everything |
| New session / different directory | Different system prompt. Starts cold. |

## Anthropic `cache_control` Markers

Claude Code sends Anthropic's `cache_control` markers in tool definitions and system blocks. These are automatically stripped during the Anthropic→OpenAI format conversion — the OpenAI format has no equivalent field. Fireworks doesn't support them and would reject them if received.

This is harmless — Fireworks caches the entire prefix automatically regardless. No markers needed.

## Pricing

- **Serverless:** 50% discount on cached prompt tokens
- **DeepSeek V4 Pro on Foundry:** ~91% discount on cached tokens
- **Dedicated deployments:** Cached tokens are close to free

## Verifying Cache Hits

On the OpenAI-compatible endpoint, Fireworks reports cached tokens in responses:

```json
"usage": {
  "prompt_tokens_details": {
    "cached_tokens": 1920
  }
}
```

The proxy converts this back to Anthropic format as `cache_read_input_tokens` in both streaming and non-streaming responses. If this shows 0, check the Fireworks billing dashboard for the definitive signal.

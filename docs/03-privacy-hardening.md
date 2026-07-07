# Privacy Hardening

## Summary

The proxy source code is clean — zero telemetry, zero phone-home, zero background network activity. All outbound connections go exclusively to the configured `OPENAI_BASE_URL`. tiktoken encoding data is pre-cached locally (`scripts/update-tokenizer.sh`) and a runtime monkeypatch blocks all HTTP downloads from the library.

Each finding below documents a privacy or security issue in the upstream proxy, the mitigation this fork applies, and how to verify it.

## Finding 1: X-Stainless-* Platform Fingerprinting [HIGH → MITIGATED]

### What

The `openai` Python SDK (v1.90.0, built by Stainless) injects platform-fingerprinting headers on every outbound API request:

| Header | Example Value | What It Reveals |
|---|---|---|
| `X-Stainless-Lang` | `python` | Runtime language |
| `X-Stainless-Package-Version` | `1.90.0` | Exact SDK version |
| `X-Stainless-OS` | `Linux / Debian 12` | OS (enhanced by `distro` package) |
| `X-Stainless-Arch` | `x86_64` | CPU architecture |
| `X-Stainless-Runtime` | `cpython` | Python implementation |
| `X-Stainless-Runtime-Version` | `3.13.5` | Exact Python version |
| `X-Stainless-Async` | `async:asyncio` | Async runtime |

These headers go to `OPENAI_BASE_URL` (Fireworks AI in our case), not to Stainless or OpenAI. But the backend operator receives a precise environment fingerprint with every request.

### Mitigation

An async httpx event hook in `src/core/client.py` strips all `X-Stainless-*` headers and the `User-Agent` header from every outbound request at the transport layer — after all headers are finalized but before the request leaves the process.

```python
async def _strip_fingerprints(request: httpx.Request):
    to_remove = [k for k in request.headers.keys() if k.lower().startswith("x-stainless")]
    for key in to_remove:
        del request.headers[key]
    if "user-agent" in request.headers:
        del request.headers["user-agent"]
```

This is wired into the OpenAI client via:
```python
stripped_http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(timeout, connect=10.0),
    event_hooks={
        "request": [_strip_fingerprints, _log_network_request],
        "response": [_log_network_response],
    },
)
```

The `_log_network_request` and `_log_network_response` hooks are no-ops unless `NETWORK_AUDIT_LOG` is set (see below).

### Why httpx event hook over monkeypatch

The alternative was monkeypatching `openai._base_client.BaseClient.platform_headers`. The event hook is more robust:
- Operates on finalized requests regardless of SDK internals
- Survives SDK version updates that rename/move internal methods
- Catches any future headers the SDK might add
- No dependency on private API surface

The hook also strips the SDK's `User-Agent: AsyncOpenAI/Python {version}` header, which would otherwise identify the SDK and version to the backend.

### Verification

TLS encrypts outbound traffic to Fireworks, so `tcpdump` on port 443 cannot see headers. Use a local echo server instead:

```bash
# Terminal 1 — start a local echo server that prints request headers
python3 -c "
from http.server import HTTPServer, BaseHTTPRequestHandler
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        for k, v in self.headers.items():
            if 'stainless' in k.lower() or 'user-agent' in k.lower():
                print(f'  FOUND: {k}: {v}')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{\"choices\":[{\"message\":{\"content\":\"ok\"},\"finish_reason\":\"stop\"}],\"usage\":{\"prompt_tokens\":1,\"completion_tokens\":1}}')
    def log_message(self, *a): pass
HTTPServer(('127.0.0.1', 9999), H).serve_forever()
"

# Terminal 2 — point proxy at echo server and send a request
OPENAI_BASE_URL=http://127.0.0.1:9999 OPENAI_API_KEY=test python3 -c "
# ... send a test request through the proxy
"
```

If any `FOUND:` lines print, headers are leaking.

## Finding 2: `distro` OS Fingerprinting [LOW → MITIGATED BY F1]

The `distro` package (transitive dependency of the `openai` SDK) reads `/etc/os-release` to detect the Linux distribution. This data fed into the `X-Stainless-OS` header, making the fingerprint more granular ("Debian 12 bookworm" vs "Linux").

Mitigated by Finding 1 — the entire header is stripped.

## Finding 3: `dnspython` in Dependency Tree [LOW → MITIGATED]

### What

`fastapi[standard]` pulled in `email-validator` → `dnspython`, adding DNS resolver capability to the dependency tree. Never called by the proxy, but present.

### Mitigation

Changed `fastapi[standard]` to plain `fastapi` in both `requirements.txt` and `pyproject.toml`. Added `uvicorn[standard]` as a separate dependency to keep performance extras (`uvloop`, `httptools`).

This removed 12 packages from the dependency tree:
`dnspython`, `email-validator`, `jinja2`, `markupsafe`, `fastapi-cli`, `rich`, `rich-toolkit`, `typer`, `shellingham`, `mdurl`, `markdown-it-py`, `python-multipart`

### Verification

```bash
uv pip list | grep -i dns
```

Should return nothing.

## Finding 4: Wildcard CORS [MEDIUM → MITIGATED]

### What

Streaming responses included `Access-Control-Allow-Origin: *` and `Access-Control-Allow-Headers: *`. Combined with a `0.0.0.0` bind, any website a user visited could silently make cross-origin requests through the proxy — a token-theft vector.

### Mitigation

Removed CORS headers entirely from streaming responses in `endpoints.py`. Claude Code is a CLI tool, not a browser — CORS headers served no purpose.

## Finding 5: Default Bind to 0.0.0.0 [MEDIUM → MITIGATED]

### What

The proxy defaulted to listening on all network interfaces, exposing it to the entire LAN.

### Mitigation

`.env` sets `HOST=127.0.0.1` — loopback only. Change to `0.0.0.0` if LAN access is intentionally desired (see setup docs).

## Finding 6: Unauthenticated Info/Action Endpoints [MEDIUM → MITIGATED]

### What

- `GET /` leaked `openai_base_url`, model names, API key status
- `GET /health` leaked `api_key_valid`, `client_api_key_validation`
- `GET /test-connection` fired a real API call to the backend on every unauthenticated GET

### Mitigation

- `/` stripped to return only version and endpoint list
- `/health` stripped to return only `status`, `timestamp`, `tiktoken_available`, and `tiktoken_downloads_blocked` (the tiktoken fields support verifying the network block without exposing configuration)
- `/test-connection` removed entirely

## Finding 7: Dead `venv` Import [INFO → MITIGATED]

### What

`request_converter.py` line 3 had `from venv import logger`, immediately overwritten on line 9. Dead code, not malicious, but sloppy.

### Mitigation

Deleted the line.

## Supply Chain

### Direct Dependencies (6)

| Package | Telemetry? | Notes |
|---|---|---|
| `fastapi` | No | Web framework. No extras. |
| `uvicorn[standard]` | No | ASGI server. `uvloop` + `httptools` for performance. |
| `pydantic` | No | Data validation. |
| `python-dotenv` | No | `.env` file loading. |
| `openai` | X-Stainless headers (stripped) | SDK for upstream calls. |
| `tiktoken` | Network downloads blocked at runtime | Token counting. Encoding data (~1.5MB) is pre-cached locally by `scripts/update-tokenizer.sh`. A monkeypatch on `tiktoken.load.read_file` blocks all HTTP downloads at runtime — if the cache is missing, the proxy falls back to a heuristic instead of downloading. Integrity verified by tiktoken's built-in sha256 check. |

### Key Transitive Dependencies

| Package | Telemetry? | Notes |
|---|---|---|
| `httpx` / `httpcore` | No | HTTP client used by `openai` SDK. No built-in telemetry. |
| `distro` | No | Reads local OS files. No network. Feeds stripped headers. |
| `certifi` | No | TLS certificate bundle. |
| `jiter` | No | Rust JSON parser. No network. |

### Lockfile

All dependencies are pinned with exact versions and hashes in `uv.lock`. Always install with `uv sync --locked`. Never use `uv sync` without `--locked` or `pip install` — these bypass the lockfile and pull latest versions from PyPI.

## Finding 8: HOST Default Was 0.0.0.0 [MEDIUM → MITIGATED]

### What

`config.py` defaulted `HOST` to `0.0.0.0`, exposing the proxy to the entire LAN if `.env` was missing or `HOST` was unset.

### Mitigation

Changed the code default in `config.py` from `0.0.0.0` to `127.0.0.1`. The proxy now binds to loopback even without a `.env` file. Defense-in-depth — not dependent on `.env` as the single layer.

## Finding 9: SDK User-Agent Header [MEDIUM → MITIGATED]

### What

The OpenAI SDK sets `User-Agent: AsyncOpenAI/Python {version}` on every request. The proxy had removed its own custom User-Agent but the SDK's default survived.

### Mitigation

Extended the httpx event hook (renamed `_strip_fingerprints`) to also remove the `User-Agent` header from outbound requests.

## Finding 10: FastAPI Auto-Generated Docs [LOW → MITIGATED]

### What

FastAPI auto-generates `/docs` (Swagger UI), `/redoc`, and `/openapi.json` endpoints by default — exposing the full API schema including all Pydantic models, parameter names, and route map.

### Mitigation

Disabled all three via `FastAPI(docs_url=None, redoc_url=None, openapi_url=None)` in `main.py`.

## tiktoken Network Block Architecture

tiktoken (the token counting library) downloads encoding data from a Microsoft Azure CDN on first use. This is a network call to an external host that is not the configured `OPENAI_BASE_URL` — a privacy violation in a proxy designed to have exactly one outbound destination.

The proxy prevents this with a defense-in-depth strategy implemented in `src/__init__.py`:

### Layer 1: Pre-cached encoding data

`scripts/update-tokenizer.sh` downloads tiktoken's encoding data at setup time and stores it in `.tiktoken-cache/` at the project root. The `TIKTOKEN_CACHE_DIR` environment variable points tiktoken at this cache. When the cache is populated, tiktoken reads from disk and never attempts a download.

### Layer 2: Monkeypatch on `tiktoken.load.read_file`

Even with a populated cache, a mismatch between the configured encoding and the cached data (or a corrupted cache) would cause tiktoken to attempt a download. The proxy replaces `tiktoken.load.read_file` — the function tiktoken calls for all HTTP downloads — with a version that raises `TiktokenDownloadBlocked` for any URL containing `://`.

Local file reads pass through to the original function. Only network downloads are blocked.

### Layer 3: Self-test at import time

Immediately after patching, `__init__.py` calls `read_file("https://verify-patch")`. If this does not raise `RuntimeError`, the patch failed — `__init__.py` sets `_tiktoken_network_blocked = False` and logs a CRITICAL error. Downstream, `endpoints.py` checks this flag: if `False`, it refuses to load tiktoken and falls back to a heuristic character-count estimator. The proxy never calls tiktoken in an unpatched state.

### Layer 4: Defense-in-depth fallback patch

If the primary patch fails entirely (ImportError, AttributeError — tiktoken renamed `read_file`), an `except Exception` block applies a minimal fallback blocker that reads local files with `open()` and raises `RuntimeError` for URLs. This is a last resort that covers tiktoken API changes.

### Observability

The `_tiktoken_downloads_blocked` counter in `__init__.py` increments every time the monkeypatch blocks a download attempt. The self-test at import time triggers one increment (to prove the patch works), so the baseline value is 1. The `/health` endpoint reports `tiktoken_downloads_blocked` as `max(0, counter - 1)` — if this value is above 0 during operation, tiktoken attempted a real download that was blocked.

### Verification

```bash
# Verify the patch is active in a clean subprocess
uv run python -c "
import src  # triggers __init__.py monkeypatch
import tiktoken.load
try:
    tiktoken.load.read_file('https://test')
    print('FAIL: no exception raised')
except RuntimeError as e:
    print('PASS: ' + str(e))
"
```

The test suite includes 12 tests covering the network block: URL blocking, local file passthrough, self-test failure detection, defense-in-depth fallback, subprocess durability, encoding mismatch degradation, health endpoint reporting, cache directory handling, and a socket-level proof that no network contact occurs during token counting.

## What the Proxy Does NOT Do

- No telemetry frameworks (Sentry, Datadog, PostHog, etc.)
- No phone-home beacons or heartbeats
- No runtime-initiated persistent state (no database, no runtime downloads). Tokenizer cache (`.tiktoken-cache/`) is pre-populated by `scripts/update-tokenizer.sh` and read-only at runtime. File writes only when `NETWORK_AUDIT_LOG` is explicitly enabled (opt-in diagnostic tool, off by default).
- No background threads or scheduled tasks
- No dynamic code execution (no eval, exec, subprocess)
- No middleware registered at the app level
- No external log shipping
- Single outbound destination: `OPENAI_BASE_URL` only, and only in response to incoming requests

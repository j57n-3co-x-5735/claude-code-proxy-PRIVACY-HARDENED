# Scripts

Lifecycle scripts for running the proxy. All scripts are in `scripts/` and can be run from anywhere — they resolve paths relative to the project root.

## Prerequisites

- `uv` installed
- `.env` file configured (copy from `.env.example`)

## start.sh

Starts the proxy in the background. Logs to `proxy.log` in the project root.

```bash
./scripts/start.sh
```

- Refuses to start if the proxy is already running
- Prints the PID, log file path, and health check URL
- Pass environment overrides inline: `LOG_LEVEL=DEBUG ./scripts/start.sh`
- Pass `NETWORK_AUDIT_LOG=/tmp/audit.jsonl ./scripts/start.sh` to enable network auditing

## stop.sh

Stops the proxy gracefully.

```bash
./scripts/stop.sh
```

- Sends SIGTERM, waits up to 5 seconds, then SIGKILL if needed
- Cleans up the PID file
- Handles stale PID files and detects orphaned processes

## restart.sh

Stops and starts the proxy in one command.

```bash
./scripts/restart.sh
```

## logs.sh

Follows the proxy log in real time (`tail -f`). Ctrl+C to stop watching.

```bash
./scripts/logs.sh
```

## update-tokenizer.sh

Downloads tiktoken encoding data into `.tiktoken-cache/` so the proxy never contacts the CDN at runtime.

```bash
./scripts/update-tokenizer.sh              # uses TOKENIZER_ENCODING from .env, or cl100k_base
./scripts/update-tokenizer.sh o200k_base   # download a specific encoding
./scripts/update-tokenizer.sh --strict     # fail if any cached file has no reference hash
./scripts/update-tokenizer.sh --verify-only  # check existing cache without downloading
```

Flags:
- `--strict` — exits non-zero if any cached file has no entry in `scripts/tokenizer-hashes.txt`. Use in CI to enforce pinned hashes.
- `--verify-only` — checks integrity of the existing cache without downloading. Exits non-zero if cache is empty, any hash mismatches, or (implicitly strict) any file has no reference hash.

Re-run if:
- Token counts seem inaccurate after changing `TOKENIZER_ENCODING` in `.env`
- You updated tiktoken to a new version (`uv lock && uv sync --locked`)
- The `.tiktoken-cache/` directory was deleted

The script verifies cached files against known-good sha256 hashes in `scripts/tokenizer-hashes.txt`. tiktoken also validates hashes internally on load.

## test-docker.sh

Builds the Docker image and verifies the proxy starts with tiktoken available.

```bash
./scripts/test-docker.sh
```

Checks: image builds, container starts, `/health` returns `tiktoken_available: true`, `/v1/messages/count_tokens` returns a non-zero count. Cleans up the container and image on exit.

## Runtime files

These are created by the scripts and excluded from git:

| File | Purpose |
|------|---------|
| `proxy.log` | Proxy stdout/stderr (appended on each start) |
| `.proxy.pid` | PID of the running proxy process |
| `.tiktoken-cache/` | Persistent tiktoken encoding data (populated by `update-tokenizer.sh`) |

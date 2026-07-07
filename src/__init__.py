"""Claude Code Proxy

A proxy server that enables Claude Code to work with OpenAI-compatible API providers.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_project_root = Path(__file__).resolve().parent.parent

# Treat empty string as unset — tiktoken interprets TIKTOKEN_CACHE_DIR="" as "disable caching"
# which would force a download on every call.
_cache_env = os.environ.get("TIKTOKEN_CACHE_DIR", "")
if not _cache_env:
    os.environ["TIKTOKEN_CACHE_DIR"] = str(_project_root / ".tiktoken-cache")

_cache_dir = Path(os.environ["TIKTOKEN_CACHE_DIR"])
if not _cache_dir.exists() or not any(_cache_dir.iterdir()):
    print(
        f"WARNING: TIKTOKEN_CACHE_DIR ({_cache_dir}) is empty or missing — "
        f"run scripts/update-tokenizer.sh to populate it",
        file=sys.stderr,
    )

# Block tiktoken from making network requests at runtime.
# Encoding data must be pre-cached via scripts/update-tokenizer.sh.
# Verified against tiktoken 0.13.0 — read_file (load.py:8) is called by
# read_file_cached (load.py:49,66) for all HTTP downloads.
_tiktoken_network_blocked = False
_tiktoken_downloads_blocked = 0

try:
    import tiktoken.load as _tiktoken_load

    _orig_read_file = _tiktoken_load.read_file

    class TiktokenDownloadBlocked(RuntimeError):
        """Raised when tiktoken attempts a network download at runtime."""
        pass

    def _read_file_no_network(blobpath: str) -> bytes:
        global _tiktoken_downloads_blocked
        if "://" in blobpath:
            _tiktoken_downloads_blocked += 1
            cache_dir = Path(os.environ.get("TIKTOKEN_CACHE_DIR", ""))
            if cache_dir.exists() and any(cache_dir.iterdir()):
                hint = (
                    f"Cache exists at {cache_dir} but tiktoken tried to download "
                    f"{blobpath} — likely an encoding mismatch or corrupted cache. "
                    f"Delete .tiktoken-cache/ and re-run scripts/update-tokenizer.sh"
                )
            else:
                hint = (
                    f"tiktoken tried to download {blobpath} — "
                    f"run scripts/update-tokenizer.sh to populate the local cache"
                )
            raise TiktokenDownloadBlocked(hint)
        return _orig_read_file(blobpath)

    _tiktoken_load.read_file = _read_file_no_network

    try:
        _tiktoken_load.read_file("https://verify-patch")
        # Self-test didn't raise — patch may not be effective.
        # Use stderr, not logging — this fires before logging is configured.
        print(
            "CRITICAL: tiktoken network block failed — read_file did not raise for URL. "
            "Token counting will use heuristic fallback.",
            file=sys.stderr,
        )
    except RuntimeError:
        _tiktoken_network_blocked = True
except Exception as e:
    # Patching failed entirely (ImportError, AttributeError, etc.)
    # Defense-in-depth: try one more time with a minimal blocker.
    try:
        import tiktoken.load as _tiktoken_load_retry
        def _hard_block(blobpath: str) -> bytes:
            if "://" in blobpath:
                raise RuntimeError("tiktoken downloads blocked (network patch failed)")
            with open(blobpath, "rb") as f:
                return f.read()
        _tiktoken_load_retry.read_file = _hard_block
    except Exception:
        pass
    print(
        f"WARNING: tiktoken network block not applied — "
        f"token counting will use heuristic: {e}",
        file=sys.stderr,
    )

__version__ = "1.0.0"
__author__ = "Claude Code Proxy"

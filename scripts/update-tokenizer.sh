#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CACHE_DIR="$PROJECT_DIR/.tiktoken-cache"
KNOWN_HASHES="$SCRIPT_DIR/tokenizer-hashes.txt"

MODE="download"  # download (default), --verify-only, --strict
ENCODING=""

for arg in "$@"; do
    case "$arg" in
        --verify-only) MODE="verify" ;;
        --strict) MODE="download-strict" ;;
        --*) echo "Unknown flag: $arg"; echo "Usage: $0 [--verify-only|--strict] [encoding]"; exit 1 ;;
        *) ENCODING="$arg" ;;
    esac
done

if [ -z "$ENCODING" ] && [ -f "$PROJECT_DIR/.env" ]; then
    ENCODING="$(grep -E '^TOKENIZER_ENCODING=' "$PROJECT_DIR/.env" 2>/dev/null | cut -d= -f2 | tr -d '"' | tr -d "'" || true)"
fi
ENCODING="${ENCODING:-cl100k_base}"

if [ "$MODE" = "verify" ]; then
    echo "Verify-only mode: checking existing cache (no download)"
else
    echo "Downloading tiktoken encoding: $ENCODING"
fi
echo "Cache directory: $CACHE_DIR"
echo ""

if [ "$MODE" != "verify" ]; then
    mkdir -p "$CACHE_DIR"
    TIKTOKEN_CACHE_DIR="$CACHE_DIR" uv run --directory "$PROJECT_DIR" python -c "
import sys, tiktoken
enc = tiktoken.get_encoding(sys.argv[1])
print(f'  Encoding: {enc.name}')
print(f'  Vocabulary: {enc.max_token_value + 1} tokens')
" "$ENCODING"
fi

# Verify integrity against known-good hashes
VERIFIED=0
FAILED=0
UNVERIFIED_FILES=""
UNVERIFIED_COUNT=0
FILE_COUNT=0
echo ""
echo "Cache contents:"
for f in "$CACHE_DIR"/*; do
    [ -f "$f" ] || continue
    FILE_COUNT=$((FILE_COUNT + 1))
    BASENAME="$(basename "$f")"
    SIZE=$(stat --format="%s" "$f" 2>/dev/null || stat -f "%z" "$f" 2>/dev/null)
    HASH=$(sha256sum "$f" 2>/dev/null | cut -d' ' -f1 || shasum -a 256 "$f" 2>/dev/null | cut -d' ' -f1)

    if [ -f "$KNOWN_HASHES" ]; then
        EXPECTED=$(grep "^${BASENAME} " "$KNOWN_HASHES" 2>/dev/null | awk '{print $2}' || true)
        if [ -n "$EXPECTED" ]; then
            if [ "$HASH" = "$EXPECTED" ]; then
                echo "  $BASENAME  ${SIZE} bytes  sha256:${HASH}  [VERIFIED]"
                VERIFIED=$((VERIFIED + 1))
            else
                echo "  $BASENAME  ${SIZE} bytes  sha256:${HASH}  [MISMATCH — expected ${EXPECTED}]"
                FAILED=$((FAILED + 1))
            fi
        else
            echo "  $BASENAME  ${SIZE} bytes  sha256:${HASH}  [NEW — no reference hash]"
            UNVERIFIED_FILES="${UNVERIFIED_FILES}${BASENAME} ${HASH}\n"
            UNVERIFIED_COUNT=$((UNVERIFIED_COUNT + 1))
        fi
    else
        echo "  WARNING: $KNOWN_HASHES not found — integrity verification skipped"
        echo "  $BASENAME  ${SIZE} bytes  sha256:${HASH}"
        UNVERIFIED_FILES="${UNVERIFIED_FILES}${BASENAME} ${HASH}\n"
        UNVERIFIED_COUNT=$((UNVERIFIED_COUNT + 1))
    fi
done

echo ""

if [ "$FILE_COUNT" -eq 0 ]; then
    echo "ERROR: Cache directory is empty — no encoding data found."
    exit 1
fi

if [ "$FAILED" -gt 0 ]; then
    echo "ERROR: $FAILED file(s) failed checksum verification."
    echo "The cached data may be corrupted. Delete .tiktoken-cache/ and re-run this script."
    exit 1
fi

if [ "$UNVERIFIED_COUNT" -gt 0 ]; then
    if [ "$MODE" = "download-strict" ] || [ "$MODE" = "verify" ]; then
        echo "ERROR: $UNVERIFIED_COUNT file(s) have no reference hash — integrity not verified."
        echo "Re-run without --strict to be prompted to add the hash."
        exit 1
    fi

    echo "$UNVERIFIED_COUNT new file(s) have no reference hash."
    echo ""
    echo "To trust this download, review the evidence above and confirm."
    echo "This will add the hash(es) to $KNOWN_HASHES"
    echo "so future runs (and --strict / --verify-only) can verify integrity."
    echo ""
    printf "Pin these hashes to tokenizer-hashes.txt? [y/N] "
    read -r REPLY
    if [ "$REPLY" = "y" ] || [ "$REPLY" = "Y" ]; then
        printf "%b" "$UNVERIFIED_FILES" >> "$KNOWN_HASHES"
        echo "Hashes pinned."
    else
        echo "Skipped. The cache will work but integrity is unverified."
        echo "Use --strict to treat unverified files as errors."
    fi
fi

if [ "$VERIFIED" -gt 0 ]; then
    echo "Integrity: $VERIFIED file(s) verified against known-good hashes."
fi
echo "Done."
if [ "$MODE" != "verify" ]; then
    echo "Restart the proxy to pick up the new cache."
fi

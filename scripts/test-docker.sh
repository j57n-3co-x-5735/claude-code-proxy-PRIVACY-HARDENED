#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
IMAGE_NAME="claude-code-proxy-test"
CONTAINER_NAME="proxy-docker-test-$$"
PORT=3099

cleanup() {
    docker rm -f "$CONTAINER_NAME" 2>/dev/null || true
    docker rmi "$IMAGE_NAME" 2>/dev/null || true
}
trap cleanup EXIT

echo "=== Docker integration test ==="
echo ""

echo "1. Building image..."
docker build -t "$IMAGE_NAME" "$PROJECT_DIR" --quiet

echo "2. Starting container on port $PORT..."
docker run -d --name "$CONTAINER_NAME" \
    -p "$PORT:3000" \
    -e OPENAI_API_KEY=test-key-for-docker-test \
    -e PORT=3000 \
    -e HOST=0.0.0.0 \
    "$IMAGE_NAME" > /dev/null

echo "3. Waiting for proxy to start..."
RETRIES=0
MAX_RETRIES=15
while [ $RETRIES -lt $MAX_RETRIES ]; do
    if curl -sf "http://localhost:$PORT/health" > /dev/null 2>&1; then
        break
    fi
    RETRIES=$((RETRIES + 1))
    sleep 1
done

if [ $RETRIES -eq $MAX_RETRIES ]; then
    echo "FAIL: Proxy did not start within ${MAX_RETRIES}s"
    echo "Container logs:"
    docker logs "$CONTAINER_NAME"
    exit 1
fi

echo "4. Checking health endpoint..."
HEALTH=$(curl -sf "http://localhost:$PORT/health")
echo "   $HEALTH"

TIKTOKEN_AVAILABLE=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tiktoken_available', 'MISSING'))")
if [ "$TIKTOKEN_AVAILABLE" = "True" ]; then
    echo "   tiktoken_available: true [PASS]"
elif [ "$TIKTOKEN_AVAILABLE" = "MISSING" ]; then
    echo "   FAIL: tiktoken_available field missing from /health"
    exit 1
else
    echo "   FAIL: tiktoken_available is $TIKTOKEN_AVAILABLE (expected true)"
    echo "   This means the Docker build did not pre-cache the tiktoken encoding."
    echo "   Container logs:"
    docker logs "$CONTAINER_NAME"
    exit 1
fi

echo "5. Checking token counting..."
TOKEN_RESPONSE=$(curl -sf -X POST "http://localhost:$PORT/v1/messages/count_tokens" \
    -H "Content-Type: application/json" \
    -d '{"model":"test","messages":[{"role":"user","content":"hello world"}]}')
echo "   $TOKEN_RESPONSE"

INPUT_TOKENS=$(echo "$TOKEN_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('input_tokens', 0))")
if [ "$INPUT_TOKENS" -gt 0 ]; then
    echo "   input_tokens: $INPUT_TOKENS [PASS]"
else
    echo "   FAIL: input_tokens is 0 or missing"
    exit 1
fi

echo ""
echo "=== All Docker integration tests passed ==="

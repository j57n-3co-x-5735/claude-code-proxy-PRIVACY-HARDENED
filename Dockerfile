FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Copy the project into the image
ADD . /app

# Sync the project into a new environment, asserting the lockfile is up to date
WORKDIR /app
RUN uv sync --locked

# Pre-cache tiktoken encoding into project-local persistent cache.
# Runs at build time (before src/__init__.py monkeypatch), so download works normally.
ARG TOKENIZER_ENCODING=cl100k_base
ENV TIKTOKEN_CACHE_DIR=/app/.tiktoken-cache
RUN mkdir -p /app/.tiktoken-cache && \
    uv run python -c "import sys, tiktoken; tiktoken.get_encoding(sys.argv[1])" "$TOKENIZER_ENCODING"

CMD ["uv", "run", "start_proxy.py"]

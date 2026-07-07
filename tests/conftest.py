import os

# The unit suite mocks the upstream client, so no real key is needed — but
# src.core.config builds Config() at import time and exits if OPENAI_API_KEY is
# unset. This runs at conftest import, before any test module imports src, so a
# clean checkout (CI, no .env) can still collect. setdefault yields to a real
# key from the environment or .env when one is present.
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import pytest
from unittest.mock import patch


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def neutralize_api_key_validation():
    """Disable API key validation for all tests unless explicitly overridden."""
    with patch("src.api.endpoints.config.anthropic_api_key", None):
        yield

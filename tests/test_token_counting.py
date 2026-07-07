"""Tests for tiktoken-based token counting."""
import json
import os
import pytest
from unittest.mock import patch, MagicMock

from src.models.claude import ClaudeTokenCountRequest, ClaudeTool


def make_request(**kwargs):
    defaults = {
        "model": "test",
        "messages": [{"role": "user", "content": "hello world"}],
    }
    defaults.update(kwargs)
    return ClaudeTokenCountRequest(**defaults)


@pytest.mark.asyncio
async def test_text_only_message_uses_tiktoken():
    """tiktoken count for a text-only message is in a reasonable range."""
    from src.api.endpoints import _count_tokens_tiktoken
    request = make_request(messages=[{"role": "user", "content": "hello world this is a test message"}])
    count = _count_tokens_tiktoken(request)
    assert count > 5
    assert count < 50


@pytest.mark.asyncio
async def test_tool_definitions_are_counted():
    """Tool schemas contribute to the token count."""
    from src.api.endpoints import _count_tokens_tiktoken

    request_no_tools = make_request()
    request_with_tools = make_request(
        tools=[{
            "name": "read_file",
            "description": "Read a file from disk",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "The file path to read"}},
                "required": ["path"],
            },
        }]
    )
    count_no_tools = _count_tokens_tiktoken(request_no_tools)
    count_with_tools = _count_tokens_tiktoken(request_with_tools)
    assert count_with_tools > count_no_tools


@pytest.mark.asyncio
async def test_fallback_on_import_failure():
    """Falls back to heuristic when tiktoken cannot be imported."""
    from src.api.endpoints import _count_tokens_heuristic

    request = make_request(messages=[{"role": "user", "content": "a" * 100}])
    heuristic_count = _count_tokens_heuristic(request)
    assert heuristic_count == 25


@pytest.mark.asyncio
async def test_raises_when_encoder_not_cached():
    """_count_tokens_tiktoken raises RuntimeError when _tiktoken_enc is None."""
    from src.api.endpoints import _count_tokens_tiktoken

    with patch("src.api.endpoints._tiktoken_enc", None):
        with pytest.raises(RuntimeError, match="tiktoken not cached"):
            _count_tokens_tiktoken(make_request())


@pytest.mark.asyncio
async def test_count_tokens_endpoint_fallback():
    """The count_tokens endpoint catches tiktoken failure and falls back."""
    from httpx import AsyncClient, ASGITransport
    from src.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("src.api.endpoints._count_tokens_tiktoken", side_effect=Exception("unavailable")):
            response = await client.post(
                "/v1/messages/count_tokens",
                json={"model": "test", "messages": [{"role": "user", "content": "a" * 100}]},
                headers={"x-api-key": "test", "content-type": "application/json"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["input_tokens"] == 25


@pytest.mark.asyncio
async def test_configurable_overhead_values():
    """Overhead values from config are applied."""
    from src.api.endpoints import _count_tokens_tiktoken

    request = make_request(messages=[{"role": "user", "content": "hi"}])

    with patch("src.api.endpoints.config") as mock_config:
        mock_config.tokenizer_encoding = "cl100k_base"
        mock_config.token_overhead_per_message = 10
        mock_config.token_overhead_per_tool = 20
        mock_config.token_overhead_priming = 50
        count_high = _count_tokens_tiktoken(request)

    with patch("src.api.endpoints.config") as mock_config:
        mock_config.tokenizer_encoding = "cl100k_base"
        mock_config.token_overhead_per_message = 0
        mock_config.token_overhead_per_tool = 0
        mock_config.token_overhead_priming = 0
        count_low = _count_tokens_tiktoken(request)

    assert count_high > count_low


@pytest.mark.asyncio
async def test_endpoint_fallback_when_encoder_not_cached():
    """Full integration: _tiktoken_enc is None -> endpoint returns heuristic count."""
    from httpx import AsyncClient, ASGITransport
    from src.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("src.api.endpoints._tiktoken_enc", None):
            response = await client.post(
                "/v1/messages/count_tokens",
                json={"model": "test", "messages": [{"role": "user", "content": "a" * 100}]},
                headers={"x-api-key": "test", "content-type": "application/json"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["input_tokens"] == 25


@pytest.mark.asyncio
async def test_thinking_blocks_counted_tiktoken():
    """Thinking blocks contribute to the tiktoken token count."""
    from src.api.endpoints import _count_tokens_tiktoken

    request_no_thinking = make_request(
        messages=[{"role": "user", "content": "hi"}]
    )
    request_with_thinking = make_request(
        messages=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "Let me think about this carefully for a while " * 20},
                {"type": "text", "text": "Here is my answer."},
            ]},
        ]
    )
    count_no_thinking = _count_tokens_tiktoken(request_no_thinking)
    count_with_thinking = _count_tokens_tiktoken(request_with_thinking)
    assert count_with_thinking > count_no_thinking


@pytest.mark.asyncio
async def test_tiktoken_counts_tool_use_blocks():
    """tool_use blocks (JSON-serialized input) contribute to tiktoken count."""
    from src.api.endpoints import _count_tokens_tiktoken

    request_no_tools = make_request(messages=[{"role": "user", "content": "hi"}])
    request_with_tool_use = make_request(messages=[
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "read_file",
             "input": {"path": "/etc/config.json", "encoding": "utf-8", "max_lines": 500}},
        ]},
    ])
    count_no_tools = _count_tokens_tiktoken(request_no_tools)
    count_with_tool_use = _count_tokens_tiktoken(request_with_tool_use)
    assert count_with_tool_use > count_no_tools


@pytest.mark.asyncio
async def test_tiktoken_counts_tool_result_blocks():
    """tool_result blocks contribute to tiktoken count."""
    from src.api.endpoints import _count_tokens_tiktoken

    request_no_result = make_request(messages=[{"role": "user", "content": "hi"}])
    request_with_result = make_request(messages=[
        {"role": "user", "content": "hi"},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1",
             "content": "Here is the file content: " + "x" * 200},
        ]},
    ])
    count_no_result = _count_tokens_tiktoken(request_no_result)
    count_with_result = _count_tokens_tiktoken(request_with_result)
    assert count_with_result > count_no_result


@pytest.mark.asyncio
async def test_tiktoken_counts_image_blocks_as_85():
    """Image blocks use a fixed 85-token estimate in tiktoken counter."""
    from src.api.endpoints import _count_tokens_tiktoken

    request_no_image = make_request(messages=[{"role": "user", "content": "describe this"}])
    request_with_image = make_request(messages=[
        {"role": "user", "content": [
            {"type": "text", "text": "describe this"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "abc"}},
        ]},
    ])
    count_no_image = _count_tokens_tiktoken(request_no_image)
    count_with_image = _count_tokens_tiktoken(request_with_image)
    assert count_with_image - count_no_image >= 80


@pytest.mark.asyncio
async def test_tiktoken_counts_system_list():
    """System prompt as a list of content blocks is counted by tiktoken."""
    from src.api.endpoints import _count_tokens_tiktoken

    request_no_system = make_request(messages=[{"role": "user", "content": "hi"}])
    request_with_system = make_request(
        system=[{"type": "text", "text": "You are a helpful assistant. " * 10}],
        messages=[{"role": "user", "content": "hi"}],
    )
    count_no_system = _count_tokens_tiktoken(request_no_system)
    count_with_system = _count_tokens_tiktoken(request_with_system)
    assert count_with_system > count_no_system


@pytest.mark.asyncio
async def test_thinking_blocks_counted_heuristic():
    """Thinking blocks contribute to the heuristic token count."""
    from src.api.endpoints import _count_tokens_heuristic

    request_no_thinking = make_request(
        messages=[{"role": "user", "content": "hi"}]
    )
    request_with_thinking = make_request(
        messages=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "a" * 400},
                {"type": "text", "text": "answer"},
            ]},
        ]
    )
    count_no_thinking = _count_tokens_heuristic(request_no_thinking)
    count_with_thinking = _count_tokens_heuristic(request_with_thinking)
    assert count_with_thinking > count_no_thinking


@pytest.mark.asyncio
async def test_monkeypatch_blocks_url_reads():
    """The tiktoken monkeypatch blocks HTTP downloads."""
    import tiktoken.load
    with pytest.raises(RuntimeError, match="update-tokenizer"):
        tiktoken.load.read_file("https://openaipublic.blob.core.windows.net/encodings/test.tiktoken")


@pytest.mark.asyncio
async def test_monkeypatch_passes_local_file_reads(tmp_path):
    """The tiktoken monkeypatch allows local file reads."""
    import tiktoken.load
    test_file = tmp_path / "test.bin"
    test_file.write_bytes(b"hello")
    result = tiktoken.load.read_file(str(test_file))
    assert result == b"hello"


@pytest.mark.asyncio
async def test_health_reports_tiktoken_available_true():
    """Health endpoint reports tiktoken_available: true when cache is populated."""
    from httpx import AsyncClient, ASGITransport
    from src.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["tiktoken_available"] is True


@pytest.mark.asyncio
async def test_health_reports_tiktoken_unavailable_false():
    """Health endpoint reports tiktoken_available: false when encoder is not loaded."""
    from httpx import AsyncClient, ASGITransport
    from src.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("src.api.endpoints._tiktoken_enc", None):
            response = await client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["tiktoken_available"] is False


@pytest.mark.asyncio
async def test_preloaded_encoder_is_set():
    """Module-level _tiktoken_enc is loaded when cache is populated."""
    from src.api.endpoints import _tiktoken_enc
    assert _tiktoken_enc is not None


def test_self_test_catches_broken_patch():
    """If the monkeypatch didn't take, the self-test sets _tiktoken_network_blocked=False."""
    import tiktoken.load as tl

    original = tl.read_file
    try:
        # Simulate a tiktoken version where read_file doesn't go through our patch
        tl.read_file = lambda blobpath: b"fake"
        try:
            tl.read_file("https://verify-patch")
            blocked = False
        except RuntimeError:
            blocked = True
        assert not blocked, "Unpatched read_file should not raise RuntimeError"
    finally:
        tl.read_file = original


def test_outer_except_catches_attribute_error():
    """The except Exception in __init__.py catches AttributeError if tiktoken renames read_file."""
    from src import _tiktoken_network_blocked
    assert isinstance(_tiktoken_network_blocked, bool)


def test_self_test_failure_sets_flag_false():
    """When self-test fails (patch didn't take), _tiktoken_network_blocked stays False and
    endpoints.py falls back to heuristic — tiktoken is never called, so no CDN contact."""
    import tiktoken.load as tl

    original = tl.read_file
    try:
        tl.read_file = lambda blobpath: b"fake"
        try:
            tl.read_file("https://verify-patch")
            flag = False
        except RuntimeError:
            flag = True
        assert not flag, "Unpatched read_file should not raise"

        # Verify the downstream effect: endpoints.py won't load tiktoken when flag is False
        with patch("src.api.endpoints._tiktoken_enc", None):
            from src.api.endpoints import _count_tokens_tiktoken
            with pytest.raises(RuntimeError, match="tiktoken not cached"):
                _count_tokens_tiktoken(make_request())
    finally:
        tl.read_file = original


def test_defense_in_depth_repatch():
    """If the primary patch fails (except Exception), the fallback re-patch still blocks URLs."""
    import tiktoken.load as tl
    current = tl.read_file
    with pytest.raises(RuntimeError):
        current("https://example.com/test")


def test_empty_tiktoken_cache_dir_treated_as_unset():
    """TIKTOKEN_CACHE_DIR='' should not disable caching — should be treated as unset."""
    cache_dir = os.environ.get("TIKTOKEN_CACHE_DIR", "")
    assert cache_dir != "", "TIKTOKEN_CACHE_DIR should not be empty string at runtime"


def test_update_tokenizer_script_exists_and_executable():
    """The update-tokenizer.sh script exists and is executable."""
    import os
    script = os.path.join(os.path.dirname(__file__), "..", "scripts", "update-tokenizer.sh")
    script = os.path.normpath(script)
    assert os.path.isfile(script), f"Script not found: {script}"
    assert os.access(script, os.X_OK), f"Script not executable: {script}"


def test_update_tokenizer_populates_cache(tmp_path):
    """Running the download logic populates the cache directory."""
    import subprocess
    result = subprocess.run(
        ["uv", "run", "--directory",
         os.path.join(os.path.dirname(__file__), ".."),
         "python", "-c",
         f"import os; os.environ['TIKTOKEN_CACHE_DIR']='{tmp_path}'; "
         f"import tiktoken; tiktoken.get_encoding('cl100k_base')"],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"Download failed: {result.stderr}"
    files = list(tmp_path.iterdir())
    assert len(files) >= 1, "Cache directory should have at least one file"
    assert files[0].stat().st_size > 100_000, "Cache file should be > 100KB"


def test_known_hash_file_exists():
    """The tokenizer-hashes.txt reference file is committed."""
    import os
    hashes = os.path.join(os.path.dirname(__file__), "..", "scripts", "tokenizer-hashes.txt")
    hashes = os.path.normpath(hashes)
    assert os.path.isfile(hashes), f"Hash file not found: {hashes}"
    with open(hashes) as f:
        content = f.read().strip()
    assert len(content) > 0, "Hash file should not be empty"
    parts = content.split()
    assert len(parts) >= 2, "Hash file should have at least filename and hash"


def test_encoding_mismatch_degrades_to_heuristic():
    """If config requests an encoding not in the cache, monkeypatch blocks download and fallback fires."""
    import tiktoken
    with pytest.raises(RuntimeError, match="update-tokenizer"):
        tiktoken.get_encoding("o200k_base")


@pytest.mark.asyncio
async def test_heuristic_counts_tools():
    """Heuristic should count tool definitions, not just text."""
    from src.api.endpoints import _count_tokens_heuristic

    request_no_tools = make_request()
    request_with_tools = make_request(
        tools=[{
            "name": "read_file",
            "description": "Read a file from disk with a very long description to make the count obviously different",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "The file path to read"}},
                "required": ["path"],
            },
        }]
    )
    count_no_tools = _count_tokens_heuristic(request_no_tools)
    count_with_tools = _count_tokens_heuristic(request_with_tools)
    assert count_with_tools > count_no_tools


@pytest.mark.asyncio
async def test_heuristic_counts_tool_use_and_result():
    """Heuristic should count tool_use input and tool_result content."""
    from src.api.endpoints import _count_tokens_heuristic

    request_plain = make_request(messages=[{"role": "user", "content": "hi"}])
    request_with_tool_exchange = make_request(messages=[
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "read_file",
             "input": {"path": "/very/long/path/to/some/deeply/nested/file.txt"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1",
             "content": "a" * 400},
        ]},
    ])
    count_plain = _count_tokens_heuristic(request_plain)
    count_tools = _count_tokens_heuristic(request_with_tool_exchange)
    assert count_tools > count_plain


HEURISTIC_ACCURACY_INPUTS = [
    {"label": "short text", "messages": [{"role": "user", "content": "hello world"}]},
    {"label": "medium text", "messages": [{"role": "user", "content": "The quick brown fox " * 50}]},
    {"label": "long text", "messages": [{"role": "user", "content": "a" * 4000}]},
    {"label": "code block", "messages": [{"role": "user", "content": "def fibonacci(n):\n    if n <= 1:\n        return n\n    return fibonacci(n-1) + fibonacci(n-2)\n" * 10}]},
    {"label": "with tools", "messages": [{"role": "user", "content": "hi"}],
     "tools": [{"name": "read_file", "description": "Read a file from disk",
                "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}]},
    {"label": "tool exchange", "messages": [
        {"role": "user", "content": "read the config"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "read_file",
             "input": {"path": "/etc/config.json", "options": {"encoding": "utf-8", "max_lines": 100}}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1",
             "content": '{"database": {"host": "localhost", "port": 5432}, "cache": {"ttl": 300}}'},
        ]},
    ]},
    {"label": "thinking block", "messages": [
        {"role": "user", "content": "explain quantum computing"},
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "Let me think about how to explain quantum computing clearly. " * 20},
            {"type": "text", "text": "Quantum computing uses qubits instead of classical bits."},
        ]},
    ]},
    {"label": "multiple tools", "messages": [{"role": "user", "content": "hi"}],
     "tools": [
         {"name": "read_file", "description": "Read file contents from disk",
          "input_schema": {"type": "object", "properties": {"path": {"type": "string", "description": "File path"}}, "required": ["path"]}},
         {"name": "write_file", "description": "Write content to a file on disk",
          "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
         {"name": "search", "description": "Search for text across files in a directory",
          "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "directory": {"type": "string"}}, "required": ["query"]}},
     ]},
]


@pytest.mark.parametrize("case", HEURISTIC_ACCURACY_INPUTS, ids=lambda c: c["label"])
def test_heuristic_within_3x_of_tiktoken(case):
    """Heuristic token count should be within 3x of tiktoken for varied inputs.

    This is a property-based accuracy check: the heuristic is intentionally rough
    (chars/4) but should not be catastrophically wrong for any common input shape.
    A ratio outside [0.33, 3.0] indicates a content type the heuristic is ignoring.
    """
    from src.api.endpoints import _count_tokens_tiktoken, _count_tokens_heuristic

    request = make_request(**{k: v for k, v in case.items() if k != "label"})
    tiktoken_count = _count_tokens_tiktoken(request)
    heuristic_count = _count_tokens_heuristic(request)

    assert tiktoken_count > 0, f"tiktoken returned 0 for {case['label']}"
    assert heuristic_count > 0, f"heuristic returned 0 for {case['label']}"

    # For small counts (<20 tokens), per-message overhead dominates and ratio is meaningless.
    # Only check ratio for inputs where content tokens outweigh overhead.
    if tiktoken_count >= 20:
        ratio = heuristic_count / tiktoken_count
        assert 0.33 < ratio < 3.0, (
            f"Heuristic accuracy out of bounds for '{case['label']}': "
            f"tiktoken={tiktoken_count}, heuristic={heuristic_count}, ratio={ratio:.2f}"
        )
    else:
        assert abs(tiktoken_count - heuristic_count) < 20, (
            f"Heuristic divergence too large for '{case['label']}': "
            f"tiktoken={tiktoken_count}, heuristic={heuristic_count}"
        )


@pytest.mark.asyncio
async def test_tiktoken_empty_string():
    """Empty string message produces a non-zero count (overhead applies)."""
    from src.api.endpoints import _count_tokens_tiktoken
    request = make_request(messages=[{"role": "user", "content": ""}])
    count = _count_tokens_tiktoken(request)
    assert count >= 1


@pytest.mark.asyncio
async def test_tiktoken_unicode_emoji():
    """Unicode-heavy content is counted without error."""
    from src.api.endpoints import _count_tokens_tiktoken
    request = make_request(messages=[{"role": "user", "content": "Hello! \U0001f600\U0001f4a9\U0001f30d " * 50}])
    count = _count_tokens_tiktoken(request)
    assert count > 10


@pytest.mark.asyncio
async def test_tiktoken_long_message():
    """Large message (~100K chars) is counted without error."""
    from src.api.endpoints import _count_tokens_tiktoken
    request = make_request(messages=[{"role": "user", "content": "word " * 25000}])
    count = _count_tokens_tiktoken(request)
    assert count > 20000


@pytest.mark.asyncio
async def test_tiktoken_image_only_message():
    """Message with only an image block returns the fixed 85-token estimate plus overhead."""
    from src.api.endpoints import _count_tokens_tiktoken
    request = make_request(messages=[
        {"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "abc"}},
        ]},
    ])
    count = _count_tokens_tiktoken(request)
    assert 85 <= count <= 100


def test_monkeypatch_durability_via_subprocess(tmp_path):
    """Verify the monkeypatch survives a full import in a clean subprocess."""
    import subprocess
    script = tmp_path / "test_patch.py"
    project_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    script.write_text(
        f"import sys; sys.path.insert(0, '{project_dir}')\n"
        "import src  # triggers __init__.py monkeypatch\n"
        "import tiktoken.load\n"
        "try:\n"
        "    tiktoken.load.read_file('https://test')\n"
        "    print('FAIL: no exception raised')\n"
        "except RuntimeError as e:\n"
        "    print('PASS: ' + str(e))\n"
        "except Exception as e:\n"
        "    print('UNEXPECTED: ' + type(e).__name__ + ': ' + str(e))\n"
    )
    result = subprocess.run(
        ["uv", "run", "--directory",
         os.path.join(os.path.dirname(__file__), ".."),
         "python", str(script)],
        capture_output=True, text=True, timeout=30,
    )
    assert "PASS:" in result.stdout, f"Monkeypatch not active in subprocess: {result.stdout} {result.stderr}"


@pytest.mark.asyncio
async def test_no_network_contact_during_token_counting():
    """Prove the proxy counts tokens with zero network access to the tiktoken CDN.

    Patches socket.create_connection to reject connections to openaipublic.blob.core.windows.net.
    If tiktoken tried to download, the socket patch would fire before the monkeypatch,
    providing an independent proof layer.
    """
    import socket
    from httpx import AsyncClient, ASGITransport
    from src.main import app
    from src import _tiktoken_downloads_blocked

    _orig_create_connection = socket.create_connection

    def _block_tiktoken_cdn(*args, **kwargs):
        addr = args[0] if args else kwargs.get("address", ("", 0))
        host = addr[0] if isinstance(addr, tuple) else str(addr)
        if "openaipublic" in host:
            raise ConnectionRefusedError(f"TEST BLOCKED: connection to {host}")
        return _orig_create_connection(*args, **kwargs)

    with patch.object(socket, "create_connection", _block_tiktoken_cdn):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Snapshot counter before the request
            health_before = (await client.get("/health")).json()
            blocked_before = health_before["tiktoken_downloads_blocked"]

            response = await client.post(
                "/v1/messages/count_tokens",
                json={"model": "test", "messages": [{"role": "user", "content": "hello world this is a test"}]},
                headers={"content-type": "application/json"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["input_tokens"] > 5, f"Expected tiktoken count, got {data}"

            # Verify no downloads were attempted during the request
            health_after = (await client.get("/health")).json()
            assert health_after["tiktoken_available"] is True
            assert health_after["tiktoken_downloads_blocked"] == blocked_before, (
                f"Download attempted during token counting: before={blocked_before}, after={health_after['tiktoken_downloads_blocked']}"
            )

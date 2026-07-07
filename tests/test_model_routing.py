"""Tests for model routing auto-prefix (plan item 3.4)."""
import pytest
from unittest.mock import MagicMock


def make_manager(model_prefix="accounts/fireworks/models/", big="gpt-4o", middle=None, small="gpt-4o-mini"):
    from src.core.model_manager import ModelManager
    config = MagicMock()
    config.model_prefix = model_prefix
    config.big_model = big
    config.middle_model = middle or big
    config.small_model = small
    return ModelManager(config)


def test_bare_deepseek_gets_prefixed():
    """Bare deepseek-* names auto-prefix with MODEL_PREFIX."""
    mgr = make_manager()
    result = mgr.map_claude_model_to_openai("deepseek-v4-pro")
    assert result == "accounts/fireworks/models/deepseek-v4-pro"


def test_already_prefixed_passes_through():
    """Models starting with accounts/ pass through unchanged."""
    mgr = make_manager()
    result = mgr.map_claude_model_to_openai("accounts/fireworks/models/deepseek-v4-pro")
    assert result == "accounts/fireworks/models/deepseek-v4-pro"


def test_empty_prefix_disables_auto_prefix():
    """Setting MODEL_PREFIX="" disables auto-prefixing."""
    mgr = make_manager(model_prefix="")
    result = mgr.map_claude_model_to_openai("deepseek-v4-pro")
    assert result == "deepseek-v4-pro"


def test_claude_haiku_maps_to_small_model():
    """Claude haiku names map to SMALL_MODEL, not prefixed."""
    mgr = make_manager(small="accounts/fireworks/models/deepseek-v4-flash")
    result = mgr.map_claude_model_to_openai("claude-3-5-haiku-20241022")
    assert result == "accounts/fireworks/models/deepseek-v4-flash"


def test_claude_sonnet_maps_to_middle_model():
    """Claude sonnet names map to MIDDLE_MODEL."""
    mgr = make_manager(middle="accounts/fireworks/models/deepseek-v4-pro")
    result = mgr.map_claude_model_to_openai("claude-sonnet-4-20250514")
    assert result == "accounts/fireworks/models/deepseek-v4-pro"


def test_claude_opus_maps_to_big_model():
    """Claude opus names map to BIG_MODEL."""
    mgr = make_manager(big="accounts/fireworks/models/deepseek-v4-pro")
    result = mgr.map_claude_model_to_openai("claude-opus-4-20250514")
    assert result == "accounts/fireworks/models/deepseek-v4-pro"


def test_unknown_model_defaults_to_big():
    """Unknown model names default to BIG_MODEL."""
    mgr = make_manager(big="my-custom-model")
    result = mgr.map_claude_model_to_openai("some-unknown-model")
    assert result == "my-custom-model"


def test_gpt_models_pass_through():
    """OpenAI model names pass through as-is."""
    mgr = make_manager()
    assert mgr.map_claude_model_to_openai("gpt-4o") == "gpt-4o"
    assert mgr.map_claude_model_to_openai("o1-preview") == "o1-preview"


def test_custom_prefix():
    """Custom MODEL_PREFIX is applied correctly."""
    mgr = make_manager(model_prefix="my-provider/models/")
    result = mgr.map_claude_model_to_openai("deepseek-v4-pro")
    assert result == "my-provider/models/deepseek-v4-pro"

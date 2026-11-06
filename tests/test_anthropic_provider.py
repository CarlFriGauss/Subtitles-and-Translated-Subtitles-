"""BUG-2: the Anthropic translation route must use a current model and request shape."""

import pytest

import subgen_planner
import subgen_providers as providers

PROVIDER = providers.BUILTIN_PROVIDERS["anthropic"]


def test_default_model_is_current():
    assert PROVIDER["translation_model"] == providers.ANTHROPIC_DEFAULT_TRANSLATION_MODEL
    assert subgen_planner.TRANSLATION_MODEL_DEFAULTS["anthropic"] == providers.ANTHROPIC_DEFAULT_TRANSLATION_MODEL
    assert ("anthropic", providers.ANTHROPIC_DEFAULT_TRANSLATION_MODEL) in subgen_planner.MODEL_CATALOG


@pytest.mark.parametrize("stored", ["claude-3-5-sonnet-latest", "claude-3-5-sonnet-20241022", "", None])
def test_retired_or_missing_models_map_to_current(stored):
    assert providers.current_anthropic_model(stored) == providers.ANTHROPIC_DEFAULT_TRANSLATION_MODEL


def test_explicit_current_model_is_kept():
    assert providers.current_anthropic_model("claude-opus-5-5") == "claude-opus-5-5"


def test_request_has_no_sampling_parameters_and_enables_fallback():
    url, payload, headers = providers.build_anthropic_translation_request(PROVIDER, "p", "i", "claude-3-5-sonnet-latest")
    assert url == "https://api.anthropic.com/v1/messages"
    assert payload["model"] == providers.ANTHROPIC_DEFAULT_TRANSLATION_MODEL
    assert not {"temperature", "top_p", "top_k"} & payload.keys()
    assert payload["fallbacks"] == "default"
    assert headers["anthropic-beta"] == "server-side-fallback-2026-07-01"


def test_custom_base_url_gets_no_first_party_only_fields():
    provider = dict(PROVIDER, base_url="https://proxy.example/anthropic")
    url, payload, headers = providers.build_anthropic_translation_request(provider, "p", "i", None)
    assert url == "https://proxy.example/anthropic/v1/messages"
    assert "fallbacks" not in payload and headers == {}


def test_refusal_raises_clear_error():
    with pytest.raises(RuntimeError, match="refusal category: cyber"):
        providers.anthropic_response_text({"stop_reason": "refusal", "stop_details": {"category": "cyber"}, "content": []})


def test_truncation_raises_clear_error():
    with pytest.raises(ValueError, match="max_tokens"):
        providers.anthropic_response_text({"stop_reason": "max_tokens", "content": [{"type": "text", "text": "{"}]})


def test_thinking_blocks_are_ignored():
    response = {"stop_reason": "end_turn", "content": [
        {"type": "thinking", "thinking": ""},
        {"type": "text", "text": '{"translations": []}'},
    ]}
    assert providers.anthropic_response_text(response) == '{"translations": []}'


def test_call_sends_built_request(monkeypatch):
    captured = {}

    def fake_post_json(url, payload, headers, *args, **kwargs):
        captured.update(url=url, payload=payload, headers=headers)
        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": '{"translations": []}'}], "usage": {}}

    monkeypatch.setattr(providers, "post_json", fake_post_json)
    providers.call_anthropic_translation(PROVIDER, "sk-test-000", "p", "i", "claude-3-5-sonnet-latest")
    assert captured["payload"]["model"] == providers.ANTHROPIC_DEFAULT_TRANSLATION_MODEL
    assert captured["headers"]["x-api-key"] == "sk-test-000"
    assert "temperature" not in captured["payload"]


@pytest.mark.parametrize("model", ["claude-haiku-4-5", "claude-haiku-5-5", "claude-sonnet-4-6"])
def test_fallbacks_only_for_models_that_support_them(model):
    _, payload, headers = providers.build_anthropic_translation_request(PROVIDER, "p", "i", model)
    assert "fallbacks" not in payload and "anthropic-beta" not in headers

"""BUG-6: LLM translation batches must survive imperfect model responses."""

import json

import pytest

import subgen_pipeline as pipeline


def segments(count):
    return [{"start": float(i), "end": float(i) + 1, "text": f"line {i}"} for i in range(count)]


@pytest.fixture()
def provider(monkeypatch):
    """A scripted provider. `behaviour(start, end, call_number)` returns a response."""
    state = {"calls": [], "behaviour": None}

    monkeypatch.setattr(
        pipeline, "build_llm_translation_prompt",
        lambda context, start, end: json.dumps({"start": start, "end": end}),
    )

    def fake_call(provider_config, provider_id, prompt, instructions, model=None):
        rng = json.loads(prompt)
        state["calls"].append((rng["start"], rng["end"]))
        return state["behaviour"](rng["start"], rng["end"], len(state["calls"]))

    monkeypatch.setattr(pipeline, "call_provider_translation", fake_call)
    return state


def complete(start, end):
    return {"translations": [{"index": i, "text": f"T{i}"} for i in range(start, end)]}


def translate(count):
    return pipeline.translate_segments_openai(
        segments(count), "en", "he", model="m", batch_size=4, provider_id="fake", provider_config={},
    )


def test_empty_input_returns_empty_list(provider):
    provider["behaviour"] = lambda *a: pytest.fail("no request expected")
    assert translate(0) == []


def test_string_indices_are_accepted(provider):
    provider["behaviour"] = lambda s, e, n: {"translations": [{"index": str(i), "text": f"T{i}"} for i in range(s, e)]}
    assert [seg["text"] for seg in translate(4)] == ["T0", "T1", "T2", "T3"]


def test_missing_index_is_retried(provider):
    def behaviour(s, e, n):
        response = complete(s, e)
        if n == 1:
            response["translations"].pop()
        return response
    provider["behaviour"] = behaviour
    assert [seg["text"] for seg in translate(4)] == ["T0", "T1", "T2", "T3"]
    assert provider["calls"] == [(0, 4), (0, 4)]


def test_persistent_gap_splits_the_batch(provider):
    def behaviour(s, e, n):
        response = complete(s, e)
        if e - s > 1:  # the model always drops index 2 in multi-line batches
            response["translations"] = [t for t in response["translations"] if t["index"] != 2]
        return response
    provider["behaviour"] = behaviour
    assert [seg["text"] for seg in translate(4)] == ["T0", "T1", "T2", "T3"]
    assert (2, 3) in provider["calls"]


def test_malformed_json_is_retried(provider):
    def behaviour(s, e, n):
        if n == 1:
            raise json.JSONDecodeError("truncated", "{", 1)
        return complete(s, e)
    provider["behaviour"] = behaviour
    assert len(translate(4)) == 4


def test_provider_errors_are_not_retried(provider):
    def behaviour(s, e, n):
        raise RuntimeError("HTTP 401: invalid api key")
    provider["behaviour"] = behaviour
    with pytest.raises(RuntimeError, match="401"):
        translate(4)
    assert len(provider["calls"]) == 1


def test_duplicate_indices_keep_the_first_answer(provider):
    provider["behaviour"] = lambda s, e, n: {"translations": complete(s, e)["translations"] + [{"index": 0, "text": "WRONG"}]}
    assert translate(4)[0]["text"] == "T0"


def test_unrecoverable_single_line_reports_index(provider):
    provider["behaviour"] = lambda s, e, n: {"translations": []}
    with pytest.raises(RuntimeError, match="fake translation failed for subtitle index 0"):
        translate(1)

"""BUG-7: one retry policy for every paid provider call."""

import io
import json
import socket
import urllib.error

import pytest

import subgen_http


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code, body=b"{}", headers=None):
    return urllib.error.HTTPError("https://x", code, "err", headers or {}, io.BytesIO(body))


@pytest.fixture()
def scripted(monkeypatch):
    """Script urlopen outcomes in order; record sleeps instead of sleeping."""
    state = {"outcomes": [], "calls": 0, "sleeps": []}

    def fake_urlopen(request, timeout=None):
        state["calls"] += 1
        outcome = state["outcomes"].pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return FakeResponse(json.dumps(outcome).encode("utf-8"))

    monkeypatch.setattr(subgen_http.urllib.request, "urlopen", fake_urlopen)
    return state


def post(state, **kwargs):
    return subgen_http.post_for_json("https://x", b"{}", {}, timeout=5, sleep=state["sleeps"].append, **kwargs)


def test_success(scripted):
    scripted["outcomes"] = [{"ok": True}]
    assert post(scripted) == {"ok": True}


def test_429_then_success_honours_retry_after(scripted):
    scripted["outcomes"] = [http_error(429, headers={"Retry-After": "7"}), {"ok": 1}]
    assert post(scripted) == {"ok": 1}
    assert scripted["sleeps"] == [7.0]


def test_retry_after_ms(scripted):
    scripted["outcomes"] = [http_error(529, headers={"retry-after-ms": "1500"}), {"ok": 1}]
    post(scripted)
    assert scripted["sleeps"] == [1.5]


def test_openai_insufficient_quota_is_not_retried(scripted):
    body = json.dumps({"error": {"code": "insufficient_quota", "type": "insufficient_quota"}}).encode()
    scripted["outcomes"] = [http_error(429, body)]
    with pytest.raises(subgen_http.ProviderHTTPError) as excinfo:
        post(scripted)
    assert excinfo.value.status == 429 and scripted["calls"] == 1


def test_gemini_daily_quota_is_not_retried(scripted):
    body = json.dumps({"error": {"status": "RESOURCE_EXHAUSTED", "details": [
        {"violations": [{"quotaId": "GenerateRequestsPerDayPerProject"}]}]}}).encode()
    scripted["outcomes"] = [http_error(429, body)]
    with pytest.raises(subgen_http.ProviderHTTPError):
        post(scripted)
    assert scripted["calls"] == 1


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_client_errors_are_not_retried(scripted, code):
    scripted["outcomes"] = [http_error(code)]
    with pytest.raises(subgen_http.ProviderHTTPError):
        post(scripted)
    assert scripted["calls"] == 1


def test_read_timeout_is_retried_only_once(scripted):
    scripted["outcomes"] = [socket.timeout("read"), socket.timeout("read"), {"never": 1}]
    with pytest.raises(RuntimeError, match="timed out"):
        post(scripted)
    assert scripted["calls"] == 2


def test_connection_reset_is_retried(scripted):
    scripted["outcomes"] = [ConnectionResetError("reset"), urllib.error.URLError("refused"), {"ok": 1}]
    assert post(scripted) == {"ok": 1}
    assert scripted["calls"] == 3


def test_attempts_are_bounded(scripted):
    scripted["outcomes"] = [http_error(503)] * 10
    with pytest.raises(subgen_http.ProviderHTTPError):
        post(scripted, max_attempts=4)
    assert scripted["calls"] == 4
    assert all(delay <= subgen_http.MAX_BACKOFF_SECONDS for delay in scripted["sleeps"])


def test_gemini_retry_delay_is_used(scripted):
    body = json.dumps({"error": {"details": [{"retryDelay": "12s"}]}}).encode()
    scripted["outcomes"] = [http_error(429, body), {"ok": 1}]
    post(scripted)
    assert 12 <= scripted["sleeps"][0] <= 14


def test_openai_audio_upload_now_retries(monkeypatch, scripted):
    import subgen_pipeline
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-000")
    monkeypatch.setattr(subgen_http.time, "sleep", lambda s: None)
    monkeypatch.setattr(subgen_http, "backoff_delay", lambda attempt, base=2.0: 0)
    scripted["outcomes"] = [http_error(429), {"text": "hi"}]
    assert subgen_pipeline.post_openai_multipart("https://x", {"model": "m"}, {}) == {"text": "hi"}

"""Security regression tests for the local HTTP server (web/server.py).

Covers review tasks SEC-1 (path traversal, HEAD auth bypass) and SEC-2
(DNS rebinding Host check, CSRF Origin/Content-Type checks).
"""

import http.client
import json
import threading
from pathlib import Path

import pytest

import server


@pytest.fixture()
def local_server():
    httpd = server.SubGenThreadingServer(("127.0.0.1", 0), server.SubGenRequestHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    previous = dict(server.mobile_access)
    try:
        yield httpd.server_address[1]
    finally:
        server.mobile_access.clear()
        server.mobile_access.update(previous)
        httpd.shutdown()
        httpd.server_close()


def request(port, method, path, headers=None, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        # skip_host lets a test send its own Host header (or none).
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        all_headers = {"Host": f"127.0.0.1:{port}"}
        all_headers.update(headers or {})
        for key, value in all_headers.items():
            if value is not None:
                conn.putheader(key, value)
        if body is not None:
            conn.putheader("Content-Length", str(len(body)))
        conn.endheaders()
        if body is not None:
            conn.send(body)
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


def traversal_target():
    """A file that certainly exists, addressed relative to the drive/filesystem root."""
    target = Path(server.__file__).resolve()
    relative = target.relative_to(target.anchor).as_posix()
    return target, relative


# --- SEC-1 -----------------------------------------------------------------

@pytest.mark.parametrize("prefix", ["/api/../", "/api/..%2F", "/api/x/../../"])
def test_api_path_traversal_does_not_serve_files(local_server, prefix):
    target, relative = traversal_target()
    status, body = request(local_server, "GET", prefix + relative)
    assert status == 404
    assert target.read_bytes()[:200] not in body


def test_unknown_api_route_returns_json_404(local_server):
    status, body = request(local_server, "GET", "/api/definitely-not-a-route")
    assert status == 404
    assert json.loads(body)["error"]


def test_static_files_still_served(local_server):
    status, body = request(local_server, "GET", "/")
    assert status == 200
    assert b"<html" in body.lower()


def test_head_requires_authorization_for_remote_clients(local_server, monkeypatch):
    monkeypatch.setitem(server.mobile_access, "enabled", True)
    monkeypatch.setitem(server.mobile_access, "token", "secret-token")
    monkeypatch.setattr(server.SubGenRequestHandler, "client_is_local", lambda self: False)
    _, relative = traversal_target()
    status, _ = request(local_server, "HEAD", "/api/../" + relative)
    assert status == 401


def test_head_on_api_is_not_allowed(local_server):
    status, _ = request(local_server, "HEAD", "/api/health")
    assert status == 405


def test_head_on_static_file_works_locally(local_server):
    status, _ = request(local_server, "HEAD", "/")
    assert status == 200


# --- SEC-2 -----------------------------------------------------------------

@pytest.mark.parametrize("host", ["evil.example:8765", "attacker.test", "127.0.0.1.nip.io:8080"])
def test_rebinding_host_is_rejected(local_server, host):
    status, _ = request(local_server, "GET", "/api/session", headers={"Host": host})
    assert status == 403


@pytest.mark.parametrize("host", ["localhost:{port}", "127.0.0.1:{port}", "[::1]:{port}", "192.168.1.20:{port}"])
def test_ip_and_localhost_hosts_are_accepted(local_server, host):
    status, _ = request(local_server, "GET", "/api/session", headers={"Host": host.format(port=local_server)})
    assert status == 200


def test_missing_host_is_rejected(local_server):
    status, _ = request(local_server, "GET", "/api/session", headers={"Host": None})
    assert status == 403


def test_cross_site_post_from_local_browser_is_rejected(local_server):
    status, _ = request(
        local_server, "POST", "/api/config/update-output-dir",
        headers={"Origin": "https://evil.example", "Content-Type": "application/json"},
        body=b'{"output_dir": "C:/x"}',
    )
    assert status == 403


def test_sec_fetch_site_cross_site_is_rejected(local_server):
    status, _ = request(
        local_server, "POST", "/api/mobile/rotate",
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert status == 403


def test_text_plain_post_body_is_rejected(local_server):
    status, _ = request(
        local_server, "POST", "/api/config/update-output-dir",
        headers={"Content-Type": "text/plain"},
        body=b'{"output_dir": "C:/x"}',
    )
    assert status == 415


def test_same_origin_json_post_passes_the_guards(local_server):
    status, _ = request(
        local_server, "POST", "/api/editor/validate",
        headers={"Origin": f"http://127.0.0.1:{local_server}", "Content-Type": "application/json"},
        body=b'{"segments": []}',
    )
    assert status not in (403, 415)

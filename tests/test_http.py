import json
import socket
import threading
import urllib.error
import urllib.request

from hermes_call_me.config import load_settings
from hermes_call_me.server import Handler, _Server
from tests.conftest import configure


def _free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_health_demo_page_and_webhook_auth(monkeypatch):
    port = _free_port()
    configure(monkeypatch, HERMES_CALL_ME_PORT=str(port))
    httpd = _Server(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
            body = json.loads(response.read().decode())
        assert body["plugin"] == "hermes-call-me"

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/demo", timeout=2) as response:
            page = response.read().decode()
            cookie = response.headers.get("Set-Cookie", "")
        assert "Hermes Call Me" in page
        assert "test-vapi-key" not in page
        assert "test-webhook-secret" not in page
        assert "hermes_call_me_demo=" in cookie

        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/vapi/webhook",
            data=b'{"message":{"type":"status-update","status":"queued"}}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=2)
            raise AssertionError("webhook without a secret should fail")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401

        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/vapi/webhook",
            data=b'{"message":{"type":"status-update","status":"queued"}}',
            headers={
                "Content-Type": "application/json",
                "X-Vapi-Secret": load_settings().webhook_secret,
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            assert response.status == 200
    finally:
        httpd.shutdown()

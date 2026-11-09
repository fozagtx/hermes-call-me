"""Local webhook and demo page. Binds to 127.0.0.1 only.

Vapi reaches it through a tunnel. The demo page sets a cookie only when the
browser's Host is localhost, so a public tunnel cannot start calls.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import ConfigError, load_settings, scrub
from .vapi import VapiError
from .webhook import handle_body

logger = logging.getLogger("hermes_call_me")

_lock = threading.Lock()
_httpd: ThreadingHTTPServer | None = None
_MAX_BODY = 1_000_000
_DEMO_HTML = (Path(__file__).parent / "demo.html").read_text(encoding="utf-8")


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _token_ok(provided: str, expected: str) -> bool:
    if not provided or not expected:
        return False
    left = hashlib.sha256(provided.encode("utf-8")).digest()
    right = hashlib.sha256(expected.encode("utf-8")).digest()
    return hmac.compare_digest(left, right)


def _bearer(header: str) -> str:
    value = header.strip()
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return ""


def _cookie(header: str) -> str:
    for part in header.split(";"):
        name, _, value = part.strip().partition("=")
        if name == "hermes_call_me_demo":
            return urllib.parse.unquote(value)
    return ""


def _local_host(host_header: str) -> bool:
    host = host_header.split(",")[0].strip()
    name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    name = name.strip("[]").lower()
    return name in {"localhost", "127.0.0.1", "::1"}


def _health(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.4) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return False
    return isinstance(body, dict) and body.get("plugin") == "hermes-call-me"


def ensure_server(settings) -> None:
    """Start the webhook in a daemon thread if this process is not already serving it."""
    global _httpd
    if _health(settings.webhook_port):
        return
    with _lock:
        if _health(settings.webhook_port):
            return
        try:
            httpd = _Server(("127.0.0.1", settings.webhook_port), Handler)
        except OSError as exc:
            raise ConfigError(
                f"Could not listen on 127.0.0.1:{settings.webhook_port} ({exc}). "
                "If a tunnel or an older demo is using it, keep that process. "
                "Otherwise set HERMES_CALL_ME_PORT to a free port."
            ) from exc
        thread = threading.Thread(target=httpd.serve_forever, name="hermes-call-me", daemon=True)
        thread.start()
        _httpd = httpd
    for _ in range(50):
        if _health(settings.webhook_port):
            return
        time.sleep(0.05)
    raise ConfigError(
        f"The webhook server did not answer on 127.0.0.1:{settings.webhook_port}."
    )


def serve_forever(settings) -> None:
    if _health(settings.webhook_port):
        raise ConfigError(
            f"hermes-call-me is already listening on 127.0.0.1:{settings.webhook_port}."
        )
    httpd = _Server(("127.0.0.1", settings.webhook_port), Handler)
    logger.info("Listening on http://127.0.0.1:%s", settings.webhook_port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


def _mask_number(number: str) -> str:
    if len(number) < 6:
        return ""
    return number[:4] + "•" * (len(number) - 6) + number[-2:]


def _public_config(settings) -> dict:
    pin = "".join(ch for ch in settings.owner_pin if ch.isdigit())
    pin_ok = pin == settings.owner_pin and 4 <= len(pin) <= 12
    return {
        "ok": True,
        "vapi_configured": bool(settings.vapi_api_key),
        "pin_configured": pin_ok,
        "webhook_configured": settings.webhook_public_url.lower().startswith("https://"),
        "webhook_public_url_set": bool(settings.webhook_public_url),
        "phone_calls_enabled": settings.phone_calls_enabled,
        "owner_number_masked": _mask_number(settings.owner_number),
        "phone_number_configured": bool(settings.vapi_phone_number_id),
        "default_channel": settings.default_channel,
        "phone_provider": settings.phone_provider,
        "calle_region": settings.calle_region,
        "calle_configured": bool(settings.calle_api_key),
        "timeout_seconds": settings.call_timeout_seconds,
        "daily_call_cap": settings.daily_call_cap,
        "quiet_hours_enabled": settings.quiet_hours_enabled,
        "quiet_hours": settings.quiet_hours,
        "timezone": settings.owner_timezone,
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        logger.info("http " + fmt, *args)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path == "/health":
            self._json(200, {"ok": True, "plugin": "hermes-call-me"})
            return
        if path == "/demo":
            self._demo_page()
            return
        if not self._demo_authorized():
            self._json(401, {"ok": False, "error": "Open http://127.0.0.1:%s/demo on this machine." % self.server.server_address[1]})
            return
        if path == "/demo/config":
            self._config()
            return
        if path == "/demo/active":
            self._active()
            return
        if path.startswith("/demo/calls/"):
            self._call(path.removeprefix("/demo/calls/"))
            return
        self._json(404, {"ok": False, "error": "Not found."})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        length = int(self.headers.get("Content-Length") or "0")
        if length < 0 or length > _MAX_BODY:
            self._json(413, {"ok": False, "error": "Body too large."})
            return
        raw = self.rfile.read(length) if length else b""
        if path == "/vapi/webhook":
            self._webhook(raw, urllib.parse.parse_qs(parsed.query))
            return
        if not self._demo_authorized():
            self._json(401, {"ok": False, "error": "Open the demo page on localhost. A tunnel cannot start calls."})
            return
        if path == "/demo/start":
            self._start(raw)
            return
        if path.startswith("/demo/calls/") and path.endswith("/hangup"):
            call_id = path.removeprefix("/demo/calls/").removesuffix("/hangup").strip("/")
            self._hangup(call_id)
            return
        self._json(404, {"ok": False, "error": "Not found."})

    def _demo_page(self) -> None:
        body = _DEMO_HTML.encode("utf-8")
        header = {
            "Content-Type": "text/html; charset=utf-8",
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
        }
        try:
            settings = load_settings()
        except ConfigError:
            settings = None
        if settings and settings.webhook_secret and _local_host(self.headers.get("Host", "")):
            cookie = urllib.parse.quote(settings.webhook_secret, safe="")
            header["Set-Cookie"] = (
                f"hermes_call_me_demo={cookie}; HttpOnly; SameSite=Strict; Path=/"
            )
        self._send(200, body, header)

    def _demo_authorized(self) -> bool:
        try:
            settings = load_settings()
        except ConfigError:
            return False
        # Until a secret exists there is nothing to forge, and start still
        # refuses to call Vapi. Once a secret is set, localhost gets it as a
        # cookie and a public tunnel does not.
        if not settings.webhook_secret:
            return True
        provided = _bearer(self.headers.get("Authorization", "")) or _cookie(self.headers.get("Cookie", ""))
        x_vapi = self.headers.get("X-Vapi-Secret", "")
        return _token_ok(provided, settings.webhook_secret) or _token_ok(x_vapi, settings.webhook_secret)

    def _webhook_authorized(self, settings) -> bool:
        if not settings.webhook_secret:
            return False
        provided = _bearer(self.headers.get("Authorization", ""))
        x_vapi = self.headers.get("X-Vapi-Secret", "")
        return _token_ok(provided, settings.webhook_secret) or _token_ok(x_vapi, settings.webhook_secret)

    def _webhook(self, raw: bytes, query: dict) -> None:
        try:
            settings = load_settings()
        except ConfigError as exc:
            self._json(500, {"ok": False, "error": str(exc)})
            return
        if not self._webhook_authorized(settings):
            self._json(401, {"ok": False, "error": "Webhook secret did not match."})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "Webhook body was not JSON."})
            return
        if not isinstance(body, dict):
            self._json(400, {"ok": False, "error": "Webhook body must be a JSON object."})
            return
        ids = query.get("hermes_call_id") or [""]
        try:
            status, payload = handle_body(body, settings=settings, query_call_id=ids[0])
        except Exception as exc:
            logger.exception("webhook failed")
            self._json(500, {"ok": False, "error": scrub(str(exc), settings)[:500]})
            return
        self._json(status, payload)

    def _config(self) -> None:
        try:
            settings = load_settings()
        except ConfigError as exc:
            self._json(500, {"ok": False, "error": str(exc)})
            return
        self._json(200, _public_config(settings))

    def _active(self) -> None:
        from . import store

        row = store.active_call()
        if row is None:
            self._json(200, {"ok": True, "call": None})
            return
        self._json(200, {"ok": True, "call": _demo_call(row)})

    def _call(self, call_id: str) -> None:
        from . import store

        row = store.get_call(call_id)
        if row is None:
            self._json(404, {"ok": False, "error": "No such call."})
            return
        self._json(200, {"ok": True, "call": _demo_call(row)})

    def _start(self, raw: bytes) -> None:
        from .service import start_from_demo

        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "Body was not JSON."})
            return
        if not isinstance(payload, dict):
            self._json(400, {"ok": False, "error": "Body must be a JSON object."})
            return
        try:
            result = start_from_demo(payload)
        except (ConfigError, VapiError) as exc:
            self._json(400, {"ok": False, "error": scrub(str(exc))[:800]})
            return
        except Exception as exc:
            logger.exception("demo start failed")
            self._json(500, {"ok": False, "error": scrub(str(exc))[:800]})
            return
        self._json(200, result)

    def _hangup(self, call_id: str) -> None:
        from .service import hangup

        try:
            result = hangup(call_id)
        except (ConfigError, VapiError) as exc:
            self._json(400, {"ok": False, "error": scrub(str(exc))[:800]})
            return
        self._json(200, result)

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self._send(
            status,
            body,
            {
                "Content-Type": "application/json; charset=utf-8",
                "Content-Length": str(len(body)),
                "Cache-Control": "no-store",
            },
        )

    def _send(self, status: int, body: bytes, headers: dict) -> None:
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


def _demo_call(row: dict) -> dict:
    structured = None
    if row.get("structured_json"):
        try:
            structured = json.loads(row["structured_json"])
        except json.JSONDecodeError:
            structured = None
    return {
        "id": row["id"],
        "vapi_call_id": row.get("vapi_call_id"),
        "purpose": row.get("purpose"),
        "channel": row.get("channel"),
        "status": row.get("status"),
        "reason": row.get("reason"),
        "decision": row.get("decision"),
        "pin_verified": bool(row.get("pin_verified")),
        "instructions": row.get("tool_instructions"),
        "reply": row.get("tool_reply"),
        "transcript": row.get("transcript"),
        "cost_usd": row.get("cost_usd"),
        "duration_seconds": row.get("duration_seconds"),
        "ended_reason": row.get("ended_reason"),
        "join_url": row.get("join_url"),
        "error": row.get("error"),
        "structured": structured,
        "created_at": row.get("created_at"),
    }

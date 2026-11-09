"""Real Vapi REST calls. There is no fake transport.

``perform_http`` is the only function that touches the network. Tests replace
that function. Runtime code calls it.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .config import Settings, scrub

API = "https://api.vapi.ai"


class VapiError(Exception):
    """Vapi returned an error, or the request never left the machine."""


def perform_http(method: str, url: str, api_key: str, body: dict | None, timeout: float = 30) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {api_key}")
    request.add_header("Accept", "application/json")
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw else {}
            if not isinstance(parsed, dict):
                raise VapiError(f"Vapi {method} {url} returned JSON that was not an object.")
            return response.status, parsed
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise VapiError(f"Vapi {method} {url} failed ({exc.code}): {scrub(detail)}") from exc
    except urllib.error.URLError as exc:
        raise VapiError(f"Vapi {method} {url} could not connect: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise VapiError(f"Vapi {method} {url} returned invalid JSON.") from exc


def create_call(payload: dict, settings: Settings, *, http=perform_http) -> dict:
    if not settings.vapi_api_key:
        raise VapiError("VAPI_API_KEY is not set. No call was placed.")
    _status, body = http("POST", f"{API}/call", settings.vapi_api_key, payload)
    return body


def get_call(vapi_call_id: str, settings: Settings, *, http=perform_http) -> dict:
    _status, body = http("GET", f"{API}/call/{vapi_call_id}", settings.vapi_api_key, None)
    return body


def end_call(vapi_call_id: str, control_url: str | None, settings: Settings, *, http=perform_http) -> None:
    """Ask Vapi to hang up. Used when our wait hits the configured timeout."""
    message = {"type": "end-call"}
    if control_url:
        http("POST", control_url, settings.vapi_api_key, message, 15)
        return
    http("POST", f"{API}/call/{vapi_call_id}/control", settings.vapi_api_key, message, 15)


def configure_phone_number(settings: Settings, *, http=perform_http) -> dict:
    """Point an imported Vapi number at our webhook so inbound calls ask us for an assistant."""
    if not settings.vapi_api_key or not settings.vapi_phone_number_id:
        raise VapiError(
            "configure-number needs VAPI_API_KEY and VAPI_PHONE_NUMBER_ID. Nothing was changed."
        )
    from .config import webhook_endpoint

    payload = {
        "assistantId": None,
        "server": {
            "url": webhook_endpoint(settings.webhook_public_url),
            "timeoutSeconds": 7,
            "headers": {
                "Authorization": f"Bearer {settings.webhook_secret}",
                "X-Vapi-Secret": settings.webhook_secret,
            },
        },
    }
    _status, body = http(
        "PATCH",
        f"{API}/phone-number/{settings.vapi_phone_number_id}",
        settings.vapi_api_key,
        payload,
    )
    return body


def join_url(call: dict) -> str | None:
    direct = call.get("webCallUrl")
    if isinstance(direct, str) and direct:
        return direct
    transport = call.get("transport") or {}
    if isinstance(transport, dict):
        for key in ("callUrl", "websocketCallUrl"):
            value = transport.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def control_url(call: dict) -> str | None:
    monitor = call.get("monitor") or {}
    if isinstance(monitor, dict):
        value = monitor.get("controlUrl")
        if isinstance(value, str) and value:
            return value
    return None


def as_cost(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        total = value.get("total")
        if isinstance(total, (int, float)) and not isinstance(total, bool):
            return float(total)
    return None


def as_duration(message: dict, call: dict) -> float | None:
    for source in (message, call):
        seconds = source.get("durationSeconds")
        if isinstance(seconds, (int, float)) and not isinstance(seconds, bool):
            return float(seconds)
        millis = source.get("durationMs")
        if isinstance(millis, (int, float)) and not isinstance(millis, bool):
            return float(millis) / 1000.0
    return None

"""CALL-E Developer API. One-shot calls only. No stand-in responses.

Follows https://docs.heycall-e.com/calls: ``POST /v2/calls`` accepts one
E.164 number, a task, and a result schema, and returns 202. ``GET
/v2/calls/{id}`` is polled every two seconds while ``result_status`` is
``pending``. A create whose acceptance is uncertain is retried with the same
body and the same ``Idempotency-Key``, which never dials twice. Tests replace
``perform_http``. Runtime uses urllib.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from .config import DEFAULT_BASE_URL, Settings, scrub

CREATE_ATTEMPTS = 4


class CalleError(Exception):
    """CALL-E rejected the request, or the call never finished in time."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        reason_code: str | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.code = code
        self.reason_code = reason_code


def perform_http(
    method: str,
    url: str,
    api_key: str,
    body: dict | None,
    extra_headers: dict | None = None,
    timeout: float = 45,
) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {api_key}")
    request.add_header("Accept", "application/json")
    if body is not None:
        request.add_header("Content-Type", "application/json")
    for name, value in (extra_headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw else {}
            if not isinstance(parsed, dict):
                raise CalleError(f"CALL-E {method} {url} returned JSON that was not an object.")
            return response.status, parsed
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        message, code, reason_code = _error_text(detail, exc.code, method, url)
        raise CalleError(scrub(message), status=exc.code, code=code, reason_code=reason_code) from exc
    except urllib.error.URLError as exc:
        raise CalleError(f"CALL-E {method} {url} could not connect: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise CalleError(f"CALL-E {method} {url} returned invalid JSON.") from exc
    except (TimeoutError, OSError) as exc:
        raise CalleError(f"CALL-E {method} {url} did not respond: {exc}") from exc


def _error_text(detail: str, status: int, method: str, url: str) -> tuple[str, str | None, str | None]:
    code = None
    reason_code = None
    message = detail.strip()
    try:
        parsed = json.loads(detail) if detail else {}
    except json.JSONDecodeError:
        parsed = {}
    if isinstance(parsed, dict):
        error = parsed.get("error") if isinstance(parsed.get("error"), dict) else parsed
        if isinstance(error, dict):
            code = error.get("code") if isinstance(error.get("code"), str) else None
            text = error.get("message") if isinstance(error.get("message"), str) else ""
            details = error.get("details") if isinstance(error.get("details"), dict) else {}
            missing = details.get("missing_inputs")
            if isinstance(details.get("reason_code"), str):
                reason_code = details["reason_code"]
            if text:
                message = text
            if isinstance(missing, list) and missing:
                message = message + " Missing: " + "; ".join(str(item) for item in missing)
    if not message:
        message = f"HTTP {status}"
    return f"CALL-E {method} {url} failed ({status}{', ' + code if code else ''}): {message}", code, reason_code


def base_url(settings: Settings) -> str:
    return (settings.calle_base_url or DEFAULT_BASE_URL).rstrip("/")


def _uncertain(exc: CalleError) -> bool:
    """True when acceptance is unknown and the same request may be replayed."""
    if exc.status == 409:
        return exc.reason_code == "creation_in_progress"
    return exc.status is None or exc.status >= 500


def create_call(
    body: dict,
    settings: Settings,
    *,
    idempotency_key: str,
    http=None,
    sleep=None,
) -> dict:
    """Create one Call. Replays the unchanged body and key when acceptance is uncertain."""
    http = http or perform_http
    sleep = sleep or time.sleep
    if not settings.calle_api_key:
        raise CalleError(
            "CALLE_API_KEY is not set. No call was placed. "
            "Create a key in the CALL-E dashboard and export it."
        )
    if not idempotency_key or len(idempotency_key) > 255:
        raise CalleError("Idempotency-Key must be 1 to 255 characters. No call was placed.")
    for attempt in range(1, CREATE_ATTEMPTS + 1):
        try:
            _status, payload = http(
                "POST",
                f"{base_url(settings)}/v2/calls",
                settings.calle_api_key,
                body,
                {"Idempotency-Key": idempotency_key},
                45,
            )
            return payload
        except CalleError as exc:
            if attempt == CREATE_ATTEMPTS or not _uncertain(exc):
                raise
            sleep(2 * attempt)
    raise CalleError("CALL-E create did not complete. No new call was placed.")


def get_call(call_id: str, settings: Settings, *, http=None) -> dict:
    http = http or perform_http
    _status, payload = http(
        "GET",
        f"{base_url(settings)}/v2/calls/{call_id}",
        settings.calle_api_key,
        None,
        None,
        30,
    )
    return payload


def cancel_call(call_id: str, settings: Settings, *, http=None) -> None:
    http = http or perform_http
    """Cancel only if CALL-E has not submitted the call yet. A 409 is expected after dialing."""
    try:
        http(
            "POST",
            f"{base_url(settings)}/v2/calls/{call_id}/cancel",
            settings.calle_api_key,
            {},
            None,
            20,
        )
    except CalleError as exc:
        if exc.status == 409:
            return
        raise


def wait_for_result(
    call_id: str,
    settings: Settings,
    *,
    timeout_seconds: int,
    http=None,
    sleep=None,
    monotonic=None,
) -> dict:
    http = http or perform_http
    sleep = sleep or time.sleep
    monotonic = monotonic or time.monotonic
    """Poll until the business result is no longer pending. A timeout does not redial."""
    deadline = monotonic() + timeout_seconds
    last: dict = {}
    while monotonic() < deadline:
        last = get_call(call_id, settings, http=http)
        if str(last.get("result_status") or "") != "pending":
            return last
        sleep(2)
    raise CalleError(
        f"CALL-E call {call_id} was still pending after {timeout_seconds}s. "
        "It was not dialed again. Check the CALL-E dashboard before placing another call."
    )

"""Settings from the environment, Hermes secret storage, and plugin config.

Nothing here talks to Vapi. Missing secrets stay blank until a call site
validates them and raises ``ConfigError`` with the name of the variable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .context import get_context


class ConfigError(Exception):
    """The plugin is missing a value it needs for this operation."""


def _secret(name: str) -> str:
    """Read a secret through Hermes when running inside it.

    Inside Hermes, only ``agent.secret_scope.get_secret`` is used, so the
    active profile's value wins and another profile's key is never picked up
    from the process environment. The process environment is read only by the
    standalone ``python -m hermes_call_me`` server, where Hermes is absent.
    """
    try:
        from agent.secret_scope import get_secret
    except ImportError:
        return os.environ.get(name, "").strip()
    try:
        found = get_secret(name)
    except Exception:
        return ""
    if found is None:
        return ""
    return str(found).strip()


def _plugin_value(key: str, default):
    ctx = get_context()
    if ctx is None:
        return default
    getter = getattr(ctx, "get_config", None)
    if getter is None:
        return default
    try:
        value = getter(key, default=default)
    except TypeError:
        try:
            value = getter(key)
        except Exception:
            return default
    except Exception:
        return default
    if value is None or value == "":
        return default
    return value


def _first(env_name: str, config_key: str, default):
    env = os.environ.get(env_name)
    if env is not None and env.strip() != "":
        return env.strip()
    return _plugin_value(config_key, default)


def _bool(value, default: bool, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be true or false, got {value!r}.")


def _int(value, default: int, name: str) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be an integer, got {value!r}.") from exc


def _patterns(value) -> tuple[str, ...]:
    if value is None or value == "" or value == []:
        return ()
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
        return tuple(part for part in parts if part)
    if isinstance(value, (list, tuple)):
        return tuple(str(part).strip() for part in value if str(part).strip())
    raise ConfigError(
        "risky_tool_patterns must be a list of regular expressions "
        f"or a comma-separated string, got {value!r}."
    )


@dataclass(frozen=True)
class Settings:
    vapi_api_key: str
    owner_pin: str
    webhook_secret: str
    webhook_public_url: str
    owner_number: str
    vapi_phone_number_id: str
    call_timeout_seconds: int
    daily_call_cap: int
    quiet_hours: str
    quiet_hours_enabled: bool
    owner_timezone: str
    guard_enabled: bool
    risky_tool_patterns: tuple[str, ...]
    approval_ttl_seconds: int
    webhook_port: int
    vapi_model: str
    voice_provider: str
    voice_id: str
    default_channel: str
    phone_calls_enabled: bool
    gateway_session_key: str
    phone_provider: str
    calle_api_key: str
    calle_base_url: str
    calle_region: str
    calle_locale: str


def load_settings() -> Settings:
    """Read settings. Raises ``ConfigError`` only when a present value is illegal."""
    channel = str(_first("HERMES_CALL_ME_CHANNEL", "default_channel", "web")).strip().lower()
    if channel not in {"web", "phone"}:
        raise ConfigError(
            "HERMES_CALL_ME_CHANNEL must be 'web' or 'phone', "
            f"got {channel!r}."
        )
    timeout = _int(
        _first("HERMES_CALL_ME_TIMEOUT_SECONDS", "call_timeout_seconds", 180),
        180,
        "HERMES_CALL_ME_TIMEOUT_SECONDS",
    )
    if timeout < 30 or timeout > 600:
        raise ConfigError(
            "HERMES_CALL_ME_TIMEOUT_SECONDS must be between 30 and 600 "
            f"(about 3 minutes is the default). Got {timeout}."
        )
    cap = _int(
        _first("HERMES_CALL_ME_DAILY_CAP", "daily_call_cap", 8),
        8,
        "HERMES_CALL_ME_DAILY_CAP",
    )
    if cap < 0:
        raise ConfigError("HERMES_CALL_ME_DAILY_CAP cannot be negative.")
    port = _int(
        _first("HERMES_CALL_ME_PORT", "webhook_port", 8787),
        8787,
        "HERMES_CALL_ME_PORT",
    )
    if port < 0 or port > 65535:
        raise ConfigError(f"HERMES_CALL_ME_PORT is not a TCP port: {port}.")
    ttl = _int(
        _first("HERMES_CALL_ME_APPROVAL_TTL_SECONDS", "approval_ttl_seconds", 600),
        600,
        "HERMES_CALL_ME_APPROVAL_TTL_SECONDS",
    )
    if ttl < 30:
        raise ConfigError("HERMES_CALL_ME_APPROVAL_TTL_SECONDS must be at least 30.")
    return Settings(
        vapi_api_key=_secret("VAPI_API_KEY"),
        owner_pin=_secret("HERMES_CALL_ME_PIN"),
        webhook_secret=_secret("HERMES_CALL_ME_WEBHOOK_SECRET"),
        webhook_public_url=str(
            _first("HERMES_CALL_ME_WEBHOOK_URL", "webhook_public_url", "")
        ).strip(),
        owner_number=str(
            _first("HERMES_CALL_ME_OWNER_NUMBER", "owner_number", "")
        ).strip(),
        vapi_phone_number_id=str(
            _first("VAPI_PHONE_NUMBER_ID", "vapi_phone_number_id", "")
        ).strip(),
        call_timeout_seconds=timeout,
        daily_call_cap=cap,
        quiet_hours=str(_first("HERMES_CALL_ME_QUIET_HOURS", "quiet_hours", "22:00-07:00")).strip(),
        quiet_hours_enabled=_bool(
            _first("HERMES_CALL_ME_QUIET_HOURS_ENABLED", "quiet_hours_enabled", False),
            False,
            "HERMES_CALL_ME_QUIET_HOURS_ENABLED",
        ),
        owner_timezone=str(
            _first("HERMES_CALL_ME_TIMEZONE", "owner_timezone", "America/New_York")
        ).strip()
        or "America/New_York",
        guard_enabled=_bool(
            _first("HERMES_CALL_ME_GUARD", "guard_enabled", False),
            False,
            "HERMES_CALL_ME_GUARD",
        ),
        risky_tool_patterns=_patterns(
            _first("HERMES_CALL_ME_RISKY_TOOLS", "risky_tool_patterns", "")
        ),
        approval_ttl_seconds=ttl,
        webhook_port=port,
        vapi_model=str(_first("HERMES_CALL_ME_MODEL", "vapi_model", "gpt-4o-mini")).strip()
        or "gpt-4o-mini",
        voice_provider=str(
            _first("HERMES_CALL_ME_VOICE_PROVIDER", "voice_provider", "vapi")
        ).strip()
        or "vapi",
        voice_id=str(_first("HERMES_CALL_ME_VOICE_ID", "voice_id", "Elliot")).strip()
        or "Elliot",
        default_channel=channel,
        phone_calls_enabled=_bool(
            _first("HERMES_CALL_ME_PHONE_CALLS", "phone_calls_enabled", False),
            False,
            "HERMES_CALL_ME_PHONE_CALLS",
        ),
        gateway_session_key=str(
            _first("HERMES_CALL_ME_GATEWAY_SESSION_KEY", "gateway_session_key", "")
        ).strip(),
        phone_provider=_phone_provider(),
        calle_api_key=_secret("CALLE_API_KEY"),
        calle_base_url=_calle_base_url(),
        calle_region=_region(),
        calle_locale=str(_first("HERMES_CALL_ME_LOCALE", "calle_locale", "en-US")).strip() or "en-US",
    )


def _phone_provider() -> str:
    provider = str(_first("HERMES_CALL_ME_PROVIDER", "phone_provider", "calle")).strip().lower()
    if provider not in {"calle", "vapi"}:
        raise ConfigError(
            "HERMES_CALL_ME_PROVIDER must be calle or vapi, "
            f"got {provider!r}. calle places the real phone call. "
            "vapi remains the browser demo."
        )
    return provider


def _region() -> str:
    region = str(_first("HERMES_CALL_ME_REGION", "calle_region", "US")).strip().upper()
    if len(region) != 2 or not region.isalpha():
        raise ConfigError(
            "HERMES_CALL_ME_REGION must be a two-letter country code from "
            f"https://docs.heycall-e.com/regions, got {region!r}. Default is US."
        )
    return region


def _calle_base_url() -> str:
    url = str(_first("CALLE_BASE_URL", "calle_base_url", "https://api.heycall-e.com")).strip()
    if not url.lower().startswith("https://"):
        raise ConfigError(f"CALLE_BASE_URL must be an https URL, got {url!r}.")
    return url.rstrip("/")


def webhook_endpoint(public_url: str) -> str:
    base = public_url.strip().rstrip("/")
    if base.endswith("/vapi/webhook"):
        return base
    return base + "/vapi/webhook"


def _require_pin(settings: Settings) -> None:
    if not settings.owner_pin:
        raise ConfigError("Set HERMES_CALL_ME_PIN. No call was placed.")
    digits = "".join(ch for ch in settings.owner_pin if ch.isdigit())
    if digits != settings.owner_pin or not (4 <= len(digits) <= 12):
        raise ConfigError(
            "HERMES_CALL_ME_PIN must be 4 to 12 digits. The call asks the owner "
            "to say it, and this server compares the digits. A missing or "
            "non-numeric PIN would make the gate meaningless, so the call is refused."
        )


def _require_webhook(settings: Settings) -> None:
    if not settings.webhook_secret:
        raise ConfigError("Set HERMES_CALL_ME_WEBHOOK_SECRET. No call was placed.")
    if not settings.webhook_public_url:
        raise ConfigError(
            "Set HERMES_CALL_ME_WEBHOOK_URL to the public https origin of this "
            "server, from an https tunnel (see the README). No call was placed."
        )
    if not settings.webhook_public_url.lower().startswith("https://"):
        raise ConfigError(
            "HERMES_CALL_ME_WEBHOOK_URL must be a public https URL. "
            f"Got {settings.webhook_public_url!r}. Vapi's cloud cannot reach "
            "localhost, so the browser PIN check would never run."
        )


def require_call_config(settings: Settings, channel: str) -> None:
    """Fail loudly before any call is created."""
    _require_pin(settings)
    if channel == "web":
        if not settings.vapi_api_key:
            raise ConfigError(
                "VAPI_API_KEY is not set. The browser demo needs a private Vapi key. "
                "No call was placed."
            )
        _require_webhook(settings)
        return
    if channel != "phone":
        raise ConfigError(f"channel must be 'web' or 'phone', got {channel!r}.")
    if not settings.phone_calls_enabled:
        raise ConfigError(
            "Phone calls are off, so this did not dial anyone. The browser demo "
            "uses channel web. For a real call, set HERMES_CALL_ME_PHONE_CALLS=1 "
            "and HERMES_CALL_ME_OWNER_NUMBER, then turn phone calls off again."
        )
    if not _e164(settings.owner_number):
        raise ConfigError(
            "HERMES_CALL_ME_OWNER_NUMBER must be one E.164 number, including + "
            "and the country code, for example +14155550100. "
            "Refusing to dial without a single allowlisted number."
        )
    if settings.phone_provider == "calle":
        if not settings.calle_api_key:
            raise ConfigError(
                "CALLE_API_KEY is not set. No call was placed. "
                "Sign in at https://www.heycall-e.com, create an API key, and export it. "
                "New accounts include 100 free credits (US$1)."
            )
        return
    if not settings.vapi_api_key:
        raise ConfigError("VAPI_API_KEY is not set. No call was placed.")
    if not settings.vapi_phone_number_id:
        raise ConfigError(
            "VAPI_PHONE_NUMBER_ID is not set. The optional Vapi phone path needs "
            "a phoneNumberId. The default phone provider is CALL-E and does not need one."
        )
    _require_webhook(settings)


def _e164(number: str) -> bool:
    if not number.startswith("+"):
        return False
    rest = number[1:]
    return rest.isdigit() and 8 <= len(rest) <= 15 and rest[0] != "0"


def scrub(text: str, settings: Settings | None = None) -> str:
    """Remove secrets from a provider error before it reaches the model or logs."""
    if not text:
        return text
    current = settings or _settings_or_blank()
    for secret in (
        current.vapi_api_key,
        current.webhook_secret,
        current.owner_pin,
        current.calle_api_key,
    ):
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


def _settings_or_blank() -> Settings:
    try:
        return load_settings()
    except ConfigError:
        return Settings(
            vapi_api_key="",
            owner_pin="",
            webhook_secret="",
            webhook_public_url="",
            owner_number="",
            vapi_phone_number_id="",
            call_timeout_seconds=180,
            daily_call_cap=8,
            quiet_hours="22:00-07:00",
            quiet_hours_enabled=False,
            owner_timezone="America/New_York",
            guard_enabled=False,
            risky_tool_patterns=(),
            approval_ttl_seconds=600,
            webhook_port=8787,
            vapi_model="gpt-4o-mini",
            voice_provider="vapi",
            voice_id="Elliot",
            default_channel="web",
            phone_calls_enabled=False,
            gateway_session_key="",
            phone_provider="calle",
            calle_api_key="",
            calle_base_url="https://api.heycall-e.com",
            calle_region="US",
            calle_locale="en-US",
        )

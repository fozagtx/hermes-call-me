"""Settings from Hermes secret storage and plugin config, or the environment outside Hermes.

Nothing here talks to CALL-E. Missing secrets stay blank until a call site
validates them and raises ``ConfigError`` with the name of the variable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .context import get_context

DEFAULT_BASE_URL = "https://api.heycall-e.com"

# Calling codes CALL-E lists at https://docs.heycall-e.com/regions (checked
# 2026-11-10). Country calling codes are prefix-free, so a number belongs to
# at most one of these. +1 covers US and CA (local lines); the rest use
# CALL-E's international pool.
SUPPORTED_CALLING_CODES: dict[str, str] = {
    "+1": "US/CA",
    "+31": "NL",
    "+34": "ES",
    "+44": "GB",
    "+48": "PL",
    "+49": "DE",
    "+52": "MX",
    "+55": "BR",
    "+60": "MY",
    "+61": "AU",
    "+62": "ID",
    "+63": "PH",
    "+65": "SG",
    "+66": "TH",
    "+81": "JP",
    "+84": "VN",
    "+90": "TR",
    "+91": "IN",
    "+92": "PK",
    "+358": "FI",
    "+880": "BD",
}


class ConfigError(Exception):
    """The plugin is missing a value it needs for this operation."""


def _secret(name: str) -> str:
    """Read a secret through Hermes when running inside it.

    Inside Hermes, only ``agent.secret_scope.get_secret`` is used, so the
    active profile's value wins and another profile's key is never picked up
    from the process environment. The process environment is read only when
    Hermes is absent (tests, or ``python -m hermes_call_me``).
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
    """Inside Hermes, read the active profile's plugin config only.

    The process environment is shared by every profile, so it is read only
    when no Hermes context is attached (tests, ``python -m hermes_call_me``).
    """
    if get_context() is not None:
        return _plugin_value(config_key, default)
    env = os.environ.get(env_name)
    if env is not None and env.strip() != "":
        return env.strip()
    return default


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
    calle_api_key: str
    owner_pin: str
    owner_number: str
    calle_base_url: str
    calle_region: str
    calle_locale: str
    call_timeout_seconds: int
    daily_call_cap: int
    quiet_hours: str
    quiet_hours_enabled: bool
    owner_timezone: str
    guard_enabled: bool
    risky_tool_patterns: tuple[str, ...]
    approval_ttl_seconds: int


def load_settings() -> Settings:
    """Read settings. Raises ``ConfigError`` only when a present value is illegal."""
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
    cap = _int(_first("HERMES_CALL_ME_DAILY_CAP", "daily_call_cap", 8), 8, "HERMES_CALL_ME_DAILY_CAP")
    if cap < 0:
        raise ConfigError("HERMES_CALL_ME_DAILY_CAP cannot be negative.")
    ttl = _int(
        _first("HERMES_CALL_ME_APPROVAL_TTL_SECONDS", "approval_ttl_seconds", 600),
        600,
        "HERMES_CALL_ME_APPROVAL_TTL_SECONDS",
    )
    if ttl < 30:
        raise ConfigError("HERMES_CALL_ME_APPROVAL_TTL_SECONDS must be at least 30.")
    return Settings(
        calle_api_key=_secret("CALLE_API_KEY"),
        owner_pin=_secret("HERMES_CALL_ME_PIN"),
        owner_number=str(_first("HERMES_CALL_ME_OWNER_NUMBER", "owner_number", "")).strip(),
        calle_base_url=_calle_base_url(),
        calle_region=_region(),
        calle_locale=str(_first("HERMES_CALL_ME_LOCALE", "calle_locale", "")).strip(),
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
        risky_tool_patterns=_patterns(_first("HERMES_CALL_ME_RISKY_TOOLS", "risky_tool_patterns", "")),
        approval_ttl_seconds=ttl,
    )


def _region() -> str:
    """Blank means CALL-E infers the region from the number (+1 is US)."""
    region = str(_first("HERMES_CALL_ME_REGION", "calle_region", "")).strip().upper()
    if region and (len(region) != 2 or not region.isalpha()):
        raise ConfigError(
            "HERMES_CALL_ME_REGION must be a two-letter country code from "
            f"https://docs.heycall-e.com/regions, or blank to infer it from the number. Got {region!r}."
        )
    return region


def calling_code_country(number: str) -> str | None:
    for code, country in SUPPORTED_CALLING_CODES.items():
        if number.startswith(code):
            return country
    return None


def _calle_base_url() -> str:
    url = str(_first("CALLE_BASE_URL", "calle_base_url", DEFAULT_BASE_URL)).strip()
    if not url.lower().startswith("https://"):
        raise ConfigError(f"CALLE_BASE_URL must be an https URL, got {url!r}.")
    return url.rstrip("/")


def require_call_config(settings: Settings) -> None:
    """Fail loudly before any call is created."""
    if not settings.owner_pin:
        raise ConfigError("Set HERMES_CALL_ME_PIN. No call was placed.")
    digits = "".join(ch for ch in settings.owner_pin if ch.isdigit())
    if digits != settings.owner_pin or not (4 <= len(digits) <= 12):
        raise ConfigError(
            "HERMES_CALL_ME_PIN must be 4 to 12 digits. The call asks the owner "
            "to say it, and this plugin compares the digits. A missing or "
            "non-numeric PIN would make the gate meaningless, so the call is refused."
        )
    if not _e164(settings.owner_number):
        raise ConfigError(
            "HERMES_CALL_ME_OWNER_NUMBER must be one E.164 number, including + "
            "and the country code, for example +14155550100. "
            "Refusing to dial without a single allowlisted number."
        )
    if not settings.calle_region and calling_code_country(settings.owner_number) is None:
        raise ConfigError(
            f"CALL-E does not list the country of {settings.owner_number[:4]}... as a calling region "
            "(https://docs.heycall-e.com/regions). No call was placed. Use a US number that "
            "rings you where you are (see the README section \"Your country isn't listed\"), "
            "or, if CALL-E enabled this country on your account, set the region explicitly."
        )
    if not settings.calle_api_key:
        raise ConfigError(
            "CALLE_API_KEY is not set. No call was placed. "
            "Sign in at https://www.heycall-e.com, create an API key, and add it "
            "to the plugin's settings."
        )


def _e164(number: str) -> bool:
    if not number.startswith("+"):
        return False
    rest = number[1:]
    return rest.isdigit() and 8 <= len(rest) <= 15 and rest[0] != "0"


def scrub(text: str, settings: Settings | None = None) -> str:
    """Remove secrets from a provider error before it reaches the model or logs."""
    if not text:
        return text
    if settings is None:
        try:
            settings = load_settings()
        except ConfigError:
            return text
    for secret in (settings.calle_api_key, settings.owner_pin):
        if secret:
            text = text.replace(secret, "[redacted]")
    return text

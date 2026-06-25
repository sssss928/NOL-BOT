"""Configuration loading and validation for nol-ticket-bot."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

DEFAULT_BASE_URL = "https://world.nol.com"
ENV_FILE_VAR = "NOL_BOT_ENV_FILE"
_CODE_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class SettingsError(ValueError):
    """Raised when environment configuration is invalid."""


def resolve_env_path(env_file: str | os.PathLike[str] | None = None) -> Path | None:
    """Resolve the .env file without depending on the package install path.

    Lookup order:
    1. Explicit ``env_file`` argument.
    2. ``NOL_BOT_ENV_FILE`` environment variable.
    3. ``.env`` in the current working directory.
    4. ``.env`` in the project root for editable/source checkouts.
    5. python-dotenv's cwd-based parent search.
    """

    explicit = env_file or os.getenv(ENV_FILE_VAR)
    if explicit:
        return Path(explicit).expanduser().resolve()

    cwd_env = Path.cwd() / ".env"
    if cwd_env.exists():
        return cwd_env.resolve()

    source_root_env = Path(__file__).resolve().parents[2] / ".env"
    if source_root_env.exists():
        return source_root_env

    discovered = find_dotenv(filename=".env", usecwd=True)
    if discovered:
        return Path(discovered).resolve()

    return None


def _load_dotenv_once(env_file: str | os.PathLike[str] | None = None) -> Path | None:
    path = resolve_env_path(env_file)
    if path and path.exists():
        load_dotenv(path, override=False)
    return path


def _get(env: Mapping[str, str], key: str, default: str) -> str:
    value = env.get(key)
    return default if value is None else value


def _parse_bool(value: str, key: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise SettingsError(f"{key} must be a boolean value")


def _parse_int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = _get(env, key, str(default)).strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise SettingsError(f"{key} must be an integer") from exc


def _parse_float(env: Mapping[str, str], key: str, default: float) -> float:
    raw = _get(env, key, str(default)).strip()
    try:
        return float(raw)
    except ValueError as exc:
        raise SettingsError(f"{key} must be a number") from exc


def _validate_code(name: str, value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise SettingsError(f"{name} is required")
    if len(cleaned) > 64 or not _CODE_RE.fullmatch(cleaned):
        raise SettingsError(f"{name} must contain only letters, numbers, '_' or '-'")
    return cleaned


def _validate_range(
    name: str,
    value: int | float,
    minimum: int | float,
    maximum: int | float,
) -> None:
    if value < minimum or value > maximum:
        raise SettingsError(f"{name} must be between {minimum} and {maximum}")


@dataclass(frozen=True)
class Settings:
    goods_code: str = "26005973"
    place_code: str = "26000437"
    biz_code: str = "10965"
    lang: str = "zh-CN"
    base_url: str = DEFAULT_BASE_URL
    nol_email: str = ""
    nol_password: str = ""
    chromium_path: str = ""
    headless: bool = False
    window_w: int = 1280
    window_h: int = 800
    seat_grade_preference: tuple[str, ...] = ("VIP", "R", "S", "A")
    max_tickets: int = 2
    stop_before_payment: bool = True
    confirm_before_payment: bool = True
    poll_interval: float = 1.5
    queue_poll: float = 2.0
    queue_timeout: int = 600
    page_wait_timeout: int = 30
    salesinfo_timeout: float = 5.0
    salesinfo_retries: int = 3
    salesinfo_backoff: float = 0.5
    salesinfo_jitter: float = 0.2
    salesinfo_rate_limit: float = 0.25

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        source = os.environ if env is None else env
        grades = tuple(
            grade.strip().upper()
            for grade in _get(source, "SEAT_GRADE_PREFERENCE", "VIP,R,S,A").split(",")
            if grade.strip()
        )
        if not grades:
            raise SettingsError("SEAT_GRADE_PREFERENCE must not be empty")

        max_tickets = _parse_int(source, "MAX_TICKETS", 2)
        poll_interval = _parse_float(source, "POLL_INTERVAL", 1.5)
        queue_timeout = _parse_int(source, "QUEUE_TIMEOUT", 600)
        queue_poll = _parse_float(source, "QUEUE_POLL", 2.0)
        salesinfo_timeout = _parse_float(source, "SALESINFO_TIMEOUT", 5.0)
        salesinfo_retries = _parse_int(source, "SALESINFO_RETRIES", 3)
        salesinfo_backoff = _parse_float(source, "SALESINFO_BACKOFF", 0.5)
        salesinfo_jitter = _parse_float(source, "SALESINFO_JITTER", 0.2)
        salesinfo_rate_limit = _parse_float(source, "SALESINFO_RATE_LIMIT", 0.25)

        _validate_range("MAX_TICKETS", max_tickets, 1, 10)
        _validate_range("POLL_INTERVAL", poll_interval, 0.1, 60.0)
        _validate_range("QUEUE_TIMEOUT", queue_timeout, 1, 7200)
        _validate_range("QUEUE_POLL", queue_poll, 0.1, 60.0)
        _validate_range("SALESINFO_TIMEOUT", salesinfo_timeout, 0.1, 60.0)
        _validate_range("SALESINFO_RETRIES", salesinfo_retries, 0, 10)
        _validate_range("SALESINFO_BACKOFF", salesinfo_backoff, 0.0, 60.0)
        _validate_range("SALESINFO_JITTER", salesinfo_jitter, 0.0, 10.0)
        _validate_range("SALESINFO_RATE_LIMIT", salesinfo_rate_limit, 0.0, 60.0)

        return cls(
            goods_code=_validate_code("GOODS_CODE", _get(source, "GOODS_CODE", "26005973")),
            place_code=_validate_code("PLACE_CODE", _get(source, "PLACE_CODE", "26000437")),
            biz_code=_validate_code("BIZ_CODE", _get(source, "BIZ_CODE", "10965")),
            lang=_get(source, "LANG", "zh-CN").strip() or "zh-CN",
            base_url=_get(source, "BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            nol_email=_get(source, "NOL_EMAIL", ""),
            nol_password=_get(source, "NOL_PASSWORD", ""),
            chromium_path=_get(source, "CHROMIUM_PATH", ""),
            headless=_parse_bool(_get(source, "HEADLESS", "false"), "HEADLESS"),
            seat_grade_preference=grades,
            max_tickets=max_tickets,
            stop_before_payment=_parse_bool(
                _get(source, "STOP_BEFORE_PAYMENT", "true"),
                "STOP_BEFORE_PAYMENT",
            ),
            confirm_before_payment=_parse_bool(
                _get(source, "CONFIRM_BEFORE_PAYMENT", "true"),
                "CONFIRM_BEFORE_PAYMENT",
            ),
            poll_interval=poll_interval,
            queue_poll=queue_poll,
            queue_timeout=queue_timeout,
            salesinfo_timeout=salesinfo_timeout,
            salesinfo_retries=salesinfo_retries,
            salesinfo_backoff=salesinfo_backoff,
            salesinfo_jitter=salesinfo_jitter,
            salesinfo_rate_limit=salesinfo_rate_limit,
        )


def load_settings(
    env: Mapping[str, str] | None = None,
    env_file: str | os.PathLike[str] | None = None,
    load_env: bool = True,
) -> Settings:
    if load_env:
        _load_dotenv_once(env_file)
    return Settings.from_env(env)


SETTINGS = load_settings()

# Backward-compatible module constants.
GOODS_CODE = SETTINGS.goods_code
PLACE_CODE = SETTINGS.place_code
BIZ_CODE = SETTINGS.biz_code
LANG = SETTINGS.lang
BASE_URL = SETTINGS.base_url
NOL_EMAIL = SETTINGS.nol_email
NOL_PASSWORD = SETTINGS.nol_password
CHROMIUM_PATH = SETTINGS.chromium_path
HEADLESS = SETTINGS.headless
WINDOW_W = SETTINGS.window_w
WINDOW_H = SETTINGS.window_h
SEAT_GRADE_PREFERENCE = list(SETTINGS.seat_grade_preference)
MAX_TICKETS = SETTINGS.max_tickets
STOP_BEFORE_PAYMENT = SETTINGS.stop_before_payment
CONFIRM_BEFORE_PAYMENT = SETTINGS.confirm_before_payment
POLL_INTERVAL = SETTINGS.poll_interval
QUEUE_POLL = SETTINGS.queue_poll
QUEUE_TIMEOUT = SETTINGS.queue_timeout
PAGE_WAIT_TIMEOUT = SETTINGS.page_wait_timeout

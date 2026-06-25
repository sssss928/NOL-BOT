"""Sensitive value redaction for URLs and log records."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "<redacted>"
_REDACTED_QUERY_KEY = "redacted"
_SENSITIVE_NAMES = {
    "partner_token",
    "partnertoken",
    "partner_token_r",
    "partnertokenr",
    "user_id",
    "userid",
    "session",
    "sessionid",
    "session_id",
    "order",
    "orderid",
    "order_id",
    "orderno",
    "order_no",
    "ordernumber",
    "order_number",
}
_URLISH_RE = re.compile(r"https?://[^\s<>'\")]+", re.IGNORECASE)
_QUERY_PARAM_RE = re.compile(
    r"(?i)(?:^|[?&\s])"
    r"(partner_token_r|partner_token|user_id|session(?:_?id)?|order(?:_?(?:id|no|number))?)"
    r"=([^&\s]+)"
)
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_ORDER_PATH_RE = re.compile(r"(?i)(/(?:order|orders|reservation|reservations)/)[^/?#]+")


def is_sensitive_name(name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", name.lower())
    return normalized in _SENSITIVE_NAMES or "session" in normalized or "order" in normalized


def redact_url(value: str) -> str:
    """Redact sensitive query parameters and likely order path segments."""

    try:
        parts = urlsplit(value)
    except ValueError:
        return redact_text(value)

    if not parts.scheme or not parts.netloc:
        return redact_text(value)

    query: list[tuple[str, str]] = []
    redacted_count = 0
    for key, item_value in parse_qsl(parts.query, keep_blank_values=True):
        if is_sensitive_name(key):
            redacted_count += 1
            continue
        query.append((key, item_value))

    if redacted_count:
        query.append((_REDACTED_QUERY_KEY, REDACTED))

    path = _ORDER_PATH_RE.sub(rf"\1{REDACTED}", parts.path)
    redacted = urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            path,
            urlencode(query, doseq=True),
            parts.fragment,
        )
    )
    return _JWT_RE.sub(REDACTED, redacted)


def redact_text(value: Any) -> str:
    """Redact sensitive values from arbitrary log text."""

    text = str(value)
    text = _URLISH_RE.sub(lambda match: redact_url(match.group(0)), text)
    text = _QUERY_PARAM_RE.sub(lambda match: f" {REDACTED}={REDACTED}", text)
    text = _JWT_RE.sub(REDACTED, text)
    return text


def _redact_arg(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {
            (REDACTED if is_sensitive_name(str(key)) else key): _redact_arg(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(_redact_arg(item) for item in value)
    if isinstance(value, list):
        return [_redact_arg(item) for item in value]
    return value


class RedactingFilter(logging.Filter):
    """Logging filter that redacts sensitive URL/query content."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(record.msg)
        if record.args:
            record.args = _redact_arg(record.args)
        return True


def install_redacting_filter(logger: logging.Logger | None = None) -> None:
    """Install a redacting filter once on the selected logger."""

    target = logging.getLogger() if logger is None else logger
    if not any(isinstance(item, RedactingFilter) for item in target.filters):
        target.addFilter(RedactingFilter())

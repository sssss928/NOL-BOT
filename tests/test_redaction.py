from __future__ import annotations

import logging

from nol_ticket_bot.redaction import REDACTED, RedactingFilter, redact_text, redact_url


def test_redact_url_removes_sensitive_query_names_and_values() -> None:
    url = (
        "https://tickets.interpark.com/gates/partner"
        "?partner_token=secret&partner_token_r=secret2&user_id=u1&gc=26005973"
    )

    redacted = redact_url(url)

    assert "partner_token" not in redacted
    assert "partner_token_r" not in redacted
    assert "user_id" not in redacted
    assert "secret" not in redacted
    assert "gc=26005973" in redacted
    assert REDACTED in redacted


def test_redact_text_redacts_order_session_and_jwt() -> None:
    text = (
        "url=https://example.test/order/ORDER-123?session=abc&order_id=xyz "
        "token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signaturedata"
    )

    redacted = redact_text(text)

    assert "ORDER-123" not in redacted
    assert "session" not in redacted
    assert "order_id" not in redacted
    assert "eyJhbGci" not in redacted


def test_logging_filter_redacts_record_args() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="redirected to %s",
        args=("https://host.test/?partner_token=secret",),
        exc_info=None,
    )

    assert RedactingFilter().filter(record)
    message = record.getMessage()
    assert "partner_token" not in message
    assert "secret" not in message

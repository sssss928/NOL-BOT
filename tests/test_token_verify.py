from __future__ import annotations

from dataclasses import replace
from typing import Any

from nol_ticket_bot.config import Settings
from nol_ticket_bot.purchase import PurchaseStatus, inspect_token_verify, wait_for_token_verify


class Element:
    def __init__(self, text: str = "") -> None:
        self.text = text


class Page:
    def __init__(self, url: str, elements: dict[str, Any] | None = None) -> None:
        self.url = url
        self.elements = elements or {}

    def ele(self, selector: str, timeout: float = 0) -> Any:
        return self.elements.get(selector)


def test_token_verify_success_uses_dom_marker() -> None:
    page = Page(
        "https://tickets.interpark.com/gates/partner?partner_token=secret",
        {"css:[data-testid*='seat']": Element()},
    )

    result = inspect_token_verify(page)

    assert result is not None
    assert result.ok
    assert "partner_token" not in result.url


def test_token_verify_rejects_deny_text() -> None:
    page = Page(
        "https://tickets.interpark.com/gates/partner?partner_token=secret",
        {"tag:body": Element("Access denied because token is invalid")},
    )

    result = inspect_token_verify(page)

    assert result is not None
    assert not result.ok
    assert result.status == PurchaseStatus.TOKEN_VERIFY_FAILED


def test_wait_for_token_verify_times_out_on_pending_gate() -> None:
    page = Page("https://tickets.interpark.com/gates/partner?partner_token=secret")
    settings = replace(Settings(), queue_timeout=1, queue_poll=0.1)
    times = iter([0.0, 0.0, 2.0])

    result = wait_for_token_verify(
        page,
        settings,
        sleep_fn=lambda _seconds: None,
        clock=lambda: next(times),
    )

    assert not result.ok
    assert result.status == PurchaseStatus.TOKEN_VERIFY_FAILED
    assert "partner_token" not in result.url

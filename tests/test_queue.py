from __future__ import annotations

from dataclasses import replace
from typing import Any

from nol_ticket_bot.config import Settings
from nol_ticket_bot.purchase import PurchaseStatus, inspect_queue, wait_for_queue


class Element:
    def __init__(self, text: str = "") -> None:
        self.text = text


class Page:
    def __init__(self, url: str, elements: dict[str, Any] | None = None) -> None:
        self.url = url
        self.elements = elements or {}

    def ele(self, selector: str, timeout: float = 0) -> Any:
        return self.elements.get(selector)


def test_queue_success_from_allowlisted_host_and_dom_marker() -> None:
    page = Page(
        "https://tickets.interpark.com/booking/seat?session=secret",
        {"css:[data-testid*='seat']": Element()},
    )

    result = inspect_queue(page)

    assert result is not None
    assert result.ok
    assert "session" not in result.url
    assert "secret" not in result.url


def test_queue_rejects_unexpected_host() -> None:
    page = Page("https://evil.example/booking/seat")

    result = inspect_queue(page)

    assert result is not None
    assert not result.ok
    assert result.status == PurchaseStatus.QUEUE_TIMEOUT


def test_wait_for_queue_times_out_while_waiting() -> None:
    page = Page(
        "https://ent-waiting-api.interpark.com/waiting",
        {"css:[class*='waiting']": Element("waiting")},
    )
    settings = replace(Settings(), queue_timeout=1, queue_poll=0.1)
    times = iter([0.0, 0.0, 2.0])

    result = wait_for_queue(
        page,
        settings,
        sleep_fn=lambda _seconds: None,
        clock=lambda: next(times),
    )

    assert not result.ok
    assert result.status == PurchaseStatus.QUEUE_TIMEOUT

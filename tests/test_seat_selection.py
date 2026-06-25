from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from nol_ticket_bot.config import Settings
from nol_ticket_bot.purchase import PurchaseStatus, confirm_order, select_seat


class Button:
    def __init__(self) -> None:
        self.clicked = False

    def click(self) -> None:
        self.clicked = True


class Page:
    url = "https://tickets.interpark.com/booking/seat?session=secret"

    def __init__(self, elements: dict[str, Any] | None = None) -> None:
        self.elements = elements or {}

    def ele(self, selector: str, timeout: float = 0) -> Any:
        return self.elements.get(selector)


def test_select_seat_increments_only_after_selected_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = iter(
        [
            {"found": True, "selector": "[data-grade*=VIP]", "count": 1},
            {"clicked": True, "selected": True, "before": 0, "after": 1},
        ]
    )
    monkeypatch.setattr("nol_ticket_bot.purchase.cdp_eval", lambda *_args: next(calls))
    settings = replace(Settings(), seat_grade_preference=("VIP",), max_tickets=1)

    result = select_seat(Page(), settings)

    assert result.ok
    assert result.selected_count == 1


def test_select_seat_does_not_count_unverified_click(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = iter(
        [
            {"found": True, "selector": "[data-grade*=VIP]", "count": 1},
            {"clicked": True, "selected": False, "before": 0, "after": 0},
        ]
    )
    monkeypatch.setattr("nol_ticket_bot.purchase.cdp_eval", lambda *_args: next(calls))
    settings = replace(Settings(), seat_grade_preference=("VIP",), max_tickets=1)

    result = select_seat(Page(), settings)

    assert not result.ok
    assert result.status == PurchaseStatus.SEAT_SELECTION_FAILED
    assert result.selected_count == 0


def test_confirm_order_stops_before_payment() -> None:
    button = Button()
    settings = replace(Settings(), stop_before_payment=True)

    result = confirm_order(Page({"text:Confirm": button}), settings)

    assert result.ok
    assert result.status == PurchaseStatus.STOPPED_BEFORE_PAYMENT
    assert not button.clicked


def test_confirm_order_requires_manual_payment_confirmation() -> None:
    button = Button()
    settings = replace(Settings(), stop_before_payment=False, confirm_before_payment=True)

    result = confirm_order(
        Page({"text:Confirm": button}),
        settings,
        confirmer=lambda _url: False,
    )

    assert not result.ok
    assert result.status == PurchaseStatus.PAYMENT_CONFIRMATION_DECLINED
    assert not button.clicked


def test_confirm_order_clicks_after_confirmation() -> None:
    button = Button()
    settings = replace(Settings(), stop_before_payment=False, confirm_before_payment=True)

    result = confirm_order(
        Page({"text:Confirm": button}),
        settings,
        confirmer=lambda _url: True,
    )

    assert result.ok
    assert button.clicked

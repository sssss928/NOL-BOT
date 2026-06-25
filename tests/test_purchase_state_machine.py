from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from nol_ticket_bot.config import Settings
from nol_ticket_bot.purchase import (
    PurchaseStateMachine,
    PurchaseStatus,
    PurchaseStep,
    StepResult,
)


class Page:
    url = "https://world.nol.com"

    def __init__(self) -> None:
        self.opened: list[str] = []

    def get(self, url: str) -> None:
        self.opened.append(url)
        self.url = url

    def ele(self, selector: str, timeout: float = 0) -> Any:
        if "user-avatar" in selector:
            return object()
        return None


def test_state_machine_returns_token_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nol_ticket_bot.purchase.click_buy",
        lambda *_args, **_kwargs: StepResult(True, PurchaseStatus.SUCCESS),
    )
    monkeypatch.setattr(
        "nol_ticket_bot.purchase.wait_for_interpark",
        lambda *_args, **_kwargs: StepResult(True, PurchaseStatus.SUCCESS),
    )
    monkeypatch.setattr(
        "nol_ticket_bot.purchase.wait_for_token_verify",
        lambda *_args, **_kwargs: StepResult(
            False,
            PurchaseStatus.TOKEN_VERIFY_FAILED,
            "token verify timed out",
            "https://tickets.interpark.com/gates/partner?redacted=%3Credacted%3E",
        ),
    )
    settings = replace(Settings(), queue_timeout=1)

    result = PurchaseStateMachine(Page(), settings=settings).run()

    assert not result.ok
    assert result.status == PurchaseStatus.TOKEN_VERIFY_FAILED
    assert result.step == PurchaseStep.TOKEN_VERIFY
    assert result.failure_reason == "token verify timed out"


def test_state_machine_success_stopped_before_payment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nol_ticket_bot.purchase.click_buy",
        lambda *_args, **_kwargs: StepResult(True, PurchaseStatus.SUCCESS),
    )
    monkeypatch.setattr(
        "nol_ticket_bot.purchase.wait_for_interpark",
        lambda *_args, **_kwargs: StepResult(True, PurchaseStatus.SUCCESS),
    )
    monkeypatch.setattr(
        "nol_ticket_bot.purchase.wait_for_token_verify",
        lambda *_args, **_kwargs: StepResult(True, PurchaseStatus.SUCCESS),
    )
    monkeypatch.setattr(
        "nol_ticket_bot.purchase.wait_for_queue",
        lambda *_args, **_kwargs: StepResult(True, PurchaseStatus.SUCCESS),
    )
    monkeypatch.setattr(
        "nol_ticket_bot.purchase.select_seat",
        lambda *_args, **_kwargs: StepResult(
            True,
            PurchaseStatus.SUCCESS,
            selected_count=2,
        ),
    )
    monkeypatch.setattr(
        "nol_ticket_bot.purchase.confirm_order",
        lambda *_args, **_kwargs: StepResult(True, PurchaseStatus.STOPPED_BEFORE_PAYMENT),
    )

    result = PurchaseStateMachine(Page(), settings=Settings()).run()

    assert result.ok
    assert result.status == PurchaseStatus.STOPPED_BEFORE_PAYMENT
    assert result.selected_count == 2

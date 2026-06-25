from __future__ import annotations

from typing import Any

from click.testing import CliRunner

from nol_ticket_bot import cli
from nol_ticket_bot.purchase import PurchaseResult, PurchaseStatus, PurchaseStep


class Page:
    def __init__(self) -> None:
        self.quit_called = False

    def quit(self) -> None:
        self.quit_called = True


def test_cli_check_prints_salesinfo(monkeypatch: Any) -> None:
    monkeypatch.setattr(cli, "fetch_sales_info", lambda: {"salesInfo": {"goodsStatus": "Y"}})

    result = CliRunner().invoke(cli.main, ["check"])

    assert result.exit_code == 0
    assert "goodsStatus" in result.output


def test_cli_check_exits_nonzero_on_failure(monkeypatch: Any) -> None:
    monkeypatch.setattr(cli, "fetch_sales_info", lambda: None)

    result = CliRunner().invoke(cli.main, ["check"])

    assert result.exit_code == 1
    assert "salesinfo request failed" in result.output


def test_cli_buy_uses_purchase_result(monkeypatch: Any) -> None:
    page = Page()
    monkeypatch.setattr(cli, "create_browser_page", lambda: page)
    monkeypatch.setattr(
        cli,
        "purchase_run",
        lambda *_args, **_kwargs: PurchaseResult(
            ok=True,
            status=PurchaseStatus.STOPPED_BEFORE_PAYMENT,
            step=PurchaseStep.DONE,
            selected_count=2,
        ),
    )

    result = CliRunner().invoke(cli.main, ["buy"])

    assert result.exit_code == 0
    assert "Selected seats: 2" in result.output


def test_cli_buy_reports_failure(monkeypatch: Any) -> None:
    monkeypatch.setattr(cli, "create_browser_page", Page)
    monkeypatch.setattr(
        cli,
        "purchase_run",
        lambda *_args, **_kwargs: PurchaseResult(
            ok=False,
            status=PurchaseStatus.TOKEN_VERIFY_FAILED,
            step=PurchaseStep.TOKEN_VERIFY,
            failure_reason="token verify timed out",
            final_url="https://tickets.interpark.com/gates/partner?redacted=%3Credacted%3E",
        ),
    )

    result = CliRunner().invoke(cli.main, ["buy"])

    assert result.exit_code == 1
    assert "token_verify_failed" in result.output
    assert "token verify timed out" in result.output

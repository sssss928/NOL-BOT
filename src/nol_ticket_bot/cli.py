"""Command line interface."""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from typing import Any

import click

from . import config
from .monitor import fetch_sales_info, poll_until_open
from .purchase import PurchaseResult, PurchaseStatus
from .purchase import run as purchase_run
from .redaction import install_redacting_filter

log = logging.getLogger(__name__)


def _setup_logging(verbose: bool) -> None:
    install_redacting_filter()
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def create_browser_page() -> Any:
    from .browser import create_browser

    return create_browser()


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
@click.pass_context
def main(ctx: click.Context, verbose: bool) -> None:
    """NOL World ticket helper."""

    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    _setup_logging(verbose)


@main.command()
def check() -> None:
    """Fetch salesinfo once and print the response data."""

    data = fetch_sales_info()
    if data:
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        return
    click.secho("salesinfo request failed", fg="red")
    raise click.exceptions.Exit(1)


@main.command()
def monitor() -> None:
    """Poll salesinfo until the sale opens."""

    click.secho(f"monitoring goodsCode={config.SETTINGS.goods_code}; Ctrl-C to stop", fg="cyan")
    try:
        poll_until_open()
    except KeyboardInterrupt:
        click.echo("\nstopped")


@main.command()
def buy() -> None:
    """Run the purchase workflow immediately."""

    _run_purchase()


@main.command()
def run() -> None:
    """Monitor until open, then run the purchase workflow."""

    page = create_browser_page()
    sale_event = threading.Event()

    def on_open(_info: dict[str, Any]) -> None:
        click.secho("sale opened; starting purchase workflow", fg="green", bold=True)
        sale_event.set()

    thread = threading.Thread(
        target=poll_until_open,
        kwargs={"on_open": on_open},
        daemon=True,
    )
    thread.start()

    try:
        sale_event.wait()
        time.sleep(0.05)
        _do_purchase(page)
    except KeyboardInterrupt:
        click.echo("\nstopped")
    finally:
        _quit_page_if_needed(page)


def _run_purchase() -> None:
    page = create_browser_page()
    try:
        _do_purchase(page)
    except KeyboardInterrupt:
        click.echo("\nstopped")
    finally:
        _quit_page_if_needed(page)


def _confirm_payment(url: str) -> bool:
    click.secho("Payment confirmation required.", fg="yellow", bold=True)
    click.echo(f"Current page: {url}")
    value = str(click.prompt("Type PAY to continue to payment", default="", show_default=False))
    return value.strip().upper() == "PAY"


def _do_purchase(page: Any) -> None:
    result = purchase_run(page, confirmer=_confirm_payment)
    _print_purchase_result(result)
    if not result.ok:
        raise click.exceptions.Exit(1)


def _print_purchase_result(result: PurchaseResult) -> None:
    if result.ok:
        if result.status == PurchaseStatus.STOPPED_BEFORE_PAYMENT:
            click.secho(
                "\npurchase flow stopped before payment for manual completion",
                fg="green",
                bold=True,
            )
        else:
            click.secho("\npurchase flow completed", fg="green", bold=True)
        if result.selected_count:
            click.echo(f"Selected seats: {result.selected_count}")
        return

    click.secho("\npurchase flow failed", fg="red", bold=True)
    click.echo(f"Status: {result.status.value}")
    click.echo(f"Step: {result.step.value}")
    if result.failure_reason:
        click.echo(f"Reason: {result.failure_reason}")
    if result.final_url:
        click.echo(f"URL: {result.final_url}")
    log.error(
        "purchase failed status=%s step=%s reason=%s url=%s",
        result.status.value,
        result.step.value,
        result.failure_reason,
        result.final_url,
    )


def _quit_page_if_needed(page: Any) -> None:
    if config.SETTINGS.stop_before_payment:
        return
    try:
        page.quit()
    except Exception:
        log.debug("page quit failed", exc_info=True)


if __name__ == "__main__":
    sys.exit(main())

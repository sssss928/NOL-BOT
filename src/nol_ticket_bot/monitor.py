"""Sales opening monitor."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from . import config
from .client import NolClient
from .config import Settings

log = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
SALESINFO_URL = f"{config.BASE_URL}/api/ent-channel-out/v1/goods/salesinfo"


def fetch_sales_info(
    client: NolClient | None = None,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    active_settings = settings or config.SETTINGS
    active_client = client or NolClient(active_settings)
    return active_client.fetch_sales_info()


def next_poll_interval(
    current_interval: float,
    booking_open_time: str,
    now: datetime | None = None,
) -> float:
    if not booking_open_time:
        return current_interval
    try:
        open_at = datetime.strptime(booking_open_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
    except ValueError:
        return current_interval

    current_time = now or datetime.now(KST)
    seconds_left = (open_at - current_time).total_seconds()
    if seconds_left <= 5:
        return 0.3
    if seconds_left <= 30:
        return 0.5
    return current_interval


def poll_until_open(
    on_open: Callable[[dict[str, Any]], None] | None = None,
    *,
    client: NolClient | None = None,
    settings: Settings | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    max_iterations: int | None = None,
) -> dict[str, Any]:
    active_settings = settings or config.SETTINGS
    active_client = client or NolClient(active_settings)
    interval = active_settings.poll_interval
    iterations = 0

    log.info(
        "monitoring goodsCode=%s interval=%.1fs",
        active_settings.goods_code,
        interval,
    )

    while True:
        iterations += 1
        info = fetch_sales_info(client=active_client, settings=active_settings)
        if info:
            sales = info.get("salesInfo", {})
            status = sales.get("goodsStatus", "?")
            open_time = str(sales.get("bookingOpenTime", ""))
            interval = next_poll_interval(interval, open_time)

            log.info(
                "sales status=%s bookingOpenTime=%s bookingEndTime=%s",
                status,
                open_time,
                sales.get("bookingEndTime", ""),
            )

            if status == "Y":
                log.info("sales open")
                if on_open:
                    on_open(info)
                return info

        if max_iterations is not None and iterations >= max_iterations:
            raise TimeoutError("sales did not open before max_iterations")

        sleep_fn(interval)

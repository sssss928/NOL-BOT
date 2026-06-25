from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

import requests

from nol_ticket_bot.client import NolClient
from nol_ticket_bot.config import Settings
from nol_ticket_bot.monitor import KST, next_poll_interval, poll_until_open


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.url = "https://world.nol.com/api/ent-channel-out/v1/goods/salesinfo"

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}", response=self)


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls = 0

    def get(self, *_args: Any, **_kwargs: Any) -> FakeResponse:
        self.calls += 1
        return self.responses.pop(0)


def test_nol_client_retries_retryable_status() -> None:
    settings = replace(
        Settings(),
        salesinfo_retries=1,
        salesinfo_backoff=0,
        salesinfo_jitter=0,
        salesinfo_rate_limit=0,
    )
    session = FakeSession(
        [
            FakeResponse(503),
            FakeResponse(200, {"data": {"salesInfo": {"goodsStatus": "Y"}}}),
        ]
    )
    client = NolClient(settings, session=session, sleeper=lambda _seconds: None)

    result = client.fetch_sales_info()

    assert result == {"salesInfo": {"goodsStatus": "Y"}}
    assert session.calls == 2


def test_nol_client_returns_none_after_bounded_retries() -> None:
    settings = replace(
        Settings(),
        salesinfo_retries=1,
        salesinfo_backoff=0,
        salesinfo_jitter=0,
        salesinfo_rate_limit=0,
    )
    session = FakeSession([FakeResponse(503), FakeResponse(503)])
    client = NolClient(settings, session=session, sleeper=lambda _seconds: None)

    assert client.fetch_sales_info() is None
    assert session.calls == 2


def test_next_poll_interval_accelerates_near_open() -> None:
    now = datetime.now(KST)
    within_30s = (now + timedelta(seconds=20)).strftime("%Y-%m-%d %H:%M:%S")
    within_5s = (now + timedelta(seconds=3)).strftime("%Y-%m-%d %H:%M:%S")

    assert next_poll_interval(1.5, within_30s, now=now) == 0.5
    assert next_poll_interval(1.5, within_5s, now=now) == 0.3


def test_poll_until_open_invokes_callback() -> None:
    settings = replace(Settings(), poll_interval=0.1, salesinfo_rate_limit=0)
    client = NolClient(
        settings,
        session=FakeSession([FakeResponse(200, {"data": {"salesInfo": {"goodsStatus": "Y"}}})]),
        sleeper=lambda _seconds: None,
    )
    seen: list[dict[str, Any]] = []

    result = poll_until_open(
        on_open=seen.append,
        client=client,
        settings=settings,
        sleep_fn=lambda _seconds: None,
    )

    assert result["salesInfo"]["goodsStatus"] == "Y"
    assert seen == [result]

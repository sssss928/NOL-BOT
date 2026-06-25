"""HTTP client for NOL public APIs."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import requests

from .config import Settings
from .redaction import redact_url

log = logging.getLogger(__name__)


@dataclass
class NolClient:
    settings: Settings
    session: requests.Session = field(default_factory=requests.Session)
    sleeper: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    random_source: random.Random = field(default_factory=random.Random)
    _last_request_at: float | None = field(default=None, init=False)

    @property
    def salesinfo_url(self) -> str:
        return f"{self.settings.base_url}/api/ent-channel-out/v1/goods/salesinfo"

    def fetch_sales_info(self) -> dict[str, Any] | None:
        params = {
            "goodsCode": self.settings.goods_code,
            "placeCode": self.settings.place_code,
            "bizCode": self.settings.biz_code,
        }

        attempts = self.settings.salesinfo_retries + 1
        for attempt in range(attempts):
            self._rate_limit()
            try:
                response = self.session.get(
                    self.salesinfo_url,
                    params=params,
                    timeout=self.settings.salesinfo_timeout,
                )
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise requests.HTTPError(
                        f"retryable status {response.status_code}",
                        response=response,
                    )
                response.raise_for_status()
                payload = response.json()
                data = payload.get("data", {})
                return data if isinstance(data, dict) else {}
            except (requests.RequestException, ValueError, OSError) as exc:
                if attempt >= self.settings.salesinfo_retries:
                    url = getattr(getattr(exc, "response", None), "url", self.salesinfo_url)
                    log.warning(
                        "salesinfo request failed after %s attempt(s): %s url=%s",
                        attempt + 1,
                        exc,
                        redact_url(str(url)),
                    )
                    return None
                self._sleep_before_retry(attempt)
        return None

    def _rate_limit(self) -> None:
        interval = self.settings.salesinfo_rate_limit
        if interval <= 0:
            self._last_request_at = self.clock()
            return
        now = self.clock()
        if self._last_request_at is not None:
            wait = interval - (now - self._last_request_at)
            if wait > 0:
                self.sleeper(wait)
        self._last_request_at = self.clock()

    def _sleep_before_retry(self, attempt: int) -> None:
        base = self.settings.salesinfo_backoff * (2**attempt)
        jitter = self.random_source.uniform(0.0, self.settings.salesinfo_jitter)
        delay = min(base + jitter, 60.0)
        if delay > 0:
            self.sleeper(delay)

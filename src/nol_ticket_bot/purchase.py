"""Purchase workflow implemented as an explicit state machine."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any
from urllib.parse import urlsplit

from . import config
from .browser import cdp_eval, dismiss_dialog, wait_for_element
from .config import Settings
from .redaction import redact_url

log = logging.getLogger(__name__)

INTERPARK_HOSTS = {"tickets.interpark.com", "ticket.globalinterpark.com"}
INTERPARK_WAITING_HOSTS = {"ent-waiting-api.interpark.com"}
TOKEN_GATE_PATH = "/gates/partner"
SUCCESS_PATH_SEGMENTS = {"seat", "booking", "order", "reservation", "select", "schedule", "payment", "purchase"}
QUEUE_PATH_SEGMENTS = {"seat", "booking", "order", "reservation", "select", "schedule", "payment", "purchase"}
DENY_PATH_SEGMENTS = {"error", "denied", "forbidden", "blocked", "invalid"}
DENY_TEXT_MARKERS = (
    "abnormal",
    "access denied",
    "blocked",
    "expired",
    "forbidden",
    "invalid",
    "temporarily unavailable",
    "unauthorized",
    "verification failed",
)
TOKEN_SUCCESS_SELECTORS = (
    "css:[data-testid*='seat']",
    "css:[data-testid*='booking']",
    "css:[class*='seat']",
    "css:[class*='booking']",
    "css:iframe[src*='seat']",
)
TOKEN_DENY_SELECTORS = (
    "css:[data-error]",
    "css:[class*='error']",
    "css:[class*='blocked']",
)
QUEUE_SUCCESS_SELECTORS = (
    "css:[data-testid*='seat']",
    "css:[data-testid*='booking']",
    "css:[data-testid*='order']",
    "css:[class*='seat']",
    "css:[class*='booking']",
)
QUEUE_PENDING_SELECTORS = (
    "css:[class*='waiting']",
    "css:[class*='queue']",
    "css:[class*='rank']",
    "css:[data-testid*='waiting']",
    "css:[data-testid*='queue']",
)
CONFIRM_TEXTS = (
    "Confirm",
    "Next",
    "Continue",
    "Payment",
    "Book",
    "Reserve",
    "Pay",
)
BUY_TEXTS = (
    "Buy Ticket",
    "Book",
    "Reserve",
    "Ticket",
)


class PurchaseStatus(str, Enum):
    SUCCESS = "success"
    STOPPED_BEFORE_PAYMENT = "stopped_before_payment"
    LOGIN_FAILED = "login_failed"
    BUY_BUTTON_NOT_FOUND = "buy_button_not_found"
    INTERPARK_TIMEOUT = "interpark_timeout"
    TOKEN_VERIFY_FAILED = "token_verify_failed"
    QUEUE_TIMEOUT = "queue_timeout"
    SEAT_SELECTION_FAILED = "seat_selection_failed"
    ORDER_CONFIRM_FAILED = "order_confirm_failed"
    PAYMENT_CONFIRMATION_REQUIRED = "payment_confirmation_required"
    PAYMENT_CONFIRMATION_DECLINED = "payment_confirmation_declined"
    ERROR = "error"


class PurchaseStep(str, Enum):
    START = "start"
    LOGIN = "login"
    PRODUCT = "product"
    BUY = "buy"
    INTERPARK = "interpark"
    TOKEN_VERIFY = "token_verify"
    QUEUE = "queue"
    SEAT = "seat"
    CONFIRM_ORDER = "confirm_order"
    DONE = "done"


@dataclass(frozen=True)
class StepResult:
    ok: bool
    status: PurchaseStatus
    reason: str = ""
    url: str = ""
    selected_count: int = 0


@dataclass(frozen=True)
class PurchaseResult:
    ok: bool
    status: PurchaseStatus
    step: PurchaseStep
    failure_reason: str = ""
    final_url: str = ""
    selected_count: int = 0

    @classmethod
    def from_step(cls, step: PurchaseStep, result: StepResult) -> "PurchaseResult":
        return cls(
            ok=result.ok,
            status=result.status,
            step=step,
            failure_reason="" if result.ok else result.reason,
            final_url=result.url,
            selected_count=result.selected_count,
        )


def product_url(settings: Settings | None = None) -> str:
    active = settings or config.SETTINGS
    return (
        f"{active.base_url}/{active.lang}/ticket/genre/CONCERT"
        f"/products/{active.goods_code}?placeCode={active.place_code}"
    )


def login_url(settings: Settings | None = None) -> str:
    active = settings or config.SETTINGS
    return f"{active.base_url}/{active.lang}/login"


def current_url(page: Any) -> str:
    return str(getattr(page, "url", ""))


def safe_current_url(page: Any) -> str:
    return redact_url(current_url(page))


def _url_host(url: str) -> str:
    try:
        return urlsplit(url).hostname or ""
    except ValueError:
        return ""


def _url_segments(url: str) -> set[str]:
    try:
        return {part.lower() for part in urlsplit(url).path.split("/") if part}
    except ValueError:
        return set()


def _path_equals(url: str, path: str) -> bool:
    try:
        return urlsplit(url).path.rstrip("/") == path
    except ValueError:
        return False


def _has_any_segment(url: str, segments: set[str]) -> bool:
    return bool(_url_segments(url) & segments)


def _safe_ele(page: Any, selector: str, timeout: float = 0.3) -> Any | None:
    try:
        return page.ele(selector, timeout=timeout)
    except Exception:
        return None


def _has_dom_marker(page: Any, selectors: Iterable[str]) -> bool:
    return any(_safe_ele(page, selector, timeout=0.2) for selector in selectors)


def _body_text(page: Any) -> str:
    body = _safe_ele(page, "tag:body", timeout=0.2)
    if not body:
        return ""
    return str(getattr(body, "text", "") or "")


def _has_deny_text(page: Any) -> bool:
    text = _body_text(page).lower()
    return any(marker in text for marker in DENY_TEXT_MARKERS)


def _url_failure_status(url: str, status: PurchaseStatus, reason_prefix: str) -> StepResult | None:
    if _has_any_segment(url, DENY_PATH_SEGMENTS):
        return StepResult(False, status, f"{reason_prefix}: denylisted path", redact_url(url))
    return None


def login(page: Any, settings: Settings | None = None) -> StepResult:
    active = settings or config.SETTINGS
    page.get(login_url(active))
    time.sleep(1)

    if active.nol_email and active.nol_password:
        try:
            wait_for_element(page, "input[type='email']", timeout=10).input(active.nol_email, clear=True)
            wait_for_element(page, "input[type='password']", timeout=5).input(
                active.nol_password,
                clear=True,
            )
            log.info("credentials filled; finish interactive login if required")
        except Exception as exc:
            log.warning("credential autofill failed: %s", exc)
    else:
        log.info("no credentials configured; waiting for manual login")

    for _ in range(120):
        if "login" not in current_url(page).lower():
            return StepResult(True, PurchaseStatus.SUCCESS, url=safe_current_url(page))
        time.sleep(1)

    return StepResult(False, PurchaseStatus.LOGIN_FAILED, "login timed out", safe_current_url(page))


def navigate_to_product(page: Any, settings: Settings | None = None) -> None:
    target = product_url(settings)
    log.info("opening product page: %s", redact_url(target))
    page.get(target)
    time.sleep(1)
    dismiss_dialog(page)


def click_buy(page: Any, settings: Settings | None = None) -> StepResult:
    active = settings or config.SETTINGS
    for text in BUY_TEXTS:
        button = _safe_ele(page, f"text:{text}", timeout=1)
        if button:
            button.click()
            time.sleep(0.5)
            return StepResult(True, PurchaseStatus.SUCCESS, url=safe_current_url(page))

    labels = json.dumps([text.lower() for text in BUY_TEXTS])
    clicked = cdp_eval(
        page,
        f"""
(() => {{
  const labels = new Set({labels});
  const buttons = [...document.querySelectorAll('button,a,[role="button"]')];
  const button = buttons.find((item) => labels.has((item.textContent || '').trim().toLowerCase()));
  if (!button) return false;
  button.click();
  return true;
}})()
""",
    )
    if clicked:
        time.sleep(0.5)
        return StepResult(True, PurchaseStatus.SUCCESS, url=safe_current_url(page))

    return StepResult(
        False,
        PurchaseStatus.BUY_BUTTON_NOT_FOUND,
        f"buy button not found for goodsCode={active.goods_code}",
        safe_current_url(page),
    )


def wait_for_interpark(
    page: Any,
    *,
    timeout: float = 15.0,
    sleep_fn: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> StepResult:
    deadline = clock() + timeout
    while clock() < deadline:
        url = current_url(page)
        host = _url_host(url)
        if host in INTERPARK_HOSTS or host in INTERPARK_WAITING_HOSTS:
            return StepResult(True, PurchaseStatus.SUCCESS, url=redact_url(url))
        sleep_fn(0.3)
    return StepResult(
        False,
        PurchaseStatus.INTERPARK_TIMEOUT,
        "did not reach Interpark allowlisted host",
        safe_current_url(page),
    )


def inspect_token_verify(page: Any) -> StepResult | None:
    url = current_url(page)
    host = _url_host(url)

    failure = _url_failure_status(url, PurchaseStatus.TOKEN_VERIFY_FAILED, "token verify failed")
    if failure:
        return failure
    if _has_deny_text(page) or _has_dom_marker(page, TOKEN_DENY_SELECTORS):
        return StepResult(
            False,
            PurchaseStatus.TOKEN_VERIFY_FAILED,
            "token verify deny marker found",
            redact_url(url),
        )
    if _has_dom_marker(page, TOKEN_SUCCESS_SELECTORS):
        return StepResult(True, PurchaseStatus.SUCCESS, url=redact_url(url))
    if host in INTERPARK_WAITING_HOSTS:
        return StepResult(True, PurchaseStatus.SUCCESS, url=redact_url(url))
    if host in INTERPARK_HOSTS:
        if _path_equals(url, TOKEN_GATE_PATH):
            return None
        if _has_any_segment(url, SUCCESS_PATH_SEGMENTS):
            return StepResult(True, PurchaseStatus.SUCCESS, url=redact_url(url))
        return None
    if host:
        return StepResult(
            False,
            PurchaseStatus.TOKEN_VERIFY_FAILED,
            f"unexpected host during token verify: {host}",
            redact_url(url),
        )
    return None


def wait_for_token_verify(
    page: Any,
    settings: Settings | None = None,
    *,
    timeout: float | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> StepResult:
    active = settings or config.SETTINGS
    deadline = clock() + (active.queue_timeout if timeout is None else timeout)
    while clock() < deadline:
        result = inspect_token_verify(page)
        if result:
            return result
        sleep_fn(active.queue_poll)
    return StepResult(
        False,
        PurchaseStatus.TOKEN_VERIFY_FAILED,
        "token verify timed out",
        safe_current_url(page),
    )


def inspect_queue(page: Any) -> StepResult | None:
    url = current_url(page)
    host = _url_host(url)

    failure = _url_failure_status(url, PurchaseStatus.QUEUE_TIMEOUT, "queue failed")
    if failure:
        return failure
    if _has_deny_text(page):
        return StepResult(False, PurchaseStatus.QUEUE_TIMEOUT, "queue deny marker found", redact_url(url))
    if _has_dom_marker(page, QUEUE_SUCCESS_SELECTORS):
        return StepResult(True, PurchaseStatus.SUCCESS, url=redact_url(url))
    if host in INTERPARK_HOSTS and _has_any_segment(url, QUEUE_PATH_SEGMENTS):
        return StepResult(True, PurchaseStatus.SUCCESS, url=redact_url(url))
    if host in INTERPARK_WAITING_HOSTS or _has_dom_marker(page, QUEUE_PENDING_SELECTORS):
        return None
    if host and host not in INTERPARK_HOSTS:
        return StepResult(
            False,
            PurchaseStatus.QUEUE_TIMEOUT,
            f"unexpected host during queue: {host}",
            redact_url(url),
        )
    return None


def wait_for_queue(
    page: Any,
    settings: Settings | None = None,
    *,
    timeout: float | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> StepResult:
    active = settings or config.SETTINGS
    deadline = clock() + (active.queue_timeout if timeout is None else timeout)
    while clock() < deadline:
        result = inspect_queue(page)
        if result:
            return result
        sleep_fn(active.queue_poll)
    return StepResult(False, PurchaseStatus.QUEUE_TIMEOUT, "queue timed out", safe_current_url(page))


def select_seat(page: Any, settings: Settings | None = None) -> StepResult:
    active = settings or config.SETTINGS
    selected = 0

    for grade in active.seat_grade_preference:
        if selected >= active.max_tickets:
            break

        probe_js = f"""
(() => {{
  const selectors = [
    '[data-grade*="{grade}" i]:not([disabled]):not(.sold-out)',
    '[data-seatgrade*="{grade}" i]:not([disabled]):not(.sold-out)',
    '[aria-label*="{grade}" i][aria-disabled="false"]',
    '[class*="available"][class*="{grade.lower()}"]',
    'rect[data-grade*="{grade}" i]',
    'text[data-grade*="{grade}" i]'
  ];
  for (const selector of selectors) {{
    const elements = document.querySelectorAll(selector);
    if (elements.length) return {{ found: true, selector, count: elements.length }};
  }}
  return {{ found: false, count: 0 }};
}})()
"""
        probe = cdp_eval(page, probe_js) or {}
        if not probe.get("found"):
            continue

        selector_json = json.dumps(probe["selector"])
        attempts = min(active.max_tickets - selected, int(probe.get("count", 0)))
        for _ in range(attempts):
            click_result = cdp_eval(page, _seat_click_js(selector_json)) or {}
            if click_result.get("selected"):
                selected += 1
                log.info("seat selected %s/%s", selected, active.max_tickets)
            else:
                log.warning("seat click did not produce selected marker: %s", click_result)
            if selected >= active.max_tickets:
                break
            time.sleep(0.2)

    if selected == 0:
        return StepResult(
            False,
            PurchaseStatus.SEAT_SELECTION_FAILED,
            "no clicked seat was verified as selected",
            safe_current_url(page),
            selected_count=0,
        )
    return StepResult(
        True,
        PurchaseStatus.SUCCESS,
        url=safe_current_url(page),
        selected_count=selected,
    )


def _seat_click_js(selector_json: str) -> str:
    return f"""
(async () => {{
  const selector = {selector_json};
  const selectedSelectors = [
    '[aria-selected="true"]',
    '[data-selected="true"]',
    '[data-status="selected"]',
    '[data-seat-status="selected"]',
    '.selected',
    '[class*="selected"]'
  ];
  function classText(element) {{
    const value = element.className || '';
    return typeof value === 'string' ? value : String(value.baseVal || '');
  }}
  function isSelected(element) {{
    const className = classText(element).toLowerCase();
    return element.getAttribute('aria-selected') === 'true'
      || element.getAttribute('data-selected') === 'true'
      || (element.getAttribute('data-status') || '').toLowerCase() === 'selected'
      || (element.getAttribute('data-seat-status') || '').toLowerCase() === 'selected'
      || className.includes('selected')
      || className.includes('active');
  }}
  function selectedCount() {{
    const seen = new Set();
    for (const item of selectedSelectors.flatMap((itemSelector) => [...document.querySelectorAll(itemSelector)])) {{
      seen.add(item);
    }}
    return seen.size;
  }}
  const elements = [...document.querySelectorAll(selector)];
  const element = elements.find((item) => !isSelected(item));
  if (!element) return {{ clicked: false, selected: false, before: selectedCount(), after: selectedCount() }};
  const before = selectedCount();
  element.click();
  await new Promise((resolve) => setTimeout(resolve, 100));
  const after = selectedCount();
  return {{
    clicked: true,
    selected: isSelected(element) || after > before,
    before,
    after
  }};
}})()
"""


def confirm_order(
    page: Any,
    settings: Settings | None = None,
    *,
    confirmer: Callable[[str], bool] | None = None,
) -> StepResult:
    active = settings or config.SETTINGS
    button = None
    for text in CONFIRM_TEXTS:
        button = _safe_ele(page, f"text:{text}", timeout=1)
        if button:
            break
    if not button:
        return StepResult(
            False,
            PurchaseStatus.ORDER_CONFIRM_FAILED,
            "order confirmation button not found",
            safe_current_url(page),
        )

    if active.stop_before_payment:
        log.info("stopped before payment: %s", safe_current_url(page))
        return StepResult(
            True,
            PurchaseStatus.STOPPED_BEFORE_PAYMENT,
            "manual payment is required",
            safe_current_url(page),
        )

    if active.confirm_before_payment:
        if confirmer is None:
            return StepResult(
                False,
                PurchaseStatus.PAYMENT_CONFIRMATION_REQUIRED,
                "payment confirmation callback is required",
                safe_current_url(page),
            )
        if not confirmer(safe_current_url(page)):
            return StepResult(
                False,
                PurchaseStatus.PAYMENT_CONFIRMATION_DECLINED,
                "payment confirmation declined",
                safe_current_url(page),
            )

    button.click()
    time.sleep(1)
    return StepResult(True, PurchaseStatus.SUCCESS, url=safe_current_url(page))


def _is_logged_in(page: Any) -> bool:
    if "login" in current_url(page).lower():
        return False
    return bool(
        _safe_ele(page, "css:a[href*='/mypage'],a[href*='/profile'],a[href*='/account']", timeout=1)
        or _safe_ele(page, "css:[data-testid='user-avatar'],[data-testid='user-menu']", timeout=1)
    )


@dataclass
class PurchaseStateMachine:
    page: Any
    settings: Settings = config.SETTINGS
    confirmer: Callable[[str], bool] | None = None
    sleep_fn: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic

    def run(self) -> PurchaseResult:
        try:
            self.page.get(self.settings.base_url)
            time.sleep(1)
            if not _is_logged_in(self.page):
                result = login(self.page, self.settings)
                if not result.ok:
                    return PurchaseResult.from_step(PurchaseStep.LOGIN, result)

            navigate_to_product(self.page, self.settings)

            result = click_buy(self.page, self.settings)
            if not result.ok:
                return PurchaseResult.from_step(PurchaseStep.BUY, result)

            if "login" in current_url(self.page).lower():
                result = login(self.page, self.settings)
                if not result.ok:
                    return PurchaseResult.from_step(PurchaseStep.LOGIN, result)
                navigate_to_product(self.page, self.settings)
                result = click_buy(self.page, self.settings)
                if not result.ok:
                    return PurchaseResult.from_step(PurchaseStep.BUY, result)

            result = wait_for_interpark(self.page, sleep_fn=self.sleep_fn, clock=self.clock)
            if not result.ok:
                return PurchaseResult.from_step(PurchaseStep.INTERPARK, result)

            result = wait_for_token_verify(
                self.page,
                self.settings,
                sleep_fn=self.sleep_fn,
                clock=self.clock,
            )
            if not result.ok:
                return PurchaseResult.from_step(PurchaseStep.TOKEN_VERIFY, result)

            result = wait_for_queue(
                self.page,
                self.settings,
                sleep_fn=self.sleep_fn,
                clock=self.clock,
            )
            if not result.ok:
                return PurchaseResult.from_step(PurchaseStep.QUEUE, result)

            result = select_seat(self.page, self.settings)
            if not result.ok:
                return PurchaseResult.from_step(PurchaseStep.SEAT, result)

            selected_count = result.selected_count
            result = confirm_order(self.page, self.settings, confirmer=self.confirmer)
            return PurchaseResult(
                ok=result.ok,
                status=result.status,
                step=PurchaseStep.DONE if result.ok else PurchaseStep.CONFIRM_ORDER,
                failure_reason="" if result.ok else result.reason,
                final_url=result.url,
                selected_count=selected_count,
            )
        except Exception as exc:
            log.exception("purchase state machine failed")
            return PurchaseResult(
                ok=False,
                status=PurchaseStatus.ERROR,
                step=PurchaseStep.START,
                failure_reason=str(exc),
                final_url=safe_current_url(self.page),
            )


def run(
    page: Any,
    settings: Settings | None = None,
    *,
    confirmer: Callable[[str], bool] | None = None,
) -> PurchaseResult:
    machine = PurchaseStateMachine(
        page=page,
        settings=settings or config.SETTINGS,
        confirmer=confirmer,
    )
    return machine.run()

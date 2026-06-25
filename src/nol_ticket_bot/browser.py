"""Browser helpers for DrissionPage."""

from __future__ import annotations

import logging
import time
from importlib import import_module
from typing import Any

from . import config

log = logging.getLogger(__name__)


def create_browser() -> Any:
    try:
        drission_page: Any = import_module("DrissionPage")
    except ModuleNotFoundError as exc:
        raise RuntimeError("DrissionPage is required to launch a browser") from exc

    settings = config.SETTINGS
    options_cls = drission_page.ChromiumOptions
    page_cls = drission_page.ChromiumPage

    options = options_cls()
    options.set_argument("--disable-blink-features=AutomationControlled")
    options.set_pref("credentials_enable_service", False)
    options.set_pref("profile.password_manager_enabled", False)
    options.set_argument(f"--window-size={settings.window_w},{settings.window_h}")
    options.set_argument("--no-sandbox")
    options.set_argument("--disable-dev-shm-usage")

    if settings.chromium_path:
        options.set_browser_path(settings.chromium_path)
    if settings.headless:
        options.headless(True)

    page = page_cls(options)
    page.run_cdp(
        "Page.addScriptToEvaluateOnNewDocument",
        source="""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
                configurable: true,
            });
        """,
    )
    log.info("browser started headless=%s", settings.headless)
    return page


def cdp_eval(page: Any, js: str) -> Any:
    try:
        result = page.run_cdp(
            "Runtime.evaluate",
            expression=js,
            returnByValue=True,
            awaitPromise=True,
        )
        return result.get("result", {}).get("value")
    except Exception as exc:  # pragma: no cover - defensive against browser failures
        log.debug("CDP eval failed: %s", exc)
        return None


def wait_for_element(page: Any, selector: str, timeout: int | None = None) -> Any:
    wait_timeout = config.SETTINGS.page_wait_timeout if timeout is None else timeout
    start = time.monotonic()
    while time.monotonic() - start < wait_timeout:
        element = page.ele(selector, timeout=1)
        if element:
            return element
        time.sleep(0.2)
    raise TimeoutError(f"element not found: {selector!r}")


def dismiss_dialog(page: Any) -> bool:
    button = page.ele("text:OK", timeout=1) or page.ele("text:Confirm", timeout=1)
    if button:
        button.click()
        time.sleep(0.2)
        return True
    return False

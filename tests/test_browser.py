from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from nol_ticket_bot import browser


class Options:
    def __init__(self) -> None:
        self.arguments: list[str] = []
        self.preferences: dict[str, Any] = {}
        self.browser_path = ""
        self.headless_enabled = False

    def set_argument(self, value: str) -> None:
        self.arguments.append(value)

    def set_pref(self, key: str, value: Any) -> None:
        self.preferences[key] = value

    def set_browser_path(self, value: str) -> None:
        self.browser_path = value

    def headless(self, value: bool) -> None:
        self.headless_enabled = value


class Page:
    def __init__(self, _options: Options | None = None) -> None:
        self.cdp_calls: list[tuple[str, dict[str, Any]]] = []
        self.elements: dict[str, Any] = {}

    def run_cdp(self, command: str, **kwargs: Any) -> dict[str, Any]:
        self.cdp_calls.append((command, kwargs))
        return {"result": {"value": True}}

    def ele(self, selector: str, timeout: float = 0) -> Any:
        return self.elements.get(selector)


class Button:
    def __init__(self) -> None:
        self.clicked = False

    def click(self) -> None:
        self.clicked = True


def test_create_browser_uses_dynamic_drission_import(monkeypatch: pytest.MonkeyPatch) -> None:
    module = SimpleNamespace(ChromiumOptions=Options, ChromiumPage=Page)
    monkeypatch.setattr(browser, "import_module", lambda _name: module)

    page = browser.create_browser()

    assert isinstance(page, Page)
    assert page.cdp_calls[0][0] == "Page.addScriptToEvaluateOnNewDocument"


def test_create_browser_reports_missing_drission(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(_name: str) -> Any:
        raise ModuleNotFoundError("DrissionPage")

    monkeypatch.setattr(browser, "import_module", missing)

    with pytest.raises(RuntimeError, match="DrissionPage is required"):
        browser.create_browser()


def test_cdp_eval_returns_value() -> None:
    assert browser.cdp_eval(Page(), "1 + 1") is True


def test_cdp_eval_returns_none_on_browser_error() -> None:
    class BrokenPage(Page):
        def run_cdp(self, command: str, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("browser died")

    assert browser.cdp_eval(BrokenPage(), "1 + 1") is None


def test_wait_for_element_returns_first_match() -> None:
    page = Page()
    marker = object()
    page.elements["css:.ready"] = marker

    assert browser.wait_for_element(page, "css:.ready", timeout=1) is marker


def test_wait_for_element_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    page = Page()
    times = iter([0.0, 2.0])
    monkeypatch.setattr(browser.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(browser.time, "sleep", lambda _seconds: None)

    with pytest.raises(TimeoutError):
        browser.wait_for_element(page, "css:.missing", timeout=1)


def test_dismiss_dialog_clicks_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    page = Page()
    button = Button()
    page.elements["text:OK"] = button
    monkeypatch.setattr(browser.time, "sleep", lambda _seconds: None)

    assert browser.dismiss_dialog(page)
    assert button.clicked

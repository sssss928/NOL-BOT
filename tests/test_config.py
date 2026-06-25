from __future__ import annotations

from pathlib import Path

import pytest

from nol_ticket_bot.config import Settings, SettingsError, resolve_env_path


def test_settings_from_env_validates_required_values() -> None:
    settings = Settings.from_env(
        {
            "GOODS_CODE": "26005973",
            "PLACE_CODE": "26000437",
            "BIZ_CODE": "10965",
            "MAX_TICKETS": "2",
            "POLL_INTERVAL": "1.5",
            "QUEUE_TIMEOUT": "600",
        }
    )

    assert settings.goods_code == "26005973"
    assert settings.max_tickets == 2
    assert settings.seat_grade_preference == ("VIP", "R", "S", "A")


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("GOODS_CODE", ""),
        ("PLACE_CODE", "bad value"),
        ("BIZ_CODE", "x/y"),
        ("MAX_TICKETS", "0"),
        ("POLL_INTERVAL", "0"),
        ("QUEUE_TIMEOUT", "0"),
    ],
)
def test_settings_rejects_invalid_values(key: str, value: str) -> None:
    env = {
        "GOODS_CODE": "26005973",
        "PLACE_CODE": "26000437",
        "BIZ_CODE": "10965",
        "MAX_TICKETS": "2",
        "POLL_INTERVAL": "1.5",
        "QUEUE_TIMEOUT": "600",
    }
    env[key] = value

    with pytest.raises(SettingsError):
        Settings.from_env(env)


def test_resolve_env_path_prefers_cwd_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("GOODS_CODE=abc\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert resolve_env_path() == dotenv.resolve()


def test_resolve_env_path_supports_explicit_file(tmp_path: Path) -> None:
    env_file = tmp_path / "custom.env"
    env_file.write_text("GOODS_CODE=abc\n", encoding="utf-8")

    assert resolve_env_path(env_file) == env_file.resolve()

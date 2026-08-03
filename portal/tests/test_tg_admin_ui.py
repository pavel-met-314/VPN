from __future__ import annotations

import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient
from telegram import KeyboardButton

from app.config import AppConfig, MtproxyConfig, PortalUser, TelegramConfig, TelegramPaymentConfig, VisitLogConfig, load_config
from app.telegram_bot import BTN_ADMIN_MINI_APP, _admin_keyboard, TelegramBotContext


def make_config(*, mini_app_url: str = "") -> AppConfig:
    user = PortalUser("user01", "hash", "user01@example.test", "User One")
    telegram = TelegramConfig(
        False,
        "test-token",
        "TestBot",
        frozenset({100}),
        Path("bot.db"),
        TelegramPaymentConfig(400, 30, ""),
        admin_mini_app_url=mini_app_url,
    )
    return AppConfig(
        "127.0.0.1", 3180, "vpn.test", "secret", Path("x.db"), "family",
        {user.username: user},
        VisitLogConfig(False, Path("access.log"), Path("visits.db"), 30, frozenset()),
        telegram, MtproxyConfig(False, "vpn.test", 8443, ""), (),
    )


class TelegramMiniAppUiTest(unittest.TestCase):
    def test_admin_keyboard_includes_web_app_button_only_when_configured(self) -> None:
        configured = _admin_keyboard(
            TelegramBotContext(make_config(mini_app_url="https://vpn.test/portal/tg-admin/"), Mock())
        )
        buttons = [button for row in configured.keyboard for button in row]
        mini_app_button = next(button for button in buttons if isinstance(button, KeyboardButton) and button.text == BTN_ADMIN_MINI_APP)
        self.assertEqual(mini_app_button.web_app.url, "https://vpn.test/portal/tg-admin/")

        disabled = _admin_keyboard(TelegramBotContext(make_config(), Mock()))
        self.assertNotIn(BTN_ADMIN_MINI_APP, [str(button) for row in disabled.keyboard for button in row])

    def test_config_loads_https_url_and_rejects_non_https_url(self) -> None:
        base = """
server: {host: 127.0.0.1, port: 3180}
public_address: vpn.test
session_secret: safe-secret
telegram:
  admin_mini_app_url: URL
users: []
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(base.replace("URL", "https://vpn.test/portal/tg-admin/"), encoding="utf-8")
            self.assertEqual(load_config(path).telegram.admin_mini_app_url, "https://vpn.test/portal/tg-admin/")
            path.write_text(base.replace("URL", "http://vpn.test/portal/tg-admin/"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                load_config(path)

    def test_mini_app_assets_do_not_contain_private_vpn_data(self) -> None:
        template = (Path(__file__).parents[1] / "templates" / "tg_admin.html").read_text(encoding="utf-8")
        self.assertIn("Откройте панель из Telegram-бота", template)
        source = (Path(__file__).parents[1] / "static" / "tg-admin.js").read_text(encoding="utf-8")
        self.assertIn('"X-Telegram-Init-Data"', source)
        self.assertIn('api("/me")', source)
        self.assertIn('"Idempotency-Key"', source)
        self.assertIn("themeParams", source)
        self.assertIn("Действие выполнено, но обновить данные не удалось", source)
        self.assertIn("await loadData();", source)
        self.assertIn('button.dataset.actionCompleted = "true"', source)
        self.assertIn('button.dataset.actionCompleted === "true"', source)
        for private_name in ("vless_link", "uuid", "bot_token", "subscription"):
            self.assertNotIn(private_name, source)

    @unittest.skipUnless(find_spec("qrcode") is not None, "qrcode is required to import the portal application")
    def test_mini_app_shell_route_returns_html(self) -> None:
        from app.main import app

        response = TestClient(app).get("/portal/tg-admin/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("tg-admin.js", response.text)

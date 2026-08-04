from __future__ import annotations

import asyncio
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi.testclient import TestClient
from telegram import InlineKeyboardMarkup, KeyboardButton

from app.config import AppConfig, MtproxyConfig, PortalUser, TelegramConfig, TelegramPaymentConfig, VisitLogConfig, load_config
from app.telegram_bot import (
    BTN_ADMIN_MINI_APP,
    TelegramBotContext,
    _admin_keyboard,
    _admin_mini_app_keyboard,
    cmd_admin_help,
    cmd_start,
)


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
    def test_admin_mini_app_uses_inline_button_and_reply_keyboard_has_no_web_app(self) -> None:
        bot_ctx = TelegramBotContext(
            make_config(mini_app_url="https://vpn.test/portal/tg-admin/"), Mock()
        )
        inline = _admin_mini_app_keyboard(bot_ctx)
        self.assertIsInstance(inline, InlineKeyboardMarkup)
        self.assertEqual(inline.inline_keyboard[0][0].text, BTN_ADMIN_MINI_APP)
        self.assertEqual(inline.inline_keyboard[0][0].web_app.url, "https://vpn.test/portal/tg-admin/")

        reply_buttons = [button for row in _admin_keyboard(bot_ctx).keyboard for button in row]
        self.assertEqual([button.text for button in reply_buttons], ["Список", "Справка админа", "Статус"])
        self.assertTrue(all(not isinstance(button, KeyboardButton) or button.web_app is None for button in reply_buttons))

    def test_empty_mini_app_url_does_not_create_inline_button(self) -> None:
        self.assertIsNone(_admin_mini_app_keyboard(TelegramBotContext(make_config(), Mock())))

    def test_start_and_admin_send_inline_button_only_to_admin(self) -> None:
        async def run() -> None:
            store = Mock()
            admin_ctx = TelegramBotContext(
                make_config(mini_app_url="https://vpn.test/portal/tg-admin/"), store
            )
            admin_message = SimpleNamespace(reply_text=AsyncMock())
            admin_update = SimpleNamespace(
                message=admin_message,
                effective_chat=SimpleNamespace(id=100),
            )
            admin_context = SimpleNamespace(
                args=[], application=SimpleNamespace(bot_data={"bot_ctx": admin_ctx})
            )
            await cmd_start(admin_update, admin_context)
            self.assertEqual(admin_message.reply_text.await_count, 2)
            self.assertIsInstance(admin_message.reply_text.await_args_list[1].kwargs["reply_markup"], InlineKeyboardMarkup)

            admin_message.reply_text.reset_mock()
            await cmd_admin_help(admin_update, admin_context)
            self.assertEqual(admin_message.reply_text.await_count, 2)

            user_message = SimpleNamespace(reply_text=AsyncMock())
            user_update = SimpleNamespace(
                message=user_message,
                effective_chat=SimpleNamespace(id=101),
            )
            await cmd_start(user_update, admin_context)
            self.assertEqual(user_message.reply_text.await_count, 1)
            self.assertNotIsInstance(user_message.reply_text.await_args.kwargs.get("reply_markup"), InlineKeyboardMarkup)

        asyncio.run(run())

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

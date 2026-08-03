from __future__ import annotations

import asyncio
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.admin_service import AdminActionResult, AdminServiceError
from app.config import AppConfig, MtproxyConfig, PortalUser, TelegramConfig, TelegramPaymentConfig, VisitLogConfig
from app.telegram_bot import TelegramBotContext, cmd_extend, cmd_free, cmd_pay, handle_admin_callback


def config() -> AppConfig:
    user = PortalUser("user01", "hash", "user01@example.test", "User One")
    telegram = TelegramConfig(False, "token", "TestBot", frozenset({100}), Path("bot.db"), TelegramPaymentConfig(400, 30, ""))
    return AppConfig("127.0.0.1", 3180, "vpn.test", "secret", Path("x.db"), "family", {"user01": user}, VisitLogConfig(False, Path("access.log"), Path("visits.db"), 30, frozenset()), telegram, MtproxyConfig(False, "vpn.test", 8443, ""), ())


def result(action: str, *, replayed: bool = False) -> AdminActionResult:
    return AdminActionResult(1, action, "user01", "user01@example.test", True, "active", 0, "без срока", 1 if "payment_request" in action else None, replayed, None)


def command_update(update_id: int = 1) -> tuple[SimpleNamespace, SimpleNamespace]:
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(
        update_id=update_id,
        message=message,
        effective_chat=SimpleNamespace(id=100),
        effective_user=SimpleNamespace(username="admin", full_name="Admin"),
    )
    context = SimpleNamespace(
        args=["user01"],
        application=SimpleNamespace(bot_data={}),
        bot=SimpleNamespace(send_message=AsyncMock()),
    )
    return update, context


class RecordingService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def require_payment(self, username: str, *, idempotency_key: str, **_: object) -> AdminActionResult:
        self.calls.append(("require_payment", idempotency_key))
        return result("require_payment", replayed=self.calls.count(("require_payment", idempotency_key)) > 1)

    def set_free(self, username: str, *, idempotency_key: str, **_: object) -> AdminActionResult:
        self.calls.append(("set_free", idempotency_key))
        return result("set_free")

    def extend_default_period(self, username: str, *, idempotency_key: str, **_: object) -> AdminActionResult:
        self.calls.append(("extend_30_days", idempotency_key))
        return result("extend_30_days")


class ConcurrentApproveService:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.extend_calls = 0

    def approve_payment_request(self, request_id: int, **_: object) -> AdminActionResult:
        with self.lock:
            if self.extend_calls:
                raise AdminServiceError("REQUEST_ALREADY_RESOLVED")
            self.extend_calls += 1
        return result("approve_payment_request")


def callback_update(update_id: int, request_id: int) -> tuple[SimpleNamespace, SimpleNamespace]:
    bot = SimpleNamespace(send_message=AsyncMock())
    query = SimpleNamespace(
        data=f"pay_ok:{request_id}",
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
        message=SimpleNamespace(text="Заявка", edit_text=AsyncMock()),
        get_bot=Mock(return_value=bot),
    )
    update = SimpleNamespace(
        update_id=update_id,
        callback_query=query,
        effective_user=SimpleNamespace(username="admin", full_name="Admin"),
    )
    return update, SimpleNamespace(application=SimpleNamespace(bot_data={}))


class TelegramAdminServiceAdapterTest(unittest.TestCase):
    def _bot_context(self) -> TelegramBotContext:
        store = Mock()
        store.get_link_by_username.return_value = None
        return TelegramBotContext(config(), store)

    def test_pay_free_and_extend_delegate_to_admin_service(self) -> None:
        service = RecordingService()
        bot_ctx = self._bot_context()
        with patch.object(TelegramBotContext, "admin_service", return_value=service):
            for handler, update_id in ((cmd_pay, 1), (cmd_free, 2), (cmd_extend, 3)):
                update, context = command_update(update_id)
                context.application.bot_data["bot_ctx"] = bot_ctx
                asyncio.run(handler(update, context))
        self.assertEqual([action for action, _ in service.calls], ["require_payment", "set_free", "extend_30_days"])

    def test_repeated_command_update_uses_the_same_idempotency_key(self) -> None:
        service = RecordingService()
        bot_ctx = self._bot_context()
        update, context = command_update(42)
        context.application.bot_data["bot_ctx"] = bot_ctx
        with patch.object(TelegramBotContext, "admin_service", return_value=service):
            asyncio.run(cmd_pay(update, context))
            asyncio.run(cmd_pay(update, context))
        self.assertEqual(service.calls[0][1], service.calls[1][1])

    def test_concurrent_approve_callbacks_only_extend_once(self) -> None:
        service = ConcurrentApproveService()
        bot_ctx = self._bot_context()
        first, first_context = callback_update(10, 7)
        second, second_context = callback_update(11, 7)
        first_context.application.bot_data["bot_ctx"] = bot_ctx
        second_context.application.bot_data["bot_ctx"] = bot_ctx

        async def run_callbacks() -> None:
            await asyncio.gather(
                handle_admin_callback(first, first_context),
                handle_admin_callback(second, second_context),
            )

        with patch.object(TelegramBotContext, "admin_service", return_value=service):
            asyncio.run(run_callbacks())
        self.assertEqual(service.extend_calls, 1)

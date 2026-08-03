from __future__ import annotations

import hashlib
import hmac
import json
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import urlencode

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin_service import AdminActionResult, AdminUserView
from app.config import AppConfig, MtproxyConfig, PortalUser, TelegramConfig, TelegramPaymentConfig, VisitLogConfig
from app.tg_admin import create_tg_admin_router


TOKEN = "test-token"
DEFAULT_STORE = object()


def config() -> AppConfig:
    user = PortalUser("user01", "hash", "user01@example.test", "User One")
    telegram = TelegramConfig(False, TOKEN, "", frozenset({100}), Path("bot.db"), TelegramPaymentConfig(400, 30, ""))
    return AppConfig("127.0.0.1", 3180, "vpn.test", "secret", Path("x.db"), "family", {user.username: user}, VisitLogConfig(False, Path("access.log"), Path("visits.db"), 30, frozenset()), telegram, MtproxyConfig(False, "vpn.test", 8443, ""), ())


def signed_header(user_id: int = 100) -> str:
    values = {"auth_date": str(int(time.time())), "user": json.dumps({"id": user_id, "first_name": "Admin"})}
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


class TgAdminApiTest(unittest.TestCase):
    def _client(
        self,
        service: Mock,
        *,
        store: Mock | None | object = DEFAULT_STORE,
        notifier: AsyncMock | None = None,
    ) -> TestClient:
        app = FastAPI()
        app.include_router(
            create_tg_admin_router(
                get_config=config,
                get_store=lambda: Mock() if store is DEFAULT_STORE else store,
                notify_user=notifier or AsyncMock(return_value=None),
            )
        )
        self.patch = patch("app.tg_admin.AdminService", return_value=service)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        return TestClient(app)

    def test_api_requires_valid_admin_and_idempotency_key(self) -> None:
        client = self._client(Mock())
        no_auth = client.get("/portal/api/tg-admin/me")
        self.assertEqual(no_auth.status_code, 401)
        self.assertEqual(no_auth.json()["error"]["code"], "MISSING_INIT_DATA")

        forbidden = client.get("/portal/api/tg-admin/me", headers={"X-Telegram-Init-Data": signed_header(101)})
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(forbidden.json()["error"]["code"], "NOT_ADMIN")

        response = client.post("/portal/api/tg-admin/users/user01/extend", headers={"X-Telegram-Init-Data": signed_header()})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_IDEMPOTENCY_KEY")

        invalid_status = client.get("/portal/api/tg-admin/payment-requests?status=processing", headers={"X-Telegram-Init-Data": signed_header()})
        self.assertEqual(invalid_status.status_code, 400)
        self.assertEqual(invalid_status.json()["error"]["code"], "INVALID_STATUS")

    def test_authentication_precedes_missing_store(self) -> None:
        client = self._client(Mock(), store=None)
        response = client.get("/portal/api/tg-admin/summary")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "MISSING_INIT_DATA")

    def test_read_responses_hide_private_fields_and_post_replays(self) -> None:
        service = Mock()
        service.list_users.return_value = [AdminUserView("user01", "User One", "user01@example.test", False, True, "active", 0, "без срока", 1, "1 B", None, None, None)]
        service.require_payment.return_value = AdminActionResult(7, "require_payment", "user01", "user01@example.test", True, "expired", 1, "now", None, True, None)
        notifier = AsyncMock(return_value=True)
        client = self._client(service, notifier=notifier)
        headers = {"X-Telegram-Init-Data": signed_header(), "Idempotency-Key": "a" * 16}

        users = client.get("/portal/api/tg-admin/users", headers=headers)
        self.assertEqual(users.status_code, 200)
        self.assertEqual(users.json()["items"][0]["client_email"], "user01@example.test")
        self.assertNotIn("vless_link", users.text)

        first = client.post("/portal/api/tg-admin/users/user01/require-payment", headers=headers)
        second = client.post("/portal/api/tg-admin/users/user01/require-payment", headers=headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()["replayed"])
        self.assertEqual(service.require_payment.call_count, 2)
        notifier.assert_not_awaited()

    def test_new_action_notifies_once(self) -> None:
        service = Mock()
        service.require_payment.return_value = AdminActionResult(7, "require_payment", "user01", "user01@example.test", True, "expired", 1, "now", None, False, None)
        notifier = AsyncMock(return_value=True)
        client = self._client(service, notifier=notifier)
        response = client.post(
            "/portal/api/tg-admin/users/user01/require-payment",
            headers={"X-Telegram-Init-Data": signed_header(), "Idempotency-Key": "a" * 16},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["notification_sent"])
        notifier.assert_awaited_once()

    def test_notifier_failure_preserves_successful_action(self) -> None:
        service = Mock()
        service.require_payment.return_value = AdminActionResult(7, "require_payment", "user01", "user01@example.test", True, "expired", 1, "now", None, False, None)
        notifier = AsyncMock(side_effect=RuntimeError("telegram unavailable"))
        client = self._client(service, notifier=notifier)
        response = client.post(
            "/portal/api/tg-admin/users/user01/require-payment",
            headers={"X-Telegram-Init-Data": signed_header(), "Idempotency-Key": "a" * 16},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["notification_sent"])

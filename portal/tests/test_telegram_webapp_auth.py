from __future__ import annotations

import hashlib
import hmac
import json
import unittest
from urllib.parse import urlencode

from app.telegram_webapp_auth import TelegramInitDataError, validate_admin_init_data


TOKEN = "test-token"
NOW = 1_700_000_000


def init_data(*, user_id: int = 100, auth_date: int = NOW, **extra: str) -> str:
    values = {
        "auth_date": str(auth_date),
        "query_id": "query",
        "user": json.dumps({"id": user_id, "first_name": "Admin", "username": "admin"}),
        **extra,
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


class TelegramWebAppAuthTest(unittest.TestCase):
    def test_valid_admin_init_data_returns_admin_principal(self) -> None:
        principal = validate_admin_init_data(
            init_data(), bot_token=TOKEN, admin_chat_ids=frozenset({100}), now_ts=NOW
        )
        self.assertEqual(principal.telegram_user_id, 100)
        self.assertEqual(principal.display_name, "Admin")

    def test_changed_signed_value_is_rejected(self) -> None:
        with self.assertRaisesRegex(TelegramInitDataError, "INVALID_SIGNATURE"):
            validate_admin_init_data(
                init_data().replace("Admin", "Intruder"),
                bot_token=TOKEN,
                admin_chat_ids=frozenset({100}),
                now_ts=NOW,
            )

    def test_expired_and_non_admin_init_data_are_rejected(self) -> None:
        with self.assertRaisesRegex(TelegramInitDataError, "AUTH_EXPIRED"):
            validate_admin_init_data(
                init_data(auth_date=NOW - 601),
                bot_token=TOKEN,
                admin_chat_ids=frozenset({100}),
                now_ts=NOW,
            )
        with self.assertRaisesRegex(TelegramInitDataError, "NOT_ADMIN"):
            validate_admin_init_data(
                init_data(user_id=101),
                bot_token=TOKEN,
                admin_chat_ids=frozenset({100}),
                now_ts=NOW,
            )

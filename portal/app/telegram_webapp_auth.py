"""Проверка исходной строки Telegram Web Apps initData."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Literal
from urllib.parse import parse_qsl

from app.admin_service import AdminPrincipal


class TelegramInitDataError(ValueError):
    def __init__(
        self,
        code: Literal[
            "MISSING_INIT_DATA",
            "INVALID_SIGNATURE",
            "INVALID_USER",
            "AUTH_EXPIRED",
            "NOT_ADMIN",
        ],
    ) -> None:
        super().__init__(code)
        self.code = code


def validate_admin_init_data(
    raw_init_data: str,
    *,
    bot_token: str,
    admin_chat_ids: frozenset[int],
    now_ts: int | None = None,
    max_age_seconds: int = 600,
) -> AdminPrincipal:
    """Проверяет подпись initData и возвращает авторизованного администратора."""
    if not raw_init_data:
        raise TelegramInitDataError("MISSING_INIT_DATA")

    pairs = parse_qsl(raw_init_data, keep_blank_values=True)
    hashes = [value for name, value in pairs if name == "hash"]
    if len(hashes) != 1:
        raise TelegramInitDataError("INVALID_SIGNATURE")

    data_pairs = [(name, value) for name, value in pairs if name != "hash"]
    data_check_string = "\n".join(
        f"{name}={value}" for name, value in sorted(data_pairs, key=lambda item: item[0])
    )
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, hashes[0]):
        raise TelegramInitDataError("INVALID_SIGNATURE")

    values = dict(data_pairs)
    try:
        user = json.loads(values["user"])
        user_id = user["id"]
        auth_date = int(values["auth_date"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise TelegramInitDataError("INVALID_USER") from None
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        raise TelegramInitDataError("INVALID_USER")

    current_ts = int(time.time()) if now_ts is None else now_ts
    age = current_ts - auth_date
    if age < -30 or age > max_age_seconds:
        raise TelegramInitDataError("AUTH_EXPIRED")
    if user_id not in admin_chat_ids:
        raise TelegramInitDataError("NOT_ADMIN")

    username = user.get("username")
    telegram_username = username if isinstance(username, str) and username else None
    display_name = " ".join(
        value for value in (user.get("first_name"), user.get("last_name"))
        if isinstance(value, str) and value
    )
    return AdminPrincipal(
        telegram_user_id=user_id,
        telegram_username=telegram_username,
        display_name=display_name or telegram_username or str(user_id),
        auth_date=auth_date,
    )

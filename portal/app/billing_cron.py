"""Автобиллинг: почасовой обход клиентов, требующих оплату.

Что делает:
- шлёт в Telegram напоминание «истекает через N дн.» (за SOON_DAYS до срока, один раз);
- шлёт «доступ приостановлен» после истечения (повтор раз в EXPIRED_RENUDGE_DAYS);
- страховка: если клиент просрочен, но в 3X-UI всё ещё enable=1 — выключает его.

Запуск (тем же пользователем/venv, что и портал):
    FAMILY_PORTAL_CONFIG=/etc/family-portal/config.yaml \
    /opt/family-portal/venv/bin/python -m app.billing_cron
"""

from __future__ import annotations

import logging
import math
import os
import sys
from datetime import datetime
from pathlib import Path

from app.config import AppConfig, PortalUser, load_config
from app.telegram_notify import send_telegram
from app.telegram_store import TelegramStore
from app.xui_admin import XuiAdmin, format_expiry_ms
from app.xui_db import GMT3, XuiDatabase

logger = logging.getLogger("family-portal.billing_cron")

DAY_MS = 24 * 60 * 60 * 1000
SOON_DAYS = 3
EXPIRED_RENUDGE_DAYS = 3
CONFIG_PATH = Path(os.environ.get("FAMILY_PORTAL_CONFIG", "/etc/family-portal/config.yaml"))


def _payment_block(config: AppConfig, user: PortalUser) -> str:
    payment = config.telegram.payment
    instructions = payment.instructions.replace("userXX", user.client_email)
    return (
        f"Тариф: {payment.amount_rub} ₽ / {payment.days} дн.\n"
        f"Твой код в комментарии: {user.client_email}\n\n"
        f"{instructions}\n\n"
        "Как оплатить: открой этого бота и нажми «Я оплатил»."
    )


def build_message(config: AppConfig, user: PortalUser, kind: str, expiry_ms: int, ms_left: int) -> str:
    expiry_str = format_expiry_ms(expiry_ms)
    if kind == "expired":
        head = f"⛔ Доступ к VPN приостановлен — срок оплаты истёк ({expiry_str})."
    else:
        days_left = max(1, math.ceil(ms_left / DAY_MS))
        head = f"⏳ Напоминание: доступ к VPN истекает через {days_left} дн. — до {expiry_str}."
    return f"{head}\n\n{_payment_block(config, user)}"


def run(config: AppConfig) -> int:
    token = config.telegram.bot_token
    if not token:
        logger.info("bot_token пуст — нечего делать")
        return 0

    store = TelegramStore(config.telegram.db_path)
    xui_ro = XuiDatabase(config.xui_db_path)
    xui_admin = XuiAdmin(config.xui_db_path)
    now_ms = int(datetime.now(GMT3).timestamp() * 1000)

    need_restart = False
    sent = 0

    for username, user in config.users.items():
        if not store.get_requires_payment(username):
            continue

        traffic = xui_ro.get_client_traffic(user.client_email)
        if traffic is None or traffic.expiry_time <= 0:
            continue  # срок не выставлен — пропускаем

        expiry_ms = traffic.expiry_time
        ms_left = expiry_ms - now_ms
        inbound_remark = user.inbound_remark or config.inbound_remark

        # Страховка: просрочен, но 3X-UI ещё не выключил — выключаем.
        if ms_left <= 0 and traffic.enable:
            try:
                xui_admin.disable_client(
                    inbound_remark=inbound_remark,
                    client_email=user.client_email,
                    restart=False,
                )
                need_restart = True
                logger.info("выключен просроченный клиент %s", user.client_email)
            except Exception:
                logger.exception("не удалось выключить %s", user.client_email)

        link = store.get_link_by_username(username)
        if link is None:
            continue  # Telegram не привязан — некуда слать

        if ms_left <= 0:
            kind, renudge = "expired", EXPIRED_RENUDGE_DAYS
        elif ms_left <= SOON_DAYS * DAY_MS:
            kind, renudge = "expiring_soon", None
        else:
            continue

        if not store.should_notify(username, kind, expiry_ms, renudge_days=renudge):
            continue

        text = build_message(config, user, kind, expiry_ms, ms_left)
        if send_telegram(token, link.chat_id, text):
            store.mark_notified(username, kind, expiry_ms)
            sent += 1

    if need_restart:
        try:
            xui_admin.restart_xui()
        except Exception:
            logger.exception("restart x-ui failed")

    logger.info("billing_cron готово: отправлено %d уведомлений", sent)
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        config = load_config(CONFIG_PATH)
    except Exception:
        logger.exception("не удалось загрузить конфиг %s", CONFIG_PATH)
        return 1
    return run(config)


if __name__ == "__main__":
    sys.exit(main())

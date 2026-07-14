"""Общая отправка сообщений в Telegram Bot API (без python-telegram-bot)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from app.config import AppConfig, load_config

logger = logging.getLogger("family-portal.telegram_notify")

CONFIG_PATH = Path(os.environ.get("FAMILY_PORTAL_CONFIG", "/etc/family-portal/config.yaml"))
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def send_telegram(token: str, chat_id: int, text: str) -> bool:
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    request = urllib.request.Request(TELEGRAM_API.format(token=token), data=data)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not payload.get("ok"):
            logger.warning("telegram sendMessage not ok: %s", payload)
            return False
        return True
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        logger.exception("telegram send failed for chat %s", chat_id)
        return False


def notify_admins(config: AppConfig, text: str) -> int:
    if not config.telegram.bot_token or not config.telegram.admin_chat_ids:
        logger.error("нужны telegram.bot_token и admin_chat_ids")
        return 0
    sent = 0
    for chat_id in config.telegram.admin_chat_ids:
        if send_telegram(config.telegram.bot_token, chat_id, text):
            sent += 1
    return sent


def main() -> int:
    parser = argparse.ArgumentParser(description="Отправить сообщение админам VPN")
    parser.add_argument("--text", required=True, help="Текст сообщения")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        config = load_config(CONFIG_PATH)
    except Exception:
        logger.exception("не удалось загрузить конфиг %s", CONFIG_PATH)
        return 1
    sent = notify_admins(config, args.text)
    logger.info("отправлено %d админам", sent)
    return 0 if sent else 1


if __name__ == "__main__":
    sys.exit(main())

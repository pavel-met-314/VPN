"""Minute health checks with Telegram outage/recovery alerts."""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.config import AppConfig, load_config
from app.telegram_notify import notify_admins

logger = logging.getLogger("family-portal.health_monitor")

CONFIG_PATH = Path(os.environ.get("FAMILY_PORTAL_CONFIG", "/etc/family-portal/config.yaml"))
STATE_PATH = Path(
    os.environ.get(
        "FAMILY_HEALTH_STATE",
        "/var/lib/family-portal/health-monitor.json",
    )
)
FAILURES_BEFORE_ALERT = 2


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def check_xui_service() -> CheckResult:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "x-ui"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CheckResult("x-ui", False, str(exc))
    status = (result.stdout or result.stderr).strip() or f"exit={result.returncode}"
    return CheckResult("x-ui", result.returncode == 0 and status == "active", status)


def check_tcp(host: str, port: int) -> CheckResult:
    try:
        with socket.create_connection((host, port), timeout=5):
            return CheckResult("Reality :443", True, f"{host}:{port} отвечает")
    except OSError as exc:
        return CheckResult("Reality :443", False, f"{host}:{port}: {exc}")


def check_portal(port: int) -> CheckResult:
    url = f"http://127.0.0.1:{port}/portal/login"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            code = response.status
    except urllib.error.HTTPError as exc:
        code = exc.code
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return CheckResult("Портал", False, str(exc))
    return CheckResult("Портал", code < 500, f"HTTP {code}")


def load_state() -> dict[str, object]:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return {"status": "unknown", "consecutive_failures": 0}


def save_state(state: dict[str, object]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    temporary.replace(STATE_PATH)


def run(config: AppConfig) -> int:
    if not config.telegram.bot_token or not config.telegram.admin_chat_ids:
        logger.error("для мониторинга нужны telegram.bot_token и admin_chat_ids")
        return 1

    checks = [
        check_xui_service(),
        check_tcp(config.public_address, 443),
        check_portal(config.port),
    ]
    failed = [check for check in checks if not check.ok]
    state = load_state()
    previous_status = str(state.get("status", "unknown"))
    failures = int(state.get("consecutive_failures", 0))
    now = datetime.now(timezone.utc).astimezone().strftime("%d.%m.%Y %H:%M:%S %Z")

    if failed:
        failures += 1
        details = "\n".join(f"• {check.name}: {check.detail}" for check in failed)
        if failures >= FAILURES_BEFORE_ALERT and previous_status != "down":
            sent = notify_admins(
                config,
                f"🚨 VPN: обнаружен сбой\nВремя: {now}\n{details}",
            )
            if sent:
                previous_status = "down"
        logger.warning("health check failed (%d/%d): %s", failures, FAILURES_BEFORE_ALERT, details)
    else:
        if previous_status == "down":
            sent = notify_admins(
                config,
                f"✅ VPN снова работает\nВремя: {now}\n"
                "• x-ui: active\n• Reality :443: отвечает\n• Портал: отвечает",
            )
            if sent:
                previous_status = "up"
        else:
            previous_status = "up"
        failures = 0
        logger.info("health check ok")

    save_state(
        {
            "status": previous_status,
            "consecutive_failures": failures,
            "checked_at": now,
            "checks": [
                {"name": check.name, "ok": check.ok, "detail": check.detail}
                for check in checks
            ],
        }
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-alert", action="store_true")
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

    if args.test_alert:
        if not config.telegram.bot_token or not config.telegram.admin_chat_ids:
            logger.error("для теста нужны telegram.bot_token и admin_chat_ids")
            return 1
        sent = notify_admins(config, "✅ Тест мониторинга VPN: Telegram-алерты работают.")
        logger.info("тест отправлен %d администраторам", sent)
        return 0 if sent else 1

    return run(config)


if __name__ == "__main__":
    sys.exit(main())

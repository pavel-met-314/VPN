from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.vless import parse_json_field

GMT3 = timezone(timedelta(hours=3))
MS_DAY = 24 * 60 * 60 * 1000
logger = logging.getLogger("family-portal.xui_admin")


@dataclass(frozen=True)
class ExtendResult:
    client_email: str
    expiry_ms: int
    expiry_display: str


def format_expiry_ms(expiry_ms: int) -> str:
    if expiry_ms <= 0:
        return "без срока"
    dt = datetime.fromtimestamp(expiry_ms / 1000, tz=GMT3)
    return dt.strftime("%d.%m.%Y %H:%M")


class XuiAdmin:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _write_client_expiry(
        self,
        *,
        inbound_remark: str,
        client_email: str,
        expiry_ms: int,
        enable: bool = True,
    ) -> ExtendResult:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, settings FROM inbounds WHERE remark = ? LIMIT 1
                """,
                (inbound_remark,),
            ).fetchone()
            if row is None:
                raise LookupError(f"Inbound '{inbound_remark}' не найден")

            inbound_id = int(row["id"])
            settings = parse_json_field(row["settings"])
            clients = settings.get("clients", [])
            if not isinstance(clients, list):
                raise LookupError("Некорректный список clients в inbound")

            client: dict[str, Any] | None = None
            for item in clients:
                if isinstance(item, dict) and item.get("email") == client_email:
                    client = item
                    break
            if client is None:
                raise LookupError(f"Клиент '{client_email}' не найден")

            client["expiryTime"] = int(expiry_ms)
            client["enable"] = bool(enable)

            conn.execute(
                "UPDATE inbounds SET settings = ? WHERE id = ?",
                (json.dumps(settings, ensure_ascii=False), inbound_id),
            )

            traffic_row = conn.execute(
                "SELECT email FROM client_traffics WHERE email = ? LIMIT 1",
                (client_email,),
            ).fetchone()
            enable_int = 1 if enable else 0
            if traffic_row is None:
                conn.execute(
                    """
                    INSERT INTO client_traffics (email, up, down, total, expiry_time, enable)
                    VALUES (?, 0, 0, 0, ?, ?)
                    """,
                    (client_email, int(expiry_ms), enable_int),
                )
            else:
                conn.execute(
                    """
                    UPDATE client_traffics
                    SET expiry_time = ?, enable = ?
                    WHERE email = ?
                    """,
                    (int(expiry_ms), enable_int, client_email),
                )
            conn.commit()

        return ExtendResult(
            client_email=client_email,
            expiry_ms=int(expiry_ms),
            expiry_display=format_expiry_ms(int(expiry_ms)),
        )

    def extend_client(
        self,
        *,
        inbound_remark: str,
        client_email: str,
        days: int,
        restart: bool = True,
    ) -> ExtendResult:
        if days <= 0:
            raise ValueError("days must be positive")

        now_ms = int(datetime.now(GMT3).timestamp() * 1000)
        add_ms = days * MS_DAY

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, settings FROM inbounds WHERE remark = ? LIMIT 1
                """,
                (inbound_remark,),
            ).fetchone()
            if row is None:
                raise LookupError(f"Inbound '{inbound_remark}' не найден")

            inbound_id = int(row["id"])
            settings = parse_json_field(row["settings"])
            clients = settings.get("clients", [])
            if not isinstance(clients, list):
                raise LookupError("Некорректный список clients в inbound")

            client: dict[str, Any] | None = None
            for item in clients:
                if isinstance(item, dict) and item.get("email") == client_email:
                    client = item
                    break
            if client is None:
                raise LookupError(f"Клиент '{client_email}' не найден")

            current_expiry = int(client.get("expiryTime") or 0)
            base_ms = max(now_ms, current_expiry) if current_expiry > 0 else now_ms
            new_expiry = base_ms + add_ms

            client["expiryTime"] = new_expiry
            client["enable"] = True

            conn.execute(
                "UPDATE inbounds SET settings = ? WHERE id = ?",
                (json.dumps(settings, ensure_ascii=False), inbound_id),
            )

            traffic_row = conn.execute(
                "SELECT email FROM client_traffics WHERE email = ? LIMIT 1",
                (client_email,),
            ).fetchone()
            if traffic_row is None:
                conn.execute(
                    """
                    INSERT INTO client_traffics (email, up, down, total, expiry_time, enable)
                    VALUES (?, 0, 0, 0, ?, 1)
                    """,
                    (client_email, new_expiry),
                )
            else:
                conn.execute(
                    """
                    UPDATE client_traffics
                    SET expiry_time = ?, enable = 1
                    WHERE email = ?
                    """,
                    (new_expiry, client_email),
                )
            conn.commit()

        result = ExtendResult(
            client_email=client_email,
            expiry_ms=new_expiry,
            expiry_display=format_expiry_ms(new_expiry),
        )
        if restart:
            self.restart_xui_background()
        return result

    def set_client_expiry(
        self,
        *,
        inbound_remark: str,
        client_email: str,
        expiry_ms: int,
        enable: bool = True,
        restart: bool = True,
    ) -> ExtendResult:
        """expiry_ms=0 → без срока (бесплатный доступ)."""
        result = self._write_client_expiry(
            inbound_remark=inbound_remark,
            client_email=client_email,
            expiry_ms=expiry_ms,
            enable=enable,
        )
        if restart:
            self.restart_xui_background()
        return result

    def expire_client_now(
        self,
        *,
        inbound_remark: str,
        client_email: str,
        restart: bool = True,
    ) -> ExtendResult:
        """Сразу истекший срок — VPN перестаёт пускать до продления."""
        now_ms = int(datetime.now(GMT3).timestamp() * 1000)
        return self.set_client_expiry(
            inbound_remark=inbound_remark,
            client_email=client_email,
            expiry_ms=now_ms - 1000,
            enable=True,
            restart=restart,
        )

    def clear_client_expiry(
        self,
        *,
        inbound_remark: str,
        client_email: str,
        restart: bool = True,
    ) -> ExtendResult:
        """Бесплатный доступ без срока."""
        return self.set_client_expiry(
            inbound_remark=inbound_remark,
            client_email=client_email,
            expiry_ms=0,
            enable=True,
            restart=restart,
        )

    def restart_xui(self) -> None:
        # -n: не ждать пароль (иначе HTTP-запрос висит → пустая страница в браузере)
        result = subprocess.run(
            ["sudo", "-n", "/bin/systemctl", "restart", "x-ui"],
            check=False,
            timeout=60,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"systemctl restart x-ui failed: {err or result.returncode}")

    def restart_xui_background(self) -> None:
        def _run() -> None:
            try:
                self.restart_xui()
            except Exception:
                logger.exception("background restart x-ui failed")

        threading.Thread(target=_run, name="restart-xui", daemon=True).start()

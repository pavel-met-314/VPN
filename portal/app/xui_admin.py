from __future__ import annotations

import json
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.vless import parse_json_field

GMT3 = timezone(timedelta(hours=3))
MS_DAY = 24 * 60 * 60 * 1000


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
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def extend_client(
        self,
        *,
        inbound_remark: str,
        client_email: str,
        days: int,
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

        self.restart_xui()
        return ExtendResult(
            client_email=client_email,
            expiry_ms=new_expiry,
            expiry_display=format_expiry_ms(new_expiry),
        )

    def restart_xui(self) -> None:
        subprocess.run(
            ["sudo", "/bin/systemctl", "restart", "x-ui"],
            check=True,
            timeout=120,
            capture_output=True,
        )

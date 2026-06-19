from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.vless import build_vless_link, parse_json_field


@dataclass(frozen=True)
class ClientLink:
    remark: str
    email: str
    uuid: str
    port: int
    vless_link: str


@dataclass(frozen=True)
class ClientTraffic:
    up: int
    down: int
    total_limit: int
    expiry_time: int
    last_online: int

    @property
    def used(self) -> int:
        return self.up + self.down

    @property
    def used_human(self) -> str:
        return format_bytes(self.used)

    @property
    def up_human(self) -> str:
        return format_bytes(self.up)

    @property
    def down_human(self) -> str:
        return format_bytes(self.down)

    @property
    def limit_human(self) -> str | None:
        if self.total_limit <= 0:
            return None
        return format_bytes(self.total_limit)

    @property
    def last_online_human(self) -> str | None:
        if self.last_online <= 0:
            return None
        ts = self.last_online / 1000 if self.last_online > 10_000_000_000 else self.last_online
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime("%d.%m.%Y %H:%M")


def format_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(max(value, 0))
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{value} B"


class XuiDatabase:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        uri = f"file:{self.db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def get_client_link(
        self,
        *,
        inbound_remark: str,
        client_email: str,
        public_address: str,
    ) -> ClientLink:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT remark, port, protocol, settings, stream_settings, enable
                FROM inbounds
                WHERE remark = ?
                LIMIT 1
                """,
                (inbound_remark,),
            ).fetchone()

        if row is None:
            raise LookupError(f"Inbound '{inbound_remark}' не найден")

        if not row["enable"]:
            raise LookupError(f"Inbound '{inbound_remark}' отключён")

        if str(row["protocol"]).lower() != "vless":
            raise LookupError("Поддерживается только VLESS")

        inbound_settings = parse_json_field(row["settings"])
        stream_settings = parse_json_field(row["stream_settings"])
        clients = inbound_settings.get("clients", [])
        if not isinstance(clients, list):
            raise LookupError("Некорректный список клиентов в inbound")

        client: dict[str, Any] | None = None
        for item in clients:
            if isinstance(item, dict) and item.get("email") == client_email:
                client = item
                break

        if client is None:
            raise LookupError(f"Клиент '{client_email}' не найден в inbound")

        if client.get("enable") is False:
            raise LookupError(f"Клиент '{client_email}' отключён")

        uuid = str(client.get("id", "")).strip()
        if not uuid:
            raise LookupError(f"У клиента '{client_email}' нет UUID")

        flow = str(client.get("flow", "") or "")
        port = int(row["port"])
        remark = f"{row['remark']}-{client_email}"

        link = build_vless_link(
            uuid=uuid,
            address=public_address,
            port=port,
            remark=remark,
            inbound_settings=inbound_settings,
            stream_settings=stream_settings,
            client_flow=flow,
        )

        return ClientLink(
            remark=remark,
            email=client_email,
            uuid=uuid,
            port=port,
            vless_link=link,
        )

    def get_client_traffic(self, client_email: str) -> ClientTraffic | None:
        with self._connect() as conn:
            try:
                row = conn.execute(
                    """
                    SELECT up, down, total, expiry_time, last_online
                    FROM client_traffics
                    WHERE email = ?
                    LIMIT 1
                    """,
                    (client_email,),
                ).fetchone()
            except sqlite3.OperationalError:
                return None

        if row is None:
            return None

        return ClientTraffic(
            up=int(row["up"] or 0),
            down=int(row["down"] or 0),
            total_limit=int(row["total"] or 0),
            expiry_time=int(row["expiry_time"] or 0),
            last_online=int(row["last_online"] or 0),
        )

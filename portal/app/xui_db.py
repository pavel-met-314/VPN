from __future__ import annotations

import sqlite3
from dataclasses import dataclass
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

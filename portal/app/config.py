from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class PortalUser:
    username: str
    password_hash: str
    client_email: str
    display_name: str
    inbound_remark: str | None = None


@dataclass(frozen=True)
class AppConfig:
    host: str
    port: int
    public_address: str
    session_secret: str
    xui_db_path: Path
    inbound_remark: str
    users: dict[str, PortalUser]


def load_config(path: str | Path) -> AppConfig:
    raw: dict[str, Any]
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    server = raw["server"]
    users: dict[str, PortalUser] = {}
    for item in raw.get("users", []):
        user = PortalUser(
            username=item["username"],
            password_hash=item["password_hash"],
            client_email=item["client_email"],
            display_name=item.get("display_name", item["username"]),
            inbound_remark=item.get("inbound_remark"),
        )
        users[user.username] = user

    secret = raw["session_secret"]
    if secret in ("", "CHANGE_ME_RANDOM_64_HEX"):
        raise ValueError("Задай session_secret в config.yaml")

    return AppConfig(
        host=server.get("host", "127.0.0.1"),
        port=int(server.get("port", 3180)),
        public_address=raw["public_address"],
        session_secret=secret,
        xui_db_path=Path(raw.get("xui_db_path", "/etc/x-ui/x-ui.db")),
        inbound_remark=raw.get("inbound_remark", "family-reality"),
        users=users,
    )

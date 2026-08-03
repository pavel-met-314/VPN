from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


@dataclass(frozen=True)
class PortalUser:
    username: str
    password_hash: str
    client_email: str
    display_name: str
    inbound_remark: str | None = None


@dataclass(frozen=True)
class VisitLogConfig:
    enabled: bool
    access_log_path: Path
    db_path: Path
    retention_days: int
    admin_usernames: frozenset[str]


@dataclass(frozen=True)
class TelegramPaymentConfig:
    amount_rub: int
    days: int
    instructions: str


@dataclass(frozen=True)
class TelegramConfig:
    enabled: bool
    bot_token: str
    bot_username: str
    admin_chat_ids: frozenset[int]
    db_path: Path
    payment: TelegramPaymentConfig
    link_token_ttl_seconds: int = 900
    admin_mini_app_url: str = ""


@dataclass(frozen=True)
class MtproxyConfig:
    enabled: bool
    host: str
    port: int
    secret: str


@dataclass(frozen=True)
class ExtraNode:
    """Запасной VLESS-узел (второй VPS) для Clash url-test."""

    name: str
    vless_link: str


@dataclass(frozen=True)
class AppConfig:
    host: str
    port: int
    public_address: str
    session_secret: str
    xui_db_path: Path
    inbound_remark: str
    users: dict[str, PortalUser]
    visit_log: VisitLogConfig
    telegram: TelegramConfig
    mtproxy: MtproxyConfig
    extra_nodes: tuple[ExtraNode, ...]


def _load_telegram_config(raw: dict[str, Any]) -> TelegramConfig:
    tg_raw = raw.get("telegram", {})
    if not isinstance(tg_raw, dict):
        tg_raw = {}

    payment_raw = tg_raw.get("payment", {})
    if not isinstance(payment_raw, dict):
        payment_raw = {}

    admin_ids = tg_raw.get("admin_chat_ids", [])
    if not isinstance(admin_ids, list):
        admin_ids = []

    admin_mini_app_url = str(tg_raw.get("admin_mini_app_url", "")).strip()
    if admin_mini_app_url:
        parsed_mini_app_url = urlparse(admin_mini_app_url)
        if (
            parsed_mini_app_url.scheme != "https"
            or not parsed_mini_app_url.netloc
            or parsed_mini_app_url.username is not None
            or parsed_mini_app_url.password is not None
            or parsed_mini_app_url.query
            or parsed_mini_app_url.fragment
        ):
            raise ValueError("telegram.admin_mini_app_url должен быть HTTPS URL без параметров")

    return TelegramConfig(
        enabled=bool(tg_raw.get("enabled", False)),
        bot_token=str(tg_raw.get("bot_token", "")).strip(),
        bot_username=str(tg_raw.get("bot_username", "")).strip().lstrip("@"),
        admin_chat_ids=frozenset(int(x) for x in admin_ids),
        db_path=Path(tg_raw.get("db_path", "/var/lib/family-portal/bot.db")),
        payment=TelegramPaymentConfig(
            amount_rub=int(payment_raw.get("amount_rub", 400)),
            days=int(payment_raw.get("days", 30)),
            instructions=str(payment_raw.get("instructions", "")).strip(),
        ),
        link_token_ttl_seconds=int(tg_raw.get("link_token_ttl_seconds", 900)),
        admin_mini_app_url=admin_mini_app_url,
    )


def _load_mtproxy_config(raw: dict[str, Any], *, public_address: str) -> MtproxyConfig:
    mt_raw = raw.get("mtproxy", {})
    if not isinstance(mt_raw, dict):
        mt_raw = {}

    host = str(mt_raw.get("host", "")).strip() or public_address
    secret = str(mt_raw.get("secret", "")).strip()

    config = MtproxyConfig(
        enabled=bool(mt_raw.get("enabled", False)),
        host=host,
        port=int(mt_raw.get("port", 8443)),
        secret=secret,
    )

    if config.enabled and not config.secret:
        raise ValueError("mtproxy.enabled=true, но secret пустой")

    return config


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

    visit_raw = raw.get("visit_log", {})
    admin_names = visit_raw.get("admin_usernames", [])
    if not isinstance(admin_names, list):
        admin_names = []

    telegram = _load_telegram_config(raw)
    if telegram.enabled and not telegram.bot_token:
        raise ValueError("telegram.enabled=true, но bot_token пустой")

    public_address = raw["public_address"]
    mtproxy = _load_mtproxy_config(raw, public_address=public_address)

    extra_nodes: list[ExtraNode] = []
    for item in raw.get("extra_nodes", []) or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        link = str(item.get("vless_link", "")).strip()
        if name and link.startswith("vless://"):
            extra_nodes.append(ExtraNode(name=name, vless_link=link))

    return AppConfig(
        host=server.get("host", "127.0.0.1"),
        port=int(server.get("port", 3180)),
        public_address=public_address,
        session_secret=secret,
        xui_db_path=Path(raw.get("xui_db_path", "/etc/x-ui/x-ui.db")),
        inbound_remark=raw.get("inbound_remark", "family-reality"),
        users=users,
        visit_log=VisitLogConfig(
            enabled=bool(visit_raw.get("enabled", False)),
            access_log_path=Path(visit_raw.get("access_log_path", "/var/log/x-ui/access.log")),
            db_path=Path(visit_raw.get("db_path", "/var/lib/family-portal/visits.db")),
            retention_days=int(visit_raw.get("retention_days", 30)),
            admin_usernames=frozenset(str(name) for name in admin_names),
        ),
        telegram=telegram,
        mtproxy=mtproxy,
        extra_nodes=tuple(extra_nodes),
    )

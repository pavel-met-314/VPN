from __future__ import annotations

import json
import urllib.parse
from typing import Any


def _first_string(value: Any) -> str:
    if isinstance(value, list) and value:
        first = value[0]
        return str(first) if first is not None else ""
    if isinstance(value, str):
        return value
    return ""


def _nested_map(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def build_vless_link(
    *,
    uuid: str,
    address: str,
    port: int,
    remark: str,
    inbound_settings: dict[str, Any],
    stream_settings: dict[str, Any],
    client_flow: str = "",
) -> str:
    """Генерация vless:// как в 3X-UI (sub/subService.go + panel inbound-link.ts)."""
    network = str(stream_settings.get("network", "tcp"))
    security = str(stream_settings.get("security", "none"))

    params: dict[str, str] = {"type": network}
    encryption = inbound_settings.get("encryption")
    if isinstance(encryption, str) and encryption:
        params["encryption"] = encryption

    if security == "reality":
        params["security"] = "reality"
        reality = _nested_map(stream_settings, "realitySettings")
        nested = _nested_map(reality, "settings")

        pbk = nested.get("publicKey") or reality.get("publicKey") or ""
        if pbk:
            params["pbk"] = str(pbk)

        sni = (
            nested.get("serverName")
            or _first_string(reality.get("serverNames"))
            or str(reality.get("target", "")).split(":")[0]
        )
        if sni:
            params["sni"] = str(sni)

        sid = _first_string(reality.get("shortIds"))
        if sid:
            params["sid"] = sid

        fp = nested.get("fingerprint")
        if isinstance(fp, str) and fp:
            params["fp"] = fp

        spx = nested.get("spiderX")
        if isinstance(spx, str) and spx:
            params["spx"] = spx

        if network == "tcp" and client_flow:
            params["flow"] = client_flow
    elif security == "tls":
        params["security"] = "tls"
        if network == "tcp" and client_flow:
            params["flow"] = client_flow
    else:
        params["security"] = "none"

    base = f"vless://{uuid}@{address}:{port}"
    query = urllib.parse.urlencode(params)
    fragment = urllib.parse.quote(remark, safe="")
    return f"{base}?{query}#{fragment}"


def parse_json_field(raw: str | bytes | None) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}

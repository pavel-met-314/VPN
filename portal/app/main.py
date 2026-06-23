from __future__ import annotations

import base64
import io
import json
import os
import urllib.parse
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import qrcode
import yaml
from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer

from app.auth import (
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    check_rate_limit,
    create_session_token,
    get_portal_user,
    read_session_user,
    verify_password,
)
from app.config import AppConfig, PortalUser, load_config
from app.xui_db import ClientLink, ClientTraffic, XuiDatabase

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("FAMILY_PORTAL_CONFIG", "/etc/family-portal/config.yaml"))

app = FastAPI(title="Family VPN Portal", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@lru_cache
def get_config() -> AppConfig:
    return load_config(CONFIG_PATH)


def get_serializer(config: AppConfig = Depends(get_config)) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(config.session_secret, salt="family-portal-v1")


def resolve_user(
    request: Request,
    config: AppConfig,
    serializer: URLSafeTimedSerializer,
) -> PortalUser | None:
    token = request.cookies.get(SESSION_COOKIE)
    username = read_session_user(serializer, token)
    return get_portal_user(config, username)


def make_qr_data_url(text: str) -> str:
    encoded = base64.b64encode(make_qr_png_bytes(text)).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def make_qr_png_bytes(text: str) -> bytes:
    img = qrcode.make(text, box_size=6, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def now_local_str() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%d.%m.%Y %H:%M:%S")


def get_hiddify_options() -> dict:
    # Эти настройки были проверены на LTE/4G (Hiddify) как рабочие.
    return {
        "region": "ru",
        "balancer-strategy": "round-robin",
        "block-ads": False,
        "use-xray-core-when-possible": False,
        "execute-config-as-is": False,
        "log-level": "warn",
        "resolve-destination": False,
        "ipv6-mode": "ipv4_only",
        "remote-dns-address": "https://dns.cloudflare.com/dns-query",
        "remote-dns-domain-strategy": "ipv4_only",
        "direct-dns-address": "1.1.1.1",
        "direct-dns-domain-strategy": "",
        "mixed-port": 12334,
        "tproxy-port": 12335,
        "direct-port": 12337,
        "redirect-port": 12336,
        "tun-implementation": "gvisor",
        "mtu": 1500,
        "strict-route": True,
        "connection-test-url": "http://captive.apple.com/hotspot-detect.html",
        "url-test-interval": 600,
        "enable-clash-api": True,
        "clash-api-port": 16756,
        "enable-tun": True,
        "set-system-proxy": False,
        "bypass-lan": False,
        "allow-connection-from-lan": False,
        "enable-fake-dns": False,
        "independent-dns-cache": True,
        "rules": [],
        "tls-tricks": {
            "enable-fragment": False,
            "fragment-size": "10-30",
            "fragment-sleep": "2-8",
            "mixed-sni-case": False,
            "enable-padding": False,
            "padding-size": "1-1500",
        },
        "warp": {
            "enable": False,
            "mode": "warp_over_proxy",
            "wireguard-config": "",
            "license-key": "",
            "account-id": "",
            "access-token": "",
            "clean-ip": "auto",
            "clean-port": 0,
            "noise": "1-3",
            "noise-size": "10-30",
            "noise-delay": "10-30",
            "noise-mode": "m4",
        },
        "warp2": {
            "enable": False,
            "mode": "warp_over_proxy",
            "wireguard-config": "",
            "license-key": "",
            "account-id": "",
            "access-token": "",
            "clean-ip": "auto",
            "clean-port": 0,
            "noise": "1-3",
            "noise-size": "10-30",
            "noise-delay": "10-30",
            "noise-mode": "m4",
        },
    }


def build_clash_yaml_from_vless_link(*, vless_link: str, profile_name: str) -> str:
    split = urllib.parse.urlsplit(vless_link)
    uuid = split.username or ""
    host = split.hostname or ""
    port = split.port or 443

    query = urllib.parse.parse_qs(split.query)
    params = {k: (v[0] if v else "") for k, v in query.items()}

    proxy_name = profile_name.strip() or urllib.parse.unquote(split.fragment or "") or "VPN"

    proxy: dict = {
        "name": proxy_name,
        "type": "vless",
        "server": host,
        "port": int(port),
        "uuid": uuid,
        "udp": True,
        "network": params.get("type") or "tcp",
        "tls": True,
        "servername": params.get("sni") or host,
        "client-fingerprint": params.get("fp") or "chrome",
        "skip-cert-verify": True,
        "encryption": params.get("encryption") or "",
    }

    flow = params.get("flow") or ""
    if flow:
        proxy["flow"] = flow

    pbk = params.get("pbk") or ""
    sid = params.get("sid") or ""
    if pbk:
        proxy["reality-opts"] = {"public-key": pbk}
        if sid:
            proxy["reality-opts"]["short-id"] = sid

    cfg: dict = {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "info",
        "ipv6": False,
        "proxies": [proxy],
        "proxy-groups": [
            {
                "name": "VPN",
                "type": "select",
                "proxies": [proxy_name, "DIRECT"],
            }
        ],
        "rules": ["MATCH,VPN"],
    }

    return yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False)


def require_user(
    request: Request,
    config: AppConfig,
    serializer: URLSafeTimedSerializer,
) -> PortalUser | RedirectResponse:
    user = resolve_user(request, config, serializer)
    if user is None:
        return RedirectResponse(url="/portal/login", status_code=303)
    return user


def resolve_inbound_remark(config: AppConfig, user: PortalUser) -> str:
    return user.inbound_remark or config.inbound_remark


def load_client_data(config: AppConfig, user: PortalUser) -> tuple[ClientLink, ClientTraffic | None]:
    db = XuiDatabase(config.xui_db_path)
    client = db.get_client_link(
        inbound_remark=resolve_inbound_remark(config, user),
        client_email=user.client_email,
        public_address=config.public_address,
    )
    traffic = db.get_client_traffic(user.client_email)
    return client, traffic


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/portal/login", response_class=HTMLResponse)
def login_page(request: Request, error: str | None = None) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": error},
    )


@app.post("/portal/login")
def login_submit(
    request: Request,
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
    config: AppConfig = Depends(get_config),
    serializer: URLSafeTimedSerializer = Depends(get_serializer),
) -> Response:
    check_rate_limit(request)
    user = config.users.get(username.strip())
    if user is None or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Неверный логин или пароль"},
            status_code=401,
        )

    token = create_session_token(serializer, user.username)
    redirect = RedirectResponse(url="/portal/", status_code=303)
    redirect.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/portal",
    )
    return redirect


@app.post("/portal/logout")
def logout() -> RedirectResponse:
    redirect = RedirectResponse(url="/portal/login", status_code=303)
    redirect.delete_cookie(SESSION_COOKIE, path="/portal")
    return redirect


@app.get("/portal/", response_class=HTMLResponse, response_model=None)
def dashboard(
    request: Request,
    refresh: int | None = None,
    config: AppConfig = Depends(get_config),
    serializer: URLSafeTimedSerializer = Depends(get_serializer),
) -> Response:
    user_or_redirect = require_user(request, config, serializer)
    if isinstance(user_or_redirect, RedirectResponse):
        return user_or_redirect
    user = user_or_redirect

    try:
        client, traffic = load_client_data(config, user)
    except LookupError as exc:
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "user": user,
                "message": str(exc),
            },
            status_code=500,
        )

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "client": client,
            "traffic": traffic,
            "qr_data_url": make_qr_data_url(client.vless_link),
            "updated_at": now_local_str(),
            "just_refreshed": refresh == 1,
        },
    )


@app.get("/portal/qr.png")
def download_qr(
    request: Request,
    config: AppConfig = Depends(get_config),
    serializer: URLSafeTimedSerializer = Depends(get_serializer),
) -> Response:
    user_or_redirect = require_user(request, config, serializer)
    if isinstance(user_or_redirect, RedirectResponse):
        return user_or_redirect
    user = user_or_redirect

    try:
        client, _ = load_client_data(config, user)
    except LookupError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    filename = f"vpn-{user.client_email}.png"
    return Response(
        content=make_qr_png_bytes(client.vless_link),
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/portal/hiddify/options.json")
def download_hiddify_options(
    request: Request,
    config: AppConfig = Depends(get_config),
    serializer: URLSafeTimedSerializer = Depends(get_serializer),
) -> Response:
    user_or_redirect = require_user(request, config, serializer)
    if isinstance(user_or_redirect, RedirectResponse):
        return user_or_redirect

    content = json.dumps(get_hiddify_options(), ensure_ascii=False, indent=2).encode("utf-8")
    return Response(
        content=content,
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="hiddify-options.json"',
            "Cache-Control": "no-store",
        },
    )


@app.get("/portal/clash.yaml")
def download_clash_yaml(
    request: Request,
    config: AppConfig = Depends(get_config),
    serializer: URLSafeTimedSerializer = Depends(get_serializer),
) -> Response:
    user_or_redirect = require_user(request, config, serializer)
    if isinstance(user_or_redirect, RedirectResponse):
        return user_or_redirect
    user = user_or_redirect

    try:
        client, _ = load_client_data(config, user)
    except LookupError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    content = build_clash_yaml_from_vless_link(vless_link=client.vless_link, profile_name=f"vpn-{client.email}")
    filename = f"vpn-{client.email}.yaml"
    return Response(
        content=content.encode("utf-8"),
        media_type="application/x-yaml; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )

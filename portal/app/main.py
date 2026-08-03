from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import urllib.parse
from contextlib import asynccontextmanager
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
    SESSION_REMEMBER_MAX_AGE,
    check_rate_limit,
    create_session_token,
    create_subscription_token,
    get_portal_user,
    get_subscription_serializer,
    read_session_user,
    read_subscription_user,
    verify_password,
)
from app.config import AppConfig, PortalUser, load_config
from app.telegram_bot import build_bot_application
from app.telegram_store import TelegramStore
from app.tg_admin import create_tg_admin_router
from app.visit_log import VisitLogStore, run_visit_log_ingest_loop
from app.xui_admin import XuiAdmin
from app.xui_db import ClientLink, ClientTraffic, XuiDatabase

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("FAMILY_PORTAL_CONFIG", "/etc/family-portal/config.yaml"))

_visit_store: VisitLogStore | None = None
_ingest_task: asyncio.Task[None] | None = None
_telegram_store: TelegramStore | None = None
_telegram_app = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _visit_store, _ingest_task, _telegram_store, _telegram_app
    config = load_config(CONFIG_PATH)
    if config.visit_log.enabled:
        _visit_store = VisitLogStore(
            db_path=config.visit_log.db_path,
            access_log_path=config.visit_log.access_log_path,
            retention_days=config.visit_log.retention_days,
        )
        _ingest_task = asyncio.create_task(run_visit_log_ingest_loop(_visit_store))
    _telegram_store = TelegramStore(config.telegram.db_path)
    if config.telegram.enabled:
        _telegram_app = build_bot_application(config, _telegram_store)
        await _telegram_app.initialize()
        await _telegram_app.start()
        await _telegram_app.updater.start_polling(drop_pending_updates=True)
    yield
    if _telegram_app is not None:
        await _telegram_app.updater.stop()
        await _telegram_app.stop()
        await _telegram_app.shutdown()
        _telegram_app = None
    _telegram_store = None
    if _ingest_task is not None:
        _ingest_task.cancel()
        try:
            await _ingest_task
        except asyncio.CancelledError:
            pass
    _ingest_task = None
    _visit_store = None


app = FastAPI(title="Family VPN Portal", docs_url=None, redoc_url=None, lifespan=lifespan)
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


def build_mtproxy_links(config: AppConfig) -> tuple[str, str]:
    query = urllib.parse.urlencode(
        {
            "server": config.mtproxy.host,
            "port": config.mtproxy.port,
            "secret": config.mtproxy.secret,
        }
    )
    return f"https://t.me/proxy?{query}", f"tg://proxy?{query}"


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


CLASH_RULES_RU_SPLIT = [
    "GEOSITE,private,DIRECT",
    "GEOSITE,ru,DIRECT",
    "GEOIP,private,DIRECT,no-resolve",
    "GEOIP,ru,DIRECT,no-resolve",
    "MATCH,VPN",
]


def _vless_link_to_clash_proxy(vless_link: str, proxy_name: str) -> dict:
    split = urllib.parse.urlsplit(vless_link)
    uuid = split.username or ""
    host = split.hostname or ""
    port = split.port or 443

    query = urllib.parse.parse_qs(split.query)
    params = {k: (v[0] if v else "") for k, v in query.items()}

    name = proxy_name.strip() or urllib.parse.unquote(split.fragment or "") or "VPN"
    proxy: dict = {
        "name": name,
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
    return proxy


def build_clash_yaml_from_vless_link(
    *,
    vless_link: str,
    profile_name: str,
    split_ru: bool = True,
    extra_nodes: tuple | list | None = None,
) -> str:
    primary = _vless_link_to_clash_proxy(vless_link, profile_name)
    proxies = [primary]
    node_names = [primary["name"]]

    for node in extra_nodes or ():
        name = getattr(node, "name", None) or (node.get("name") if isinstance(node, dict) else None)
        link = getattr(node, "vless_link", None) or (
            node.get("vless_link") if isinstance(node, dict) else None
        )
        if not name or not link:
            continue
        if name in node_names:
            continue
        proxies.append(_vless_link_to_clash_proxy(str(link), str(name)))
        node_names.append(str(name))

    proxy_groups: list[dict] = []
    if len(node_names) > 1:
        proxy_groups.append(
            {
                "name": "AUTO",
                "type": "url-test",
                "url": "http://www.gstatic.com/generate_204",
                "interval": 300,
                "tolerance": 50,
                "proxies": list(node_names),
            }
        )
        select_proxies = ["AUTO", *node_names, "DIRECT"]
    else:
        select_proxies = [node_names[0], "DIRECT"]

    proxy_groups.append(
        {
            "name": "VPN",
            "type": "select",
            "proxies": select_proxies,
        }
    )

    cfg: dict = {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "info",
        "ipv6": False,
        "profile-update-interval": 86400,
        "proxies": proxies,
        "proxy-groups": proxy_groups,
        "rules": CLASH_RULES_RU_SPLIT if split_ru else ["MATCH,VPN"],
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


def is_admin(config: AppConfig, user: PortalUser) -> bool:
    return user.username in config.visit_log.admin_usernames


def require_admin(
    request: Request,
    config: AppConfig,
    serializer: URLSafeTimedSerializer,
) -> PortalUser | RedirectResponse:
    user_or_redirect = require_user(request, config, serializer)
    if isinstance(user_or_redirect, RedirectResponse):
        return user_or_redirect
    if not is_admin(config, user_or_redirect):
        raise HTTPException(status_code=403, detail="Доступ только для администратора")
    return user_or_redirect


def client_display_names(config: AppConfig) -> dict[str, str]:
    names: dict[str, str] = {}
    for user in config.users.values():
        names[user.client_email] = user.display_name
    return names


def get_visit_store() -> VisitLogStore | None:
    return _visit_store


def get_telegram_store() -> TelegramStore | None:
    return _telegram_store


async def notify_telegram_user(username: str, text: str) -> bool | None:
    store = get_telegram_store()
    if store is None or _telegram_app is None:
        return None
    link = await asyncio.to_thread(store.get_link_by_username, username)
    if link is None:
        return None
    await _telegram_app.bot.send_message(chat_id=link.chat_id, text=text)
    return True


app.include_router(
    create_tg_admin_router(
        get_config=get_config,
        get_store=get_telegram_store,
        notify_user=notify_telegram_user,
    )
)


@app.get("/portal/tg-admin/", response_class=HTMLResponse, response_model=None)
def tg_admin_mini_app(request: Request) -> HTMLResponse:
    """HTML-оболочка Mini App; авторизация выполняется только Admin API."""
    return templates.TemplateResponse(request, "tg_admin.html", {})


def user_requires_payment(store: TelegramStore | None, username: str) -> bool:
    if store is None:
        return False
    return store.get_requires_payment(username)


def telegram_ui_enabled(config: AppConfig) -> bool:
    return config.telegram.enabled and bool(config.telegram.bot_username)


def billing_ui_enabled(config: AppConfig, *, requires_payment: bool) -> bool:
    return telegram_ui_enabled(config) and requires_payment


def build_telegram_connect_url(config: AppConfig, token: str) -> str:
    username = config.telegram.bot_username
    return f"https://t.me/{username}?start=link_{token}"


def is_disabled_client_error(exc: LookupError) -> bool:
    return "отключён" in str(exc)


def safe_get_traffic(config: AppConfig, user: PortalUser) -> ClientTraffic | None:
    try:
        return XuiDatabase(config.xui_db_path).get_client_traffic(user.client_email)
    except Exception:
        return None


def render_billing_blocked(
    request: Request,
    config: AppConfig,
    user: PortalUser,
    *,
    telegram_link_url: str | None = None,
) -> HTMLResponse:
    store = get_telegram_store()
    requires_payment = user_requires_payment(store, user.username)
    telegram_enabled = telegram_ui_enabled(config)
    payment_ui_enabled = billing_ui_enabled(config, requires_payment=requires_payment)
    telegram_linked = False
    if telegram_enabled and store is not None:
        telegram_linked = store.get_link_by_username(user.username) is not None

    return templates.TemplateResponse(
        request,
        "billing_blocked.html",
        {
            "user": user,
            "traffic": safe_get_traffic(config, user),
            "telegram_enabled": telegram_enabled,
            "payment_ui_enabled": payment_ui_enabled,
            "telegram_linked": telegram_linked,
            "telegram_bot_username": config.telegram.bot_username,
            "telegram_link_url": telegram_link_url,
            "payment_amount_rub": config.telegram.payment.amount_rub,
            "payment_days": config.telegram.payment.days,
            "payment_instructions": config.telegram.payment.instructions,
        },
        status_code=402,
    )


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


def resolve_subscription_user(config: AppConfig, token: str) -> PortalUser:
    sub_serializer = get_subscription_serializer(config.session_secret)
    username = read_subscription_user(sub_serializer, token)
    user = get_portal_user(config, username)
    if user is None:
        raise HTTPException(status_code=404, detail="Подписка не найдена")
    return user


def clash_profile_response(*, content: str, filename: str) -> Response:
    return Response(
        content=content.encode("utf-8"),
        media_type="application/x-yaml; charset=utf-8",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Profile-Update-Interval": "86400",
            "Subscription-Userinfo": "upload=0; download=0; total=1073741824; expire=0",
        },
    )


def hiddify_subscription_response(
    *,
    vless_link: str,
    extra_nodes: tuple | list | None = None,
) -> Response:
    # Hiddify / v2rayNG: классическая подписка = base64 со списком vless:// ссылок.
    lines = [vless_link]
    for node in extra_nodes or ():
        link = getattr(node, "vless_link", None) or (
            node.get("vless_link") if isinstance(node, dict) else None
        )
        if link:
            lines.append(str(link))
    body = base64.b64encode(("\n".join(lines) + "\n").encode("utf-8")).decode("ascii")
    return Response(
        content=body,
        media_type="text/plain; charset=utf-8",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'attachment; filename="subscription.txt"',
            "Profile-Update-Interval": "86400",
        },
    )


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
    remember: str | None = Form(None),
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

    remember_me = remember in ("on", "true", "1", "yes")
    token = create_session_token(serializer, user.username, remember=remember_me)
    cookie_max_age = SESSION_REMEMBER_MAX_AGE if remember_me else SESSION_MAX_AGE
    redirect = RedirectResponse(url="/portal/", status_code=303)
    redirect.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=cookie_max_age,
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
        if is_disabled_client_error(exc):
            return render_billing_blocked(request, config, user)
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "user": user,
                "message": str(exc),
            },
            status_code=500,
        )

    sub_serializer = get_subscription_serializer(config.session_secret)
    sub_token = create_subscription_token(sub_serializer, user.username)
    clash_profile_url = str(request.url_for("subscription_clash_yaml", token=sub_token))
    hiddify_subscription_url = (
        f"{request.url_for('subscription_clash', token=sub_token)}?format=hiddify"
    )

    payment_ui_enabled = billing_ui_enabled(
        config,
        requires_payment=user_requires_payment(_telegram_store, user.username),
    )
    telegram_enabled = telegram_ui_enabled(config)
    telegram_linked = False
    if telegram_enabled and _telegram_store is not None:
        telegram_linked = _telegram_store.get_link_by_username(user.username) is not None

    mtproxy_link, mtproxy_tg_link = ("", "")
    if config.mtproxy.enabled:
        mtproxy_link, mtproxy_tg_link = build_mtproxy_links(config)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "client": client,
            "traffic": traffic,
            "qr_data_url": make_qr_data_url(client.vless_link),
            "clash_profile_url": clash_profile_url,
            "hiddify_subscription_url": hiddify_subscription_url,
            "telegram_enabled": telegram_enabled,
            "payment_ui_enabled": payment_ui_enabled,
            "telegram_linked": telegram_linked,
            "telegram_bot_username": config.telegram.bot_username,
            "telegram_link_url": None,
            "payment_amount_rub": config.telegram.payment.amount_rub,
            "payment_days": config.telegram.payment.days,
            "mtproxy_enabled": config.mtproxy.enabled,
            "mtproxy_link": mtproxy_link,
            "mtproxy_tg_link": mtproxy_tg_link,
            "updated_at": now_local_str(),
            "just_refreshed": refresh == 1,
            "is_admin": is_admin(config, user),
        },
    )


@app.post("/portal/telegram/link", response_class=HTMLResponse, response_model=None)
def telegram_link_create(
    request: Request,
    config: AppConfig = Depends(get_config),
    serializer: URLSafeTimedSerializer = Depends(get_serializer),
) -> Response:
    user_or_redirect = require_user(request, config, serializer)
    if isinstance(user_or_redirect, RedirectResponse):
        return user_or_redirect
    user = user_or_redirect

    store = get_telegram_store()
    if store is None:
        raise HTTPException(status_code=503, detail="Telegram недоступен")

    if not telegram_ui_enabled(config):
        raise HTTPException(status_code=404, detail="Telegram-бот не настроен")

    token = store.create_link_token(
        user.username,
        ttl_seconds=config.telegram.link_token_ttl_seconds,
    )
    connect_url = build_telegram_connect_url(config, token)

    try:
        client, traffic = load_client_data(config, user)
    except LookupError as exc:
        if is_disabled_client_error(exc):
            return render_billing_blocked(request, config, user, telegram_link_url=connect_url)
        return templates.TemplateResponse(
            request,
            "error.html",
            {"user": user, "message": str(exc)},
            status_code=500,
        )

    sub_serializer = get_subscription_serializer(config.session_secret)
    sub_token = create_subscription_token(sub_serializer, user.username)
    clash_profile_url = str(request.url_for("subscription_clash_yaml", token=sub_token))
    hiddify_subscription_url = (
        f"{request.url_for('subscription_clash', token=sub_token)}?format=hiddify"
    )
    payment_ui_enabled = billing_ui_enabled(
        config,
        requires_payment=user_requires_payment(store, user.username),
    )

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "client": client,
            "traffic": traffic,
            "qr_data_url": make_qr_data_url(client.vless_link),
            "clash_profile_url": clash_profile_url,
            "hiddify_subscription_url": hiddify_subscription_url,
            "telegram_enabled": True,
            "payment_ui_enabled": payment_ui_enabled,
            "telegram_linked": store.get_link_by_username(user.username) is not None,
            "telegram_bot_username": config.telegram.bot_username,
            "telegram_link_url": connect_url,
            "payment_amount_rub": config.telegram.payment.amount_rub,
            "payment_days": config.telegram.payment.days,
            "mtproxy_enabled": config.mtproxy.enabled,
            "mtproxy_link": build_mtproxy_links(config)[0] if config.mtproxy.enabled else "",
            "mtproxy_tg_link": build_mtproxy_links(config)[1] if config.mtproxy.enabled else "",
            "updated_at": now_local_str(),
            "just_refreshed": False,
            "is_admin": is_admin(config, user),
        },
    )


@app.get("/portal/admin/visits", response_class=HTMLResponse, response_model=None)
def admin_visits(
    request: Request,
    days: int = 7,
    client: str | None = None,
    config: AppConfig = Depends(get_config),
    serializer: URLSafeTimedSerializer = Depends(get_serializer),
) -> Response:
    user_or_redirect = require_admin(request, config, serializer)
    if isinstance(user_or_redirect, RedirectResponse):
        return user_or_redirect
    user = user_or_redirect

    if days not in (1, 7, 14, 30):
        days = 7

    store = get_visit_store()
    summary = []
    top_hosts = []
    log_status = "выключено в config.yaml"
    if store is not None:
        log_status = "активно"
        client_email = client.strip() if client else None
        if client_email == "":
            client_email = None
        summary = store.get_summary(days=days, client_email=client_email, limit=300)
        top_hosts = store.get_top_hosts(days=days, client_email=client_email, limit=25)

    names = client_display_names(config)
    client_options = sorted(
        {(u.client_email, u.display_name) for u in config.users.values()},
        key=lambda item: item[1],
    )

    return templates.TemplateResponse(
        request,
        "admin_visits.html",
        {
            "user": user,
            "days": days,
            "selected_client": client or "",
            "client_options": client_options,
            "display_names": names,
            "summary": summary,
            "top_hosts": top_hosts,
            "log_status": log_status,
            "retention_days": config.visit_log.retention_days,
            "updated_at": now_local_str(),
        },
    )


@app.get("/portal/admin/billing", response_class=HTMLResponse, response_model=None)
def admin_billing(
    request: Request,
    saved: int | None = None,
    config: AppConfig = Depends(get_config),
    serializer: URLSafeTimedSerializer = Depends(get_serializer),
) -> Response:
    user_or_redirect = require_admin(request, config, serializer)
    if isinstance(user_or_redirect, RedirectResponse):
        return user_or_redirect
    user = user_or_redirect

    store = get_telegram_store()
    usernames = sorted(config.users.keys())
    policies: dict[str, bool] = {}
    if store is not None:
        policies = store.list_billing_policies(usernames)

    rows = [
        {
            "username": portal_user.username,
            "display_name": portal_user.display_name,
            "client_email": portal_user.client_email,
            "requires_payment": policies.get(portal_user.username, False),
        }
        for portal_user in sorted(config.users.values(), key=lambda u: u.display_name)
    ]

    return templates.TemplateResponse(
        request,
        "admin_billing.html",
        {
            "user": user,
            "rows": rows,
            "telegram_active": config.telegram.enabled and bool(config.telegram.bot_username),
            "payment_amount_rub": config.telegram.payment.amount_rub,
            "payment_days": config.telegram.payment.days,
            "just_saved": saved == 1,
            "updated_at": now_local_str(),
        },
    )


@app.post("/portal/admin/billing/{username}")
def admin_billing_set(
    request: Request,
    username: str,
    action: str = Form(...),
    config: AppConfig = Depends(get_config),
    serializer: URLSafeTimedSerializer = Depends(get_serializer),
) -> Response:
    user_or_redirect = require_admin(request, config, serializer)
    if isinstance(user_or_redirect, RedirectResponse):
        return user_or_redirect

    if username not in config.users:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if action not in ("require", "free"):
        raise HTTPException(status_code=400, detail="Некорректное действие")

    store = get_telegram_store()
    if store is None:
        raise HTTPException(status_code=503, detail="Сервис биллинга недоступен")

    target = config.users[username]
    inbound_remark = target.inbound_remark or config.inbound_remark
    xui = XuiAdmin(config.xui_db_path)
    requires = action == "require"
    try:
        if requires:
            # Сразу режем доступ: expiry = сейчас. Вернётся после оплаты + «+30 дней».
            xui.expire_client_now(
                inbound_remark=inbound_remark,
                client_email=target.client_email,
            )
        else:
            # Бесплатно: без срока.
            xui.clear_client_expiry(
                inbound_remark=inbound_remark,
                client_email=target.client_email,
            )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Не удалось обновить 3X-UI: {exc}") from exc

    store.set_requires_payment(username, requires)
    return RedirectResponse(url="/portal/admin/billing?saved=1", status_code=303)


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


@app.get("/portal/mtproxy-qr.png")
def download_mtproxy_qr(
    request: Request,
    config: AppConfig = Depends(get_config),
    serializer: URLSafeTimedSerializer = Depends(get_serializer),
) -> Response:
    user_or_redirect = require_user(request, config, serializer)
    if isinstance(user_or_redirect, RedirectResponse):
        return user_or_redirect

    if not config.mtproxy.enabled:
        raise HTTPException(status_code=404, detail="MTProto-прокси не настроен")

    https_link, _ = build_mtproxy_links(config)
    return Response(
        content=make_qr_png_bytes(https_link),
        media_type="image/png",
        headers={"Content-Disposition": 'attachment; filename="telegram-proxy.png"'},
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


@app.get("/portal/sub/{token}.yaml", name="subscription_clash_yaml")
def subscription_clash_yaml(
    token: str,
    config: AppConfig = Depends(get_config),
) -> Response:
    user = resolve_subscription_user(config, token)
    try:
        client, _ = load_client_data(config, user)
    except LookupError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    content = build_clash_yaml_from_vless_link(
        vless_link=client.vless_link,
        profile_name=f"vpn-{client.email}",
        split_ru=True,
        extra_nodes=config.extra_nodes,
    )
    return clash_profile_response(content=content, filename=f"vpn-{client.email}.yaml")


@app.get("/portal/sub/{token}", name="subscription_clash")
def subscription_clash(
    token: str,
    format: str | None = None,
    config: AppConfig = Depends(get_config),
) -> Response:
    user = resolve_subscription_user(config, token)
    try:
        client, _ = load_client_data(config, user)
    except LookupError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if format in ("hiddify", "links"):
        return hiddify_subscription_response(
            vless_link=client.vless_link,
            extra_nodes=config.extra_nodes,
        )

    content = build_clash_yaml_from_vless_link(
        vless_link=client.vless_link,
        profile_name=f"vpn-{client.email}",
        split_ru=True,
        extra_nodes=config.extra_nodes,
    )
    return clash_profile_response(content=content, filename=f"vpn-{client.email}.yaml")


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

    content = build_clash_yaml_from_vless_link(
        vless_link=client.vless_link,
        profile_name=f"vpn-{client.email}",
        split_ru=True,
        extra_nodes=config.extra_nodes,
    )
    filename = f"vpn-{client.email}.yaml"
    return Response(
        content=content.encode("utf-8"),
        media_type="application/x-yaml; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )

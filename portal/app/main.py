from __future__ import annotations

import base64
import io
import os
from functools import lru_cache
from pathlib import Path

import qrcode
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
from app.xui_db import XuiDatabase

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
    img = qrcode.make(text, box_size=6, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


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
    config: AppConfig = Depends(get_config),
    serializer: URLSafeTimedSerializer = Depends(get_serializer),
) -> Response:
    user = resolve_user(request, config, serializer)
    if user is None:
        return RedirectResponse(url="/portal/login", status_code=303)
    db = XuiDatabase(config.xui_db_path)
    try:
        client = db.get_client_link(
            inbound_remark=config.inbound_remark,
            client_email=user.client_email,
            public_address=config.public_address,
        )
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
            "qr_data_url": make_qr_data_url(client.vless_link),
        },
    )

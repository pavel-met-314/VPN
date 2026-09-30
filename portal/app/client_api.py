from __future__ import annotations

import hashlib
import hmac
import logging
import sqlite3
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.auth import hash_password, verify_password
from app.client_sessions import ACCESS_TTL, REFRESH_TTL, ClientSessionStore, SessionError
from app.config import AppConfig, PortalUser
from app.telegram_store import TelegramStore
from app.xui_db import XuiDatabase

logger = logging.getLogger(__name__)
_DUMMY_HASH = hash_password("not-a-real-account")
_attempts: dict[str, deque[float]] = defaultdict(deque)
_attempt_lock = threading.Lock()


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024)
    device_name: str = Field(min_length=1, max_length=100)


class RefreshBody(BaseModel):
    refresh_token: str = Field(min_length=40, max_length=200)


def _error(status_code: int, code: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code},
        headers={"Cache-Control": "no-store"},
    )


def _check_login_limit(ip: str, username: str) -> None:
    now = time.monotonic()
    with _attempt_lock:
        for key in (f"ip:{ip}", f"user:{username}"):
            window = _attempts[key]
            while window and now - window[0] >= 900:
                window.popleft()
            if len(window) >= 5:
                raise _error(429, "RATE_LIMITED")


def _record_login_failure(ip: str, username: str) -> None:
    now = time.monotonic()
    with _attempt_lock:
        _attempts[f"ip:{ip}"].append(now)
        _attempts[f"user:{username}"].append(now)


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise _error(401, "AUTH_REQUIRED")
    return authorization[7:]


def _require_https(request: Request) -> None:
    if request.url.scheme != "https":
        raise _error(403, "HTTPS_REQUIRED")


def _tokens(access: str, refresh: str) -> dict[str, str | int]:
    return {
        "access_token": access,
        "expires_in": ACCESS_TTL,
        "refresh_token": refresh,
        "refresh_expires_in": REFRESH_TTL,
    }


def _profile(config: AppConfig, user: PortalUser) -> dict:
    try:
        if TelegramStore(config.telegram.db_path).get_requires_payment(user.username):
            raise _error(403, "VPN_ACCESS_DENIED")
        xui = XuiDatabase(config.xui_db_path)
        traffic = xui.get_client_traffic(user.client_email)
        if traffic is None:
            raise _error(503, "PROFILE_UNAVAILABLE")
        if not traffic.enable or traffic.is_expired:
            raise _error(403, "VPN_ACCESS_DENIED")
        client = xui.get_client_link(
            inbound_remark=user.inbound_remark or config.inbound_remark,
            client_email=user.client_email,
            public_address=config.public_address,
        )
        link = urlsplit(client.vless_link)
        params = parse_qs(link.query, keep_blank_values=True)

        def field(name: str, default: str = "") -> str:
            return params.get(name, [default])[0]

        if (
            link.scheme != "vless" or not link.hostname or not link.port
            or not link.username or field("security") != "reality"
            or field("type") != "tcp" or not field("pbk") or not field("sni")
        ):
            raise ValueError("Unsupported client profile")
        profile_id = hmac.new(
            config.session_secret.encode(),
            f"profile-v1:{user.username}".encode(),
            hashlib.sha256,
        ).hexdigest()[:32]
        return {
            "schema_version": 1,
            "profile_id": profile_id,
            "server_id": "primary",
            "display_name": user.display_name,
            "expires_at_ms": max(0, traffic.expiry_time),
            "endpoint": {"address": link.hostname, "port": link.port},
            "vless": {
                "uuid": link.username,
                "encryption": field("encryption", "none"),
                "flow": field("flow") or None,
            },
            "reality": {
                "server_name": field("sni"),
                "public_key": field("pbk"),
                "short_id": field("sid"),
                "fingerprint": field("fp", "chrome"),
                "spider_x": field("spx") or None,
            },
            "policy": {"routing": "full_tunnel", "dns": "remote"},
        }
    except HTTPException:
        raise
    except LookupError as exc:
        if "отключён" in str(exc):
            raise _error(403, "VPN_ACCESS_DENIED") from None
        logger.warning("Client profile unavailable: %s", type(exc).__name__)
        raise _error(503, "PROFILE_UNAVAILABLE") from None
    except Exception as exc:
        logger.warning("Client profile unavailable: %s", type(exc).__name__)
        raise _error(503, "PROFILE_UNAVAILABLE") from None


def create_client_router(get_config: Callable[[], AppConfig]) -> APIRouter:
    router = APIRouter(
        prefix="/portal/api/client/v1", dependencies=[Depends(_require_https)]
    )

    @router.post("/sessions")
    def login(
        body: LoginBody,
        request: Request,
        response: Response,
        config: AppConfig = Depends(get_config),
    ) -> dict:
        response.headers["Cache-Control"] = "no-store"
        username = body.username.strip()
        ip = request.client.host if request.client else "unknown"
        _check_login_limit(ip, username)
        user = config.users.get(username)
        if not verify_password(body.password, user.password_hash if user else _DUMMY_HASH):
            _record_login_failure(ip, username)
            raise _error(401, "INVALID_CREDENTIALS")
        try:
            access, refresh = ClientSessionStore(config.telegram.db_path).create(
                username, body.device_name.strip()
            )
        except sqlite3.Error as exc:
            logger.warning("Client session store unavailable: %s", type(exc).__name__)
            raise _error(503, "PROFILE_UNAVAILABLE") from None
        return _tokens(access, refresh)

    @router.post("/sessions/refresh")
    def refresh(
        body: RefreshBody,
        response: Response,
        config: AppConfig = Depends(get_config),
    ) -> dict:
        response.headers["Cache-Control"] = "no-store"
        try:
            access, refresh_token = ClientSessionStore(config.telegram.db_path).refresh(
                body.refresh_token
            )
        except SessionError:
            raise _error(401, "AUTH_REQUIRED") from None
        except sqlite3.Error as exc:
            logger.warning("Client session store unavailable: %s", type(exc).__name__)
            raise _error(503, "PROFILE_UNAVAILABLE") from None
        return _tokens(access, refresh_token)

    @router.delete("/sessions/current", status_code=204)
    def logout(
        authorization: str | None = Header(default=None),
        config: AppConfig = Depends(get_config),
    ) -> Response:
        token = _bearer(authorization)
        ClientSessionStore(config.telegram.db_path).revoke(token)
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    @router.get("/profile")
    def get_profile(
        response: Response,
        authorization: str | None = Header(default=None),
        config: AppConfig = Depends(get_config),
    ) -> dict:
        response.headers["Cache-Control"] = "no-store"
        try:
            username = ClientSessionStore(config.telegram.db_path).username_for_access(
                _bearer(authorization)
            )
        except SessionError:
            raise _error(401, "AUTH_REQUIRED") from None
        except sqlite3.Error as exc:
            logger.warning("Client session store unavailable: %s", type(exc).__name__)
            raise _error(503, "PROFILE_UNAVAILABLE") from None
        user = config.users.get(username)
        if user is None:
            raise _error(401, "AUTH_REQUIRED")
        return _profile(config, user)

    return router

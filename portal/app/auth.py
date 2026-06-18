from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from passlib.context import CryptContext

from app.config import AppConfig, PortalUser

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SESSION_COOKIE = "family_portal_session"
SESSION_MAX_AGE = 60 * 60 * 12  # 12 часов

_login_attempts: dict[str, Deque[float]] = defaultdict(deque)
MAX_ATTEMPTS = 5
WINDOW_SECONDS = 15 * 60


def verify_password(plain: str, password_hash: str) -> bool:
    return pwd_context.verify(plain, password_hash)


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def check_rate_limit(request: Request) -> None:
    ip = _client_ip(request)
    now = time.time()
    attempts = _login_attempts[ip]
    while attempts and now - attempts[0] > WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Слишком много попыток. Подожди 15 минут.")
    attempts.append(now)


def create_session_token(serializer: URLSafeTimedSerializer, username: str) -> str:
    return serializer.dumps({"u": username})


def read_session_user(serializer: URLSafeTimedSerializer, token: str | None) -> str | None:
    if not token:
        return None
    try:
        data = serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    username = data.get("u")
    return username if isinstance(username, str) else None


def get_portal_user(config: AppConfig, username: str | None) -> PortalUser | None:
    if not username:
        return None
    return config.users.get(username)

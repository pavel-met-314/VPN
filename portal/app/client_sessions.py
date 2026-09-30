from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

ACCESS_TTL = 15 * 60
REFRESH_TTL = 30 * 24 * 60 * 60


class SessionError(ValueError):
    pass


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_token(session_id: str) -> str:
    return f"{session_id}.{secrets.token_urlsafe(32)}"


def _session_id(token: str) -> str:
    session_id, sep, secret = token.partition(".")
    if not sep or len(session_id) != 32 or not secret:
        raise SessionError("AUTH_REQUIRED")
    return session_id


class ClientSessionStore:
    """Отдельные отзывные сессии приложения в существующей SQLite бота."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS client_device_sessions (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    device_name TEXT NOT NULL,
                    access_hash TEXT NOT NULL,
                    access_expires_at INTEGER NOT NULL,
                    refresh_hash TEXT NOT NULL,
                    refresh_expires_at INTEGER NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS client_device_refresh_history (
                    session_id TEXT NOT NULL,
                    token_hash TEXT NOT NULL,
                    used_at INTEGER NOT NULL,
                    PRIMARY KEY (session_id, token_hash)
                )
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def create(self, username: str, device_name: str) -> tuple[str, str]:
        now = int(time.time())
        session_id = secrets.token_hex(16)
        access = _new_token(session_id)
        refresh = _new_token(session_id)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO client_device_sessions
                (id, username, device_name, access_hash, access_expires_at,
                 refresh_hash, refresh_expires_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id, username, device_name, _digest(access),
                    now + ACCESS_TTL, _digest(refresh), now + REFRESH_TTL,
                    now, now,
                ),
            )
        return access, refresh

    def username_for_access(self, token: str) -> str:
        session_id = _session_id(token)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT username, access_hash, access_expires_at, revoked
                FROM client_device_sessions WHERE id = ?
                """,
                (session_id,),
            ).fetchone()
        if (
            row is None or row["revoked"] or row["access_expires_at"] <= int(time.time())
            or not hmac.compare_digest(row["access_hash"], _digest(token))
        ):
            raise SessionError("AUTH_REQUIRED")
        return str(row["username"])

    def refresh(self, token: str) -> tuple[str, str]:
        session_id = _session_id(token)
        now = int(time.time())
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT refresh_hash, refresh_expires_at, revoked
                FROM client_device_sessions WHERE id = ?
                """,
                (session_id,),
            ).fetchone()
            if row is None or row["revoked"]:
                raise SessionError("AUTH_REQUIRED")
            if not hmac.compare_digest(row["refresh_hash"], _digest(token)):
                replay = conn.execute(
                    """
                    SELECT 1 FROM client_device_refresh_history
                    WHERE session_id = ? AND token_hash = ?
                    """,
                    (session_id, _digest(token)),
                ).fetchone()
                if replay is not None:
                    conn.execute(
                        "UPDATE client_device_sessions SET revoked = 1, updated_at = ? WHERE id = ?",
                        (now, session_id),
                    )
                    conn.commit()
                raise SessionError("AUTH_REQUIRED")
            if row["refresh_expires_at"] <= now:
                conn.execute(
                    "UPDATE client_device_sessions SET revoked = 1, updated_at = ? WHERE id = ?",
                    (now, session_id),
                )
                conn.commit()
                raise SessionError("AUTH_REQUIRED")
            access = _new_token(session_id)
            refresh = _new_token(session_id)
            conn.execute(
                """
                INSERT INTO client_device_refresh_history (session_id, token_hash, used_at)
                VALUES (?, ?, ?)
                """,
                (session_id, row["refresh_hash"], now),
            )
            conn.execute(
                """
                UPDATE client_device_sessions
                SET access_hash = ?, access_expires_at = ?,
                    refresh_hash = ?, refresh_expires_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    _digest(access), now + ACCESS_TTL, _digest(refresh),
                    now + REFRESH_TTL, now, session_id,
                ),
            )
        return access, refresh

    def revoke(self, access_token: str) -> None:
        session_id = _session_id(access_token)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE client_device_sessions SET revoked = 1, updated_at = ?
                WHERE id = ? AND access_hash = ?
                """,
                (int(time.time()), session_id, _digest(access_token)),
            )

    def revoke_session(self, session_id: str) -> None:
        """Административный отзыв утерянного устройства по ID сессии."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE client_device_sessions SET revoked = 1, updated_at = ? WHERE id = ?",
                (int(time.time()), session_id),
            )

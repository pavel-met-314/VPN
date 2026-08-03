from __future__ import annotations

import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Literal

GMT3 = timezone(timedelta(hours=3))


@dataclass(frozen=True)
class TelegramLink:
    username: str
    chat_id: int
    linked_at: str


@dataclass(frozen=True)
class PaymentRequest:
    id: int
    username: str
    client_email: str
    chat_id: int
    status: str
    created_at: str
    resolved_at: str | None
    admin_chat_id: int | None


@dataclass(frozen=True)
class AdminActionRecord:
    id: int
    idempotency_key: str
    admin_telegram_id: int
    action: str
    target_username: str
    payment_request_id: int | None
    status: Literal["processing", "succeeded", "failed"]
    result_json: str | None
    error_code: str | None
    created_at: str
    completed_at: str | None


class TelegramStoreError(RuntimeError):
    def __init__(self, code: Literal["REQUEST_BUSY", "IDEMPOTENCY_CONFLICT"]) -> None:
        super().__init__(code)
        self.code = code


class TelegramStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _now_iso(self) -> str:
        return datetime.now(GMT3).isoformat(timespec="seconds")

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS telegram_links (
                    username TEXT PRIMARY KEY,
                    chat_id INTEGER NOT NULL UNIQUE,
                    linked_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS link_tokens (
                    token TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS payment_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    client_email TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    admin_chat_id INTEGER
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS payment_requests_one_open_per_user
                ON payment_requests (username)
                WHERE status IN ('pending', 'processing')
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    admin_telegram_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    target_username TEXT NOT NULL,
                    payment_request_id INTEGER,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    error_code TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS billing_policy (
                    username TEXT PRIMARY KEY,
                    requires_payment INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS billing_notifications (
                    username TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    expiry_ms INTEGER NOT NULL,
                    sent_at TEXT NOT NULL,
                    PRIMARY KEY (username, kind)
                )
                """
            )
            conn.commit()

    def create_link_token(self, username: str, *, ttl_seconds: int) -> str:
        token = secrets.token_urlsafe(16)
        expires_at = (datetime.now(GMT3) + timedelta(seconds=ttl_seconds)).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute("DELETE FROM link_tokens WHERE username = ?", (username,))
            conn.execute(
                """
                INSERT INTO link_tokens (token, username, expires_at, used_at)
                VALUES (?, ?, ?, NULL)
                """,
                (token, username, expires_at),
            )
            conn.commit()
        return token

    def consume_link_token(self, token: str) -> str | None:
        now = datetime.now(GMT3)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT username, expires_at, used_at FROM link_tokens WHERE token = ?",
                (token,),
            ).fetchone()
            if row is None or row["used_at"] is not None:
                return None
            try:
                expires = datetime.fromisoformat(str(row["expires_at"]))
            except ValueError:
                return None
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=GMT3)
            if now > expires:
                return None
            username = str(row["username"])
            conn.execute(
                "UPDATE link_tokens SET used_at = ? WHERE token = ?",
                (self._now_iso(), token),
            )
            conn.commit()
        return username

    def link_telegram(self, username: str, chat_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM telegram_links WHERE chat_id = ?", (chat_id,))
            conn.execute(
                """
                INSERT INTO telegram_links (username, chat_id, linked_at)
                VALUES (?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    chat_id = excluded.chat_id,
                    linked_at = excluded.linked_at
                """,
                (username, chat_id, self._now_iso()),
            )
            conn.commit()

    def get_link_by_username(self, username: str) -> TelegramLink | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT username, chat_id, linked_at FROM telegram_links WHERE username = ?",
                (username,),
            ).fetchone()
        if row is None:
            return None
        return TelegramLink(
            username=str(row["username"]),
            chat_id=int(row["chat_id"]),
            linked_at=str(row["linked_at"]),
        )

    def get_link_by_chat_id(self, chat_id: int) -> TelegramLink | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT username, chat_id, linked_at FROM telegram_links WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        if row is None:
            return None
        return TelegramLink(
            username=str(row["username"]),
            chat_id=int(row["chat_id"]),
            linked_at=str(row["linked_at"]),
        )

    def create_payment_request(self, *, username: str, client_email: str, chat_id: int) -> int | None:
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO payment_requests (username, client_email, chat_id, status, created_at)
                    VALUES (?, ?, ?, 'pending', ?)
                    """,
                    (username, client_email, chat_id, self._now_iso()),
                )
                conn.commit()
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            # Частичный уникальный индекс гарантирует одну открытую заявку даже при гонке.
            if self.get_open_payment_request_for_user(username) is not None:
                return None
            raise

    @staticmethod
    def _payment_request_from_row(row: sqlite3.Row) -> PaymentRequest:
        return PaymentRequest(
            id=int(row["id"]),
            username=str(row["username"]),
            client_email=str(row["client_email"]),
            chat_id=int(row["chat_id"]),
            status=str(row["status"]),
            created_at=str(row["created_at"]),
            resolved_at=str(row["resolved_at"]) if row["resolved_at"] else None,
            admin_chat_id=int(row["admin_chat_id"]) if row["admin_chat_id"] is not None else None,
        )

    @staticmethod
    def _admin_action_from_row(row: sqlite3.Row) -> AdminActionRecord:
        return AdminActionRecord(
            id=int(row["id"]),
            idempotency_key=str(row["idempotency_key"]),
            admin_telegram_id=int(row["admin_telegram_id"]),
            action=str(row["action"]),
            target_username=str(row["target_username"]),
            payment_request_id=(
                int(row["payment_request_id"])
                if row["payment_request_id"] is not None
                else None
            ),
            status=str(row["status"]),
            result_json=str(row["result_json"]) if row["result_json"] is not None else None,
            error_code=str(row["error_code"]) if row["error_code"] is not None else None,
            created_at=str(row["created_at"]),
            completed_at=str(row["completed_at"]) if row["completed_at"] else None,
        )

    def _get_payment_request(self, conn: sqlite3.Connection, request_id: int) -> PaymentRequest | None:
        row = conn.execute(
            """
            SELECT id, username, client_email, chat_id, status, created_at, resolved_at, admin_chat_id
            FROM payment_requests WHERE id = ?
            """,
            (request_id,),
        ).fetchone()
        return self._payment_request_from_row(row) if row is not None else None

    def _get_admin_action_by_key(
        self, conn: sqlite3.Connection, idempotency_key: str
    ) -> AdminActionRecord | None:
        row = conn.execute(
            """
            SELECT id, idempotency_key, admin_telegram_id, action, target_username,
                   payment_request_id, status, result_json, error_code, created_at, completed_at
            FROM admin_actions WHERE idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()
        return self._admin_action_from_row(row) if row is not None else None

    def get_payment_request(self, request_id: int) -> PaymentRequest | None:
        with self._connect() as conn:
            return self._get_payment_request(conn, request_id)

    def list_payment_requests(
        self, *, status: str | None = None, limit: int = 100
    ) -> list[PaymentRequest]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        with self._connect() as conn:
            if status is None:
                rows = conn.execute(
                    """
                    SELECT id, username, client_email, chat_id, status, created_at, resolved_at, admin_chat_id
                    FROM payment_requests
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, username, client_email, chat_id, status, created_at, resolved_at, admin_chat_id
                    FROM payment_requests WHERE status = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (status, limit),
                ).fetchall()
        return [self._payment_request_from_row(row) for row in rows]

    def get_open_payment_request_for_user(self, username: str) -> PaymentRequest | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, username, client_email, chat_id, status, created_at, resolved_at, admin_chat_id
                FROM payment_requests
                WHERE username = ? AND status IN ('pending', 'processing')
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (username,),
            ).fetchone()
        return self._payment_request_from_row(row) if row is not None else None

    def claim_payment_request(
        self, request_id: int, *, admin_chat_id: int
    ) -> PaymentRequest | None:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE payment_requests
                SET status = 'processing', admin_chat_id = ?
                WHERE id = ? AND status = 'pending'
                """,
                (admin_chat_id, request_id),
            )
            if cursor.rowcount != 1:
                return None
            conn.commit()
            return self._get_payment_request(conn, request_id)

    def release_payment_request(self, request_id: int, *, admin_chat_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE payment_requests
                SET status = 'pending', admin_chat_id = NULL
                WHERE id = ? AND status = 'processing' AND admin_chat_id = ?
                """,
                (request_id, admin_chat_id),
            )
            conn.commit()
        return cursor.rowcount == 1

    def finalize_payment_request(
        self,
        request_id: int,
        *,
        from_status: Literal["pending", "processing"],
        status: Literal["approved", "rejected"],
        admin_chat_id: int,
    ) -> bool:
        if (from_status, status) == ("processing", "approved"):
            query = """
                UPDATE payment_requests
                SET status = ?, resolved_at = ?, admin_chat_id = ?
                WHERE id = ? AND status = 'processing' AND admin_chat_id = ?
            """
            parameters = (status, self._now_iso(), admin_chat_id, request_id, admin_chat_id)
        elif (from_status, status) == ("pending", "rejected"):
            query = """
                UPDATE payment_requests
                SET status = ?, resolved_at = ?, admin_chat_id = ?
                WHERE id = ? AND status = 'pending' AND admin_chat_id IS NULL
            """
            parameters = (status, self._now_iso(), admin_chat_id, request_id)
        else:
            return False
        with self._connect() as conn:
            cursor = conn.execute(query, parameters)
            conn.commit()
        return cursor.rowcount == 1

    def begin_admin_action(
        self,
        *,
        idempotency_key: str,
        admin_telegram_id: int,
        action: str,
        target_username: str,
        payment_request_id: int | None = None,
    ) -> tuple[AdminActionRecord, bool]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO admin_actions (
                    idempotency_key, admin_telegram_id, action, target_username,
                    payment_request_id, status, created_at
                ) VALUES (?, ?, ?, ?, ?, 'processing', ?)
                ON CONFLICT(idempotency_key) DO NOTHING
                """,
                (
                    idempotency_key,
                    admin_telegram_id,
                    action,
                    target_username,
                    payment_request_id,
                    self._now_iso(),
                ),
            )
            record = self._get_admin_action_by_key(conn, idempotency_key)
            if record is None:
                raise RuntimeError("admin action was not stored")
            if cursor.rowcount == 1:
                conn.commit()
                return record, True

            if (
                record.admin_telegram_id != admin_telegram_id
                or record.action != action
                or record.target_username != target_username
                or record.payment_request_id != payment_request_id
            ):
                raise TelegramStoreError("IDEMPOTENCY_CONFLICT")
            if record.status == "processing":
                raise TelegramStoreError("REQUEST_BUSY")
            return record, False

    def complete_admin_action(self, action_id: int, *, result_json: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE admin_actions
                SET status = 'succeeded', result_json = ?, error_code = NULL, completed_at = ?
                WHERE id = ? AND status = 'processing'
                """,
                (result_json, self._now_iso(), action_id),
            )
            conn.commit()

    def fail_admin_action(self, action_id: int, *, error_code: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE admin_actions
                SET status = 'failed', error_code = ?, result_json = NULL, completed_at = ?
                WHERE id = ? AND status = 'processing'
                """,
                (error_code, self._now_iso(), action_id),
            )
            conn.commit()

    def resolve_payment_request(
        self,
        request_id: int,
        *,
        status: str,
        admin_chat_id: int,
    ) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM payment_requests WHERE id = ?",
                (request_id,),
            ).fetchone()
            if row is None or str(row["status"]) != "pending":
                return False
            conn.execute(
                """
                UPDATE payment_requests
                SET status = ?, resolved_at = ?, admin_chat_id = ?
                WHERE id = ?
                """,
                (status, self._now_iso(), admin_chat_id, request_id),
            )
            conn.commit()
        return True

    def get_requires_payment(self, username: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT requires_payment FROM billing_policy WHERE username = ?",
                (username,),
            ).fetchone()
        if row is None:
            return False
        return bool(int(row["requires_payment"]))

    def set_requires_payment(self, username: str, requires_payment: bool) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO billing_policy (username, requires_payment, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    requires_payment = excluded.requires_payment,
                    updated_at = excluded.updated_at
                """,
                (username, 1 if requires_payment else 0, self._now_iso()),
            )
            conn.commit()

    def should_notify(
        self,
        username: str,
        kind: str,
        expiry_ms: int,
        *,
        renudge_days: int | None = None,
    ) -> bool:
        """True, если про этот срок ещё не слали (или пора повторить через renudge_days)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT expiry_ms, sent_at FROM billing_notifications WHERE username = ? AND kind = ?",
                (username, kind),
            ).fetchone()
        if row is None:
            return True
        # Новый платёжный цикл (админ продлил) — уведомляем заново.
        if int(row["expiry_ms"]) != int(expiry_ms):
            return True
        if renudge_days is not None:
            try:
                sent = datetime.fromisoformat(str(row["sent_at"]))
            except ValueError:
                return True
            if sent.tzinfo is None:
                sent = sent.replace(tzinfo=GMT3)
            if (datetime.now(GMT3) - sent).total_seconds() >= renudge_days * 86400:
                return True
        return False

    def mark_notified(self, username: str, kind: str, expiry_ms: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO billing_notifications (username, kind, expiry_ms, sent_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(username, kind) DO UPDATE SET
                    expiry_ms = excluded.expiry_ms,
                    sent_at = excluded.sent_at
                """,
                (username, kind, int(expiry_ms), self._now_iso()),
            )
            conn.commit()

    def list_billing_policies(self, usernames: list[str]) -> dict[str, bool]:
        if not usernames:
            return {}
        placeholders = ",".join("?" for _ in usernames)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT username, requires_payment FROM billing_policy WHERE username IN ({placeholders})",
                usernames,
            ).fetchall()
        policies = {str(row["username"]): bool(int(row["requires_payment"])) for row in rows}
        return {name: policies.get(name, False) for name in usernames}

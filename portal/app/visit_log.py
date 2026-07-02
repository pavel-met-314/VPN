from __future__ import annotations

import asyncio
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ACCESS_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+"
    r".*?accepted\s+(?:tcp|udp):(?P<host>[^:\s]+):\d+"
    r".*?\bemail:\s*(?P<email>\S+)",
    re.IGNORECASE,
)

SKIP_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
GMT3 = timezone(timedelta(hours=3))


def format_last_seen_gmt3(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str)
    except ValueError:
        return iso_str
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=GMT3)
    return dt.astimezone(GMT3).strftime("%d.%m.%Y %H:%M:%S")


@dataclass(frozen=True)
class VisitSummaryRow:
    client_email: str
    host: str
    day: str
    hit_count: int
    last_seen: str
    last_seen_display: str


@dataclass(frozen=True)
class TopHostRow:
    client_email: str
    host: str
    hit_count: int


def parse_access_log_line(line: str) -> tuple[str, str, datetime] | None:
    match = ACCESS_LINE_RE.search(line.strip())
    if not match:
        return None

    email = match.group("email").strip()
    host = match.group("host").strip().lower()
    if not email or not host or host in SKIP_HOSTS:
        return None

    ts_raw = match.group("ts")
    try:
        if "." in ts_raw:
            ts = datetime.strptime(ts_raw, "%Y/%m/%d %H:%M:%S.%f")
        else:
            ts = datetime.strptime(ts_raw, "%Y/%m/%d %H:%M:%S")
    except ValueError:
        return None

    # X-UI пишет access.log в локальном времени сервера (GMT+3), не в UTC.
    return email, host, ts.replace(tzinfo=GMT3)


class VisitLogStore:
    def __init__(self, *, db_path: Path, access_log_path: Path, retention_days: int) -> None:
        self.db_path = db_path
        self.access_log_path = access_log_path
        self.retention_days = retention_days
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS visit_daily (
                    client_email TEXT NOT NULL,
                    host TEXT NOT NULL,
                    day TEXT NOT NULL,
                    hit_count INTEGER NOT NULL DEFAULT 1,
                    last_seen TEXT NOT NULL,
                    PRIMARY KEY (client_email, host, day)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingest_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.commit()
        self._repair_timezone_once()

    def _repair_timezone_once(self) -> None:
        """Старые записи: access.log трактовали как UTC и лишний раз сдвигали в GMT+3."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM ingest_state WHERE key = 'tz_repaired_v1'",
            ).fetchone()
            if row is not None:
                return

            rows = conn.execute(
                "SELECT client_email, host, day, last_seen FROM visit_daily",
            ).fetchall()
            for item in rows:
                try:
                    dt = datetime.fromisoformat(str(item["last_seen"]))
                except ValueError:
                    continue
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=GMT3)
                fixed = (dt - timedelta(hours=3)).astimezone(GMT3).isoformat(timespec="seconds")
                conn.execute(
                    """
                    UPDATE visit_daily SET last_seen = ?
                    WHERE client_email = ? AND host = ? AND day = ?
                    """,
                    (fixed, item["client_email"], item["host"], item["day"]),
                )

            conn.execute(
                "INSERT INTO ingest_state (key, value) VALUES ('tz_repaired_v1', '1')",
            )
            conn.commit()

    def _get_offset(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM ingest_state WHERE key = 'offset'",
            ).fetchone()
        if row is None:
            if self.access_log_path.is_file():
                return self.access_log_path.stat().st_size
            return 0
        return int(row["value"])

    def _set_offset(self, offset: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ingest_state (key, value) VALUES ('offset', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(offset),),
            )
            conn.commit()

    def ingest_once(self) -> int:
        if not self.access_log_path.is_file():
            return 0

        offset = self._get_offset()
        file_size = self.access_log_path.stat().st_size
        if offset > file_size:
            offset = 0

        ingested = 0
        with self.access_log_path.open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(offset)
            while True:
                line = fh.readline()
                if not line:
                    break
                parsed = parse_access_log_line(line)
                if parsed is None:
                    continue
                email, host, ts = parsed
                self._upsert_visit(email, host, ts)
                ingested += 1
            self._set_offset(fh.tell())

        if ingested:
            self.purge_old()
        return ingested

    def _upsert_visit(self, client_email: str, host: str, ts: datetime) -> None:
        day = ts.astimezone(GMT3).date().isoformat()
        last_seen = ts.astimezone(GMT3).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO visit_daily (client_email, host, day, hit_count, last_seen)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(client_email, host, day) DO UPDATE SET
                    hit_count = hit_count + 1,
                    last_seen = CASE
                        WHEN excluded.last_seen > last_seen THEN excluded.last_seen
                        ELSE last_seen
                    END
                """,
                (client_email, host, day, last_seen),
            )
            conn.commit()

    def purge_old(self) -> None:
        cutoff = (date.today() - timedelta(days=self.retention_days)).isoformat()
        with self._connect() as conn:
            conn.execute("DELETE FROM visit_daily WHERE day < ?", (cutoff,))
            conn.commit()

    def list_days(self, *, days: int) -> list[str]:
        since = (date.today() - timedelta(days=days - 1)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT day FROM visit_daily
                WHERE day >= ?
                ORDER BY day DESC
                """,
                (since,),
            ).fetchall()
        return [str(row["day"]) for row in rows]

    def get_summary(
        self,
        *,
        days: int = 7,
        client_email: str | None = None,
        limit: int = 200,
    ) -> list[VisitSummaryRow]:
        since = (date.today() - timedelta(days=days - 1)).isoformat()
        query = """
            SELECT client_email, host, day, hit_count, last_seen
            FROM visit_daily
            WHERE day >= ?
        """
        params: list[str | int] = [since]
        if client_email:
            query += " AND client_email = ?"
            params.append(client_email)
        query += " ORDER BY last_seen DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            VisitSummaryRow(
                client_email=str(row["client_email"]),
                host=str(row["host"]),
                day=str(row["day"]),
                hit_count=int(row["hit_count"]),
                last_seen=str(row["last_seen"]),
                last_seen_display=format_last_seen_gmt3(str(row["last_seen"])),
            )
            for row in rows
        ]

    def get_top_hosts(
        self,
        *,
        days: int = 7,
        client_email: str | None = None,
        limit: int = 20,
    ) -> list[TopHostRow]:
        since = (date.today() - timedelta(days=days - 1)).isoformat()
        query = """
            SELECT client_email, host, SUM(hit_count) AS total_hits
            FROM visit_daily
            WHERE day >= ?
        """
        params: list[str | int] = [since]
        if client_email:
            query += " AND client_email = ?"
            params.append(client_email)
        query += """
            GROUP BY client_email, host
            ORDER BY total_hits DESC
            LIMIT ?
        """
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            TopHostRow(
                client_email=str(row["client_email"]),
                host=str(row["host"]),
                hit_count=int(row["total_hits"]),
            )
            for row in rows
        ]


async def run_visit_log_ingest_loop(store: VisitLogStore, *, interval_seconds: float = 3.0) -> None:
    import logging

    logger = logging.getLogger("family-portal.visit_log")
    while True:
        try:
            await asyncio.to_thread(store.ingest_once)
        except Exception:
            logger.exception("visit_log ingest failed")
        await asyncio.sleep(interval_seconds)

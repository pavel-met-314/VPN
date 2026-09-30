from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.xui_admin import XuiAdmin
from app.xui_db import XuiDatabase


class XuiAdminTests(unittest.TestCase):
    def test_set_free_enables_canonical_3x_ui_client(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "x-ui.db"
            self._create_database(database_path)

            traffic_before = XuiDatabase(database_path).get_client_traffic("user09")
            self.assertIsNotNone(traffic_before)
            self.assertFalse(traffic_before.enable)

            XuiAdmin(database_path).clear_client_expiry(
                inbound_remark="family-reality",
                client_email="user09",
                restart=False,
            )

            conn = sqlite3.connect(database_path)
            try:
                client = conn.execute(
                    "SELECT enable, expiry_time FROM clients WHERE email = 'user09'"
                ).fetchone()
            finally:
                conn.close()
            self.assertEqual(client, (1, 0))

            traffic = XuiDatabase(database_path).get_client_traffic("user09")
            self.assertIsNotNone(traffic)
            self.assertTrue(traffic.enable)
            self.assertEqual(traffic.expiry_time, 0)

    def test_extend_enables_canonical_3x_ui_client(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "x-ui.db"
            self._create_database(database_path)

            result = XuiAdmin(database_path).extend_client(
                inbound_remark="family-reality",
                client_email="user09",
                days=30,
                restart=False,
            )

            conn = sqlite3.connect(database_path)
            try:
                client = conn.execute(
                    "SELECT enable, expiry_time FROM clients WHERE email = 'user09'"
                ).fetchone()
            finally:
                conn.close()
            self.assertEqual(client, (1, result.expiry_ms))

    @staticmethod
    def _create_database(database_path: Path) -> None:
        conn = sqlite3.connect(database_path)
        try:
            conn.executescript(
                """
                CREATE TABLE inbounds (
                    id INTEGER PRIMARY KEY, remark TEXT, enable INTEGER, settings TEXT
                );
                CREATE TABLE client_traffics (
                    inbound_id INTEGER, email TEXT, up INTEGER, down INTEGER,
                    total INTEGER, expiry_time INTEGER, last_online INTEGER, enable INTEGER
                );
                CREATE TABLE clients (
                    id INTEGER PRIMARY KEY, email TEXT, enable INTEGER,
                    expiry_time INTEGER, updated_at INTEGER
                );
                """
            )
            conn.execute(
                "INSERT INTO inbounds VALUES (?, ?, ?, ?)",
                (
                    1,
                    "family-reality",
                    1,
                    json.dumps({"clients": [{"email": "user09", "enable": False}]}),
                ),
            )
            conn.execute(
                "INSERT INTO client_traffics VALUES (?, ?, 0, 0, 0, 1, 0, 0)",
                (1, "user09"),
            )
            conn.execute(
                "INSERT INTO clients VALUES (?, ?, 0, 1, 0)",
                (9, "user09"),
            )
            conn.commit()
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()

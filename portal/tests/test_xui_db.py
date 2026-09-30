from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.xui_db import XuiDatabase


class XuiDatabaseTests(unittest.TestCase):
    def test_client_disabled_in_inbound_settings_is_not_active(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "x-ui.db"
            conn = sqlite3.connect(database_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE client_traffics (
                        email TEXT, up INTEGER, down INTEGER, total INTEGER,
                        expiry_time INTEGER, last_online INTEGER, enable INTEGER
                    )
                    """
                )
                conn.execute(
                    "CREATE TABLE inbounds (enable INTEGER, settings TEXT)"
                )
                conn.execute(
                    """
                    INSERT INTO client_traffics
                    VALUES ('user09', 0, 0, 0, 0, 0, 1)
                    """
                )
                conn.execute(
                    "INSERT INTO inbounds VALUES (?, ?)",
                    (
                        1,
                        json.dumps(
                            {"clients": [{"email": "user09", "enable": False}]}
                        ),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            traffic = XuiDatabase(database_path).get_client_traffic("user09")

        self.assertIsNotNone(traffic)
        self.assertFalse(traffic.enable)


if __name__ == "__main__":
    unittest.main()

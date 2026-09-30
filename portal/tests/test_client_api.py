from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import hash_password
from app.client_api import create_client_router
from app.client_sessions import ClientSessionStore, SessionError
from app.config import PortalUser
from app.xui_db import ClientLink, ClientTraffic


class ClientSessionTests(unittest.TestCase):
    def test_rotation_and_replay_revokes_device(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ClientSessionStore(Path(directory) / "bot.db")
            access, refresh = store.create("alice", "Test phone")
            self.assertEqual(store.username_for_access(access), "alice")
            next_access, next_refresh = store.refresh(refresh)
            self.assertNotEqual(refresh, next_refresh)
            self.assertEqual(store.username_for_access(next_access), "alice")
            with self.assertRaises(SessionError):
                store.refresh(next_refresh.partition(".")[0] + ".invalid")
            self.assertEqual(store.username_for_access(next_access), "alice")
            with self.assertRaises(SessionError):
                store.refresh(refresh)
            with self.assertRaises(SessionError):
                store.username_for_access(next_access)


class ClientApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        users = {
            name: PortalUser(
                username=name,
                password_hash=hash_password("test-password"),
                client_email=f"{name}-client",
                display_name=name.title(),
            )
            for name in ("alice", "bob")
        }
        self.config = SimpleNamespace(
            users=users,
            telegram=SimpleNamespace(db_path=Path(self.directory.name) / "bot.db"),
            xui_db_path=Path(self.directory.name) / "x-ui.db",
            public_address="vpn.example",
            inbound_remark="family",
            session_secret="test-only-secret",
        )
        app = FastAPI()
        app.include_router(create_client_router(lambda: self.config))
        self.client = TestClient(app, base_url="https://testserver")
        self.patch_xui = patch("app.client_api.XuiDatabase", FakeXuiDatabase)
        self.patch_xui.start()
        self.addCleanup(self.patch_xui.stop)

    def login(self, username: str) -> str:
        response = self.client.post(
            "/portal/api/client/v1/sessions",
            json={
                "username": username,
                "password": "test-password",
                "device_name": "Test phone",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        return response.json()["access_token"]

    def test_each_account_receives_only_its_own_profile(self) -> None:
        for username in ("alice", "bob"):
            token = self.login(username)
            response = self.client.get(
                "/portal/api/client/v1/profile",
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["vless"]["uuid"], f"{username}-uuid")
            self.assertNotIn("client_email", response.json())
            self.assertNotIn("vless://", response.text)

    def test_logout_and_invalid_login(self) -> None:
        response = self.client.post(
            "/portal/api/client/v1/sessions",
            json={
                "username": "alice",
                "password": "wrong",
                "device_name": "Test phone",
            },
        )
        self.assertEqual(response.status_code, 401)
        token = self.login("alice")
        self.assertEqual(
            self.client.delete(
                "/portal/api/client/v1/sessions/current",
                headers={"Authorization": f"Bearer {token}"},
            ).status_code,
            204,
        )
        response = self.client.get(
            "/portal/api/client/v1/profile",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 401)

    def test_billing_block_prevents_profile_delivery(self) -> None:
        token = self.login("alice")
        with patch("app.client_api.TelegramStore.get_requires_payment", return_value=True):
            response = self.client.get(
                "/portal/api/client/v1/profile",
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"]["code"], "VPN_ACCESS_DENIED")

    def test_http_login_is_rejected(self) -> None:
        app = FastAPI()
        app.include_router(create_client_router(lambda: self.config))
        response = TestClient(app).post(
            "/portal/api/client/v1/sessions",
            json={
                "username": "alice",
                "password": "test-password",
                "device_name": "Test phone",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"]["code"], "HTTPS_REQUIRED")


class FakeXuiDatabase:
    def __init__(self, db_path: Path) -> None:
        pass

    def get_client_traffic(self, client_email: str) -> ClientTraffic:
        return ClientTraffic(up=0, down=0, total_limit=0, expiry_time=0, last_online=0)

    def get_client_link(
        self, *, inbound_remark: str, client_email: str, public_address: str
    ) -> ClientLink:
        name = client_email.removesuffix("-client")
        return ClientLink(
            remark="family",
            email=client_email,
            uuid=f"{name}-uuid",
            port=443,
            vless_link=(
                f"vless://{name}-uuid@vpn.example:443?"
                "type=tcp&security=reality&pbk=public-key&sni=example.com&sid=abcd&fp=chrome"
            ),
        )


if __name__ == "__main__":
    unittest.main()

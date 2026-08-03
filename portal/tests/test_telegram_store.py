from __future__ import annotations

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.telegram_store import TelegramStore, TelegramStoreError


class TelegramStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "bot.db"
        self.store = TelegramStore(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_request(self) -> int:
        request_id = self.store.create_payment_request(
            username="user01",
            client_email="user01@example.test",
            chat_id=1001,
        )
        self.assertIsNotNone(request_id)
        return int(request_id)

    def test_only_one_admin_can_claim_payment_request(self) -> None:
        request_id = self._create_request()
        barrier = threading.Barrier(2)

        def claim(admin_chat_id: int):
            store = TelegramStore(self.db_path)
            barrier.wait()
            return store.claim_payment_request(request_id, admin_chat_id=admin_chat_id)

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(claim, (2001, 2002)))

        winners = [request for request in results if request is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0].status, "processing")
        self.assertIn(winners[0].admin_chat_id, (2001, 2002))

    def test_cannot_create_second_open_request_while_processing(self) -> None:
        request_id = self._create_request()
        self.assertIsNotNone(self.store.claim_payment_request(request_id, admin_chat_id=2001))

        duplicate = self.store.create_payment_request(
            username="user01",
            client_email="user01@example.test",
            chat_id=1001,
        )

        self.assertIsNone(duplicate)

    def test_repeated_idempotency_key_returns_completed_action(self) -> None:
        record, created = self.store.begin_admin_action(
            idempotency_key="4e5afe96-6c41-4f4a-b7e3-5cf2a9074010",
            admin_telegram_id=2001,
            action="extend_30_days",
            target_username="user01",
        )
        self.assertTrue(created)
        self.store.complete_admin_action(record.id, result_json='{"action_id": 1}')

        replay, created_again = self.store.begin_admin_action(
            idempotency_key="4e5afe96-6c41-4f4a-b7e3-5cf2a9074010",
            admin_telegram_id=2001,
            action="extend_30_days",
            target_username="user01",
        )

        self.assertFalse(created_again)
        self.assertEqual(replay.id, record.id)
        self.assertEqual(replay.status, "succeeded")
        self.assertEqual(replay.result_json, '{"action_id": 1}')

    def test_idempotency_key_conflict_is_rejected_before_status_handling(self) -> None:
        self.store.begin_admin_action(
            idempotency_key="4e5afe96-6c41-4f4a-b7e3-5cf2a9074011",
            admin_telegram_id=2001,
            action="extend_30_days",
            target_username="user01",
        )

        with self.assertRaisesRegex(TelegramStoreError, "IDEMPOTENCY_CONFLICT") as context:
            self.store.begin_admin_action(
                idempotency_key="4e5afe96-6c41-4f4a-b7e3-5cf2a9074011",
                admin_telegram_id=2002,
                action="extend_30_days",
                target_username="user01",
            )

        self.assertEqual(context.exception.code, "IDEMPOTENCY_CONFLICT")

    def test_processing_admin_action_is_reported_as_busy(self) -> None:
        self.store.begin_admin_action(
            idempotency_key="4e5afe96-6c41-4f4a-b7e3-5cf2a9074012",
            admin_telegram_id=2001,
            action="extend_30_days",
            target_username="user01",
        )

        with self.assertRaisesRegex(TelegramStoreError, "REQUEST_BUSY") as context:
            self.store.begin_admin_action(
                idempotency_key="4e5afe96-6c41-4f4a-b7e3-5cf2a9074012",
                admin_telegram_id=2001,
                action="extend_30_days",
                target_username="user01",
            )

        self.assertEqual(context.exception.code, "REQUEST_BUSY")

    def test_failed_admin_action_is_replayed_without_reexecution(self) -> None:
        record, created = self.store.begin_admin_action(
            idempotency_key="4e5afe96-6c41-4f4a-b7e3-5cf2a9074013",
            admin_telegram_id=2001,
            action="extend_30_days",
            target_username="user01",
        )
        self.assertTrue(created)
        self.store.fail_admin_action(record.id, error_code="XUI_WRITE_FAILED")

        replay, created_again = self.store.begin_admin_action(
            idempotency_key="4e5afe96-6c41-4f4a-b7e3-5cf2a9074013",
            admin_telegram_id=2001,
            action="extend_30_days",
            target_username="user01",
        )

        self.assertFalse(created_again)
        self.assertEqual(replay.id, record.id)
        self.assertEqual(replay.status, "failed")
        self.assertEqual(replay.error_code, "XUI_WRITE_FAILED")


if __name__ == "__main__":
    unittest.main()

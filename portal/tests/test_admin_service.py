from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from app.admin_service import AdminPrincipal, AdminService, AdminServiceError
from app.config import (
    AppConfig, MtproxyConfig, PortalUser, TelegramConfig, TelegramPaymentConfig,
    VisitLogConfig,
)
from app.telegram_store import AdminActionRecord, PaymentRequest
from app.xui_admin import ExtendResult


def make_service() -> tuple[AdminService, Mock, Mock, Mock]:
    user = PortalUser("user01", "hash", "user01@example.test", "User One")
    config = AppConfig("127.0.0.1", 3180, "vpn.test", "secret", Path("x.db"), "family", {user.username: user}, VisitLogConfig(False, Path("access.log"), Path("visits.db"), 30, frozenset()), TelegramConfig(False, "", "", frozenset({100}), Path("bot.db"), TelegramPaymentConfig(400, 30, "")), MtproxyConfig(False, "vpn.test", 8443, ""), ())
    store, xui_ro, xui_admin = Mock(), Mock(), Mock()
    store.begin_admin_action.return_value = (AdminActionRecord(7, "key", 100, "require_payment", "user01", None, "processing", None, None, "", None), True)
    store.get_requires_payment.return_value = True
    return AdminService(config=config, store=store, xui_ro=xui_ro, xui_admin=xui_admin), store, xui_ro, xui_admin


def principal() -> AdminPrincipal:
    return AdminPrincipal(100, "admin", "Admin", 1)


def test_require_payment_writes_xui_before_policy() -> None:
    service, store, _, xui = make_service()
    calls: list[str] = []
    xui.expire_client_now.side_effect = lambda **_: (
        calls.append("xui"), ExtendResult("user01@example.test", 10, "expired")
    )[1]
    store.set_requires_payment.side_effect = lambda *_: calls.append("policy")

    service.require_payment("user01", principal=principal(), idempotency_key="key")

    assert xui.expire_client_now.call_args.kwargs["client_email"] == "user01@example.test"
    assert store.set_requires_payment.call_args.args == ("user01", True)
    assert xui.method_calls[0][0] == "expire_client_now"
    assert calls == ["xui", "policy"]


def test_set_free_clears_expiry_before_policy() -> None:
    service, store, _, xui = make_service()
    store.begin_admin_action.return_value = (AdminActionRecord(7, "key", 100, "set_free", "user01", None, "processing", None, None, "", None), True)
    xui.clear_client_expiry.return_value = ExtendResult("user01@example.test", 0, "без срока")

    result = service.set_free("user01", principal=principal(), idempotency_key="key")

    assert result.requires_payment is False
    assert store.set_requires_payment.call_args.args == ("user01", False)


def test_extend_uses_configured_default_period() -> None:
    service, _, _, xui = make_service()
    service._store.begin_admin_action.return_value = (AdminActionRecord(7, "key", 100, "extend_30_days", "user01", None, "processing", None, None, "", None), True)
    xui.extend_client.return_value = ExtendResult("user01@example.test", 100, "later")

    service.extend_default_period("user01", principal=principal(), idempotency_key="key")

    assert xui.extend_client.call_args.kwargs["days"] == 30


def test_approve_claims_once_and_replay_does_not_extend_again() -> None:
    service, store, _, xui = make_service()
    request = PaymentRequest(11, "user01", "user01@example.test", 500, "pending", "", None, None)
    store.get_payment_request.return_value = request
    store.begin_admin_action.return_value = (AdminActionRecord(7, "key", 100, "approve_payment_request", "user01", 11, "processing", None, None, "", None), True)
    store.claim_payment_request.return_value = request
    store.finalize_payment_request.return_value = True
    xui.extend_client.return_value = ExtendResult("user01@example.test", 100, "later")

    service.approve_payment_request(11, principal=principal(), idempotency_key="key")
    assert xui.extend_client.call_count == 1

    saved = json.loads(store.complete_admin_action.call_args.kwargs["result_json"])
    store.begin_admin_action.return_value = (AdminActionRecord(7, "key", 100, "approve_payment_request", "user01", 11, "succeeded", json.dumps(saved), None, "", ""), False)
    replay = service.approve_payment_request(11, principal=principal(), idempotency_key="key")
    assert replay.replayed is True
    assert xui.extend_client.call_count == 1


def test_xui_failure_releases_claim_and_keeps_request_pending() -> None:
    service, store, _, xui = make_service()
    request = PaymentRequest(11, "user01", "user01@example.test", 500, "pending", "", None, None)
    store.get_payment_request.return_value = request
    store.begin_admin_action.return_value = (AdminActionRecord(7, "key", 100, "approve_payment_request", "user01", 11, "processing", None, None, "", None), True)
    store.claim_payment_request.return_value = request
    xui.extend_client.side_effect = RuntimeError("x-ui down")

    with unittest.TestCase().assertRaisesRegex(AdminServiceError, "XUI_WRITE_FAILED"):
        service.approve_payment_request(11, principal=principal(), idempotency_key="key")

    store.release_payment_request.assert_called_once_with(11, admin_chat_id=100)
    store.fail_admin_action.assert_called_with(7, error_code="XUI_WRITE_FAILED")


def test_finalization_failure_after_xui_is_partial_and_not_retried() -> None:
    service, store, _, xui = make_service()
    request = PaymentRequest(11, "user01", "user01@example.test", 500, "pending", "", None, None)
    store.get_payment_request.return_value = request
    store.begin_admin_action.return_value = (AdminActionRecord(7, "key", 100, "approve_payment_request", "user01", 11, "processing", None, None, "", None), True)
    store.claim_payment_request.return_value = request
    store.finalize_payment_request.return_value = False
    xui.extend_client.return_value = ExtendResult("user01@example.test", 100, "later")

    with unittest.TestCase().assertRaisesRegex(AdminServiceError, "PARTIAL_FAILURE"):
        service.approve_payment_request(11, principal=principal(), idempotency_key="key")

    store.fail_admin_action.assert_called_with(7, error_code="PARTIAL_FAILURE")

    store.begin_admin_action.return_value = (
        AdminActionRecord(
            7, "key", 100, "approve_payment_request", "user01", 11,
            "failed", None, "PARTIAL_FAILURE", "", "",
        ),
        False,
    )
    with unittest.TestCase().assertRaisesRegex(AdminServiceError, "PARTIAL_FAILURE"):
        service.approve_payment_request(11, principal=principal(), idempotency_key="key")
    assert xui.extend_client.call_count == 1


def load_tests(
    loader: unittest.TestLoader,
    tests: unittest.TestSuite,
    pattern: str | None,
) -> unittest.TestSuite:
    test_functions = (
        test_require_payment_writes_xui_before_policy,
        test_set_free_clears_expiry_before_policy,
        test_extend_uses_configured_default_period,
        test_approve_claims_once_and_replay_does_not_extend_again,
        test_xui_failure_releases_claim_and_keeps_request_pending,
        test_finalization_failure_after_xui_is_partial_and_not_retried,
    )
    return unittest.TestSuite(unittest.FunctionTestCase(test) for test in test_functions)

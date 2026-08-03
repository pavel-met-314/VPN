"""Оркестрация административных операций без прямого доступа к SQLite."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Literal, cast

from app.config import AppConfig, PortalUser
from app.telegram_store import (
    AdminActionRecord,
    PaymentRequest,
    TelegramStore,
    TelegramStoreError,
)
from app.xui_admin import ExtendResult, XuiAdmin
from app.xui_db import ClientTraffic, XuiDatabase

logger = logging.getLogger("family-portal.admin-service")

VpnState = Literal["active", "expired", "disabled", "unknown"]
ActionName = Literal[
    "require_payment",
    "set_free",
    "extend_30_days",
    "approve_payment_request",
    "reject_payment_request",
]
ErrorCode = Literal[
    "USER_NOT_FOUND",
    "REQUEST_NOT_FOUND",
    "REQUEST_ALREADY_RESOLVED",
    "REQUEST_BUSY",
    "IDEMPOTENCY_CONFLICT",
    "XUI_READ_FAILED",
    "XUI_WRITE_FAILED",
    "STORE_WRITE_FAILED",
    "PARTIAL_FAILURE",
]


@dataclass(frozen=True)
class AdminPrincipal:
    telegram_user_id: int
    telegram_username: str | None
    display_name: str
    auth_date: int


@dataclass(frozen=True)
class AdminUserView:
    username: str
    display_name: str
    client_email: str
    requires_payment: bool
    telegram_linked: bool
    vpn_state: VpnState
    expiry_ms: int | None
    expiry_display: str | None
    traffic_used_bytes: int | None
    traffic_used_display: str | None
    last_online_ms: int | None
    last_online_display: str | None
    pending_payment_request_id: int | None


@dataclass(frozen=True)
class PaymentRequestView:
    id: int
    username: str
    display_name: str
    client_email: str
    telegram_chat_id: int
    status: Literal["pending", "processing", "approved", "rejected"]
    created_at: str
    resolved_at: str | None
    admin_telegram_id: int | None


@dataclass(frozen=True)
class AdminActionResult:
    action_id: int
    action: ActionName
    target_username: str
    client_email: str
    requires_payment: bool
    vpn_state: VpnState
    expiry_ms: int | None
    expiry_display: str | None
    payment_request_id: int | None
    replayed: bool
    notification_sent: bool | None


@dataclass(frozen=True)
class AdminSummary:
    total: int
    active: int
    expired: int
    disabled: int
    unknown: int
    requires_payment: int
    pending_payment_requests: int


class AdminServiceError(RuntimeError):
    def __init__(self, code: ErrorCode) -> None:
        super().__init__(code)
        self.code = code


class AdminService:
    def __init__(
        self,
        *,
        config: AppConfig,
        store: TelegramStore,
        xui_ro: XuiDatabase,
        xui_admin: XuiAdmin,
    ) -> None:
        self._config = config
        self._store = store
        self._xui_ro = xui_ro
        self._xui_admin = xui_admin

    def get_summary(self) -> AdminSummary:
        users = self.list_users()
        try:
            pending = len(self._store.list_payment_requests(status="pending"))
        except Exception as exc:
            raise self._store_error(exc) from exc
        states = {state: sum(user.vpn_state == state for user in users) for state in (
            "active", "expired", "disabled", "unknown"
        )}
        return AdminSummary(
            total=len(users),
            active=states["active"],
            expired=states["expired"],
            disabled=states["disabled"],
            unknown=states["unknown"],
            requires_payment=sum(user.requires_payment for user in users),
            pending_payment_requests=pending,
        )

    def list_users(self) -> list[AdminUserView]:
        try:
            policies = self._store.list_billing_policies(list(self._config.users))
        except Exception as exc:
            raise self._store_error(exc) from exc
        return [self._user_view(user, policies[user.username]) for user in self._config.users.values()]

    def get_user(self, username: str) -> AdminUserView:
        user = self._user_or_error(username)
        try:
            policy = self._store.get_requires_payment(username)
        except Exception as exc:
            raise self._store_error(exc) from exc
        return self._user_view(user, policy, tolerate_xui_error=False)

    def list_payment_requests(
        self,
        *,
        status: Literal["pending", "approved", "rejected"] = "pending",
    ) -> list[PaymentRequestView]:
        try:
            requests = self._store.list_payment_requests(status=status)
        except Exception as exc:
            raise self._store_error(exc) from exc
        return [self._payment_view(request) for request in requests]

    def require_payment(self, username: str, *, principal: AdminPrincipal, idempotency_key: str) -> AdminActionResult:
        user = self._user_or_error(username)
        record, replay = self._begin_action(
            action="require_payment", user=user, principal=principal, idempotency_key=idempotency_key
        )
        if replay is not None:
            return replay
        try:
            expiry = self._xui_admin.expire_client_now(
                inbound_remark=self._inbound(user), client_email=user.client_email
            )
        except Exception as exc:
            self._fail(record, "XUI_WRITE_FAILED")
            raise AdminServiceError("XUI_WRITE_FAILED") from exc
        return self._finish_policy_action(record, "require_payment", user, expiry, True)

    def set_free(self, username: str, *, principal: AdminPrincipal, idempotency_key: str) -> AdminActionResult:
        user = self._user_or_error(username)
        record, replay = self._begin_action(
            action="set_free", user=user, principal=principal, idempotency_key=idempotency_key
        )
        if replay is not None:
            return replay
        try:
            expiry = self._xui_admin.clear_client_expiry(
                inbound_remark=self._inbound(user), client_email=user.client_email
            )
        except Exception as exc:
            self._fail(record, "XUI_WRITE_FAILED")
            raise AdminServiceError("XUI_WRITE_FAILED") from exc
        return self._finish_policy_action(record, "set_free", user, expiry, False)

    def extend_default_period(self, username: str, *, principal: AdminPrincipal, idempotency_key: str) -> AdminActionResult:
        user = self._user_or_error(username)
        record, replay = self._begin_action(
            action="extend_30_days", user=user, principal=principal, idempotency_key=idempotency_key
        )
        if replay is not None:
            return replay
        try:
            expiry = self._xui_admin.extend_client(
                inbound_remark=self._inbound(user),
                client_email=user.client_email,
                days=self._config.telegram.payment.days,
            )
        except Exception as exc:
            self._fail(record, "XUI_WRITE_FAILED")
            raise AdminServiceError("XUI_WRITE_FAILED") from exc
        return self._finish_policy_action(record, "extend_30_days", user, expiry, True)

    def approve_payment_request(self, request_id: int, *, principal: AdminPrincipal, idempotency_key: str) -> AdminActionResult:
        request = self._request_or_error(request_id)
        user = self._user_or_error(request.username)
        record, replay = self._begin_action(
            action="approve_payment_request", user=user, principal=principal,
            idempotency_key=idempotency_key, payment_request_id=request_id,
        )
        if replay is not None:
            return replay
        try:
            requires_payment = self._policy(user.username)
        except AdminServiceError:
            self._fail(record, "STORE_WRITE_FAILED")
            raise
        try:
            claimed = self._store.claim_payment_request(request_id, admin_chat_id=principal.telegram_user_id)
        except Exception as exc:
            self._fail(record, "STORE_WRITE_FAILED")
            raise self._store_error(exc) from exc
        if claimed is None:
            self._fail(record, self._request_unavailable_code(request_id))
            raise AdminServiceError(self._request_unavailable_code(request_id))
        if claimed.username != user.username or claimed.client_email != user.client_email:
            self._release(claimed, principal.telegram_user_id)
            self._fail(record, "USER_NOT_FOUND")
            raise AdminServiceError("USER_NOT_FOUND")
        try:
            expiry = self._xui_admin.extend_client(
                inbound_remark=self._inbound(user), client_email=user.client_email,
                days=self._config.telegram.payment.days,
            )
        except Exception as exc:
            self._release(claimed, principal.telegram_user_id)
            self._fail(record, "XUI_WRITE_FAILED")
            raise AdminServiceError("XUI_WRITE_FAILED") from exc
        try:
            finalized = self._store.finalize_payment_request(
                request_id, from_status="processing", status="approved",
                admin_chat_id=principal.telegram_user_id,
            )
        except Exception as exc:
            self._fail(record, "PARTIAL_FAILURE")
            raise AdminServiceError("PARTIAL_FAILURE") from exc
        if not finalized:
            self._fail(record, "PARTIAL_FAILURE")
            raise AdminServiceError("PARTIAL_FAILURE")
        result = self._result(record, "approve_payment_request", user, expiry, requires_payment, request_id)
        return self._complete(record, result)

    def reject_payment_request(self, request_id: int, *, principal: AdminPrincipal, idempotency_key: str) -> AdminActionResult:
        request = self._request_or_error(request_id)
        user = self._user_or_error(request.username)
        record, replay = self._begin_action(
            action="reject_payment_request", user=user, principal=principal,
            idempotency_key=idempotency_key, payment_request_id=request_id,
        )
        if replay is not None:
            return replay
        try:
            requires_payment = self._policy(user.username)
        except AdminServiceError:
            self._fail(record, "STORE_WRITE_FAILED")
            raise
        try:
            rejected = self._store.finalize_payment_request(
                request_id, from_status="pending", status="rejected",
                admin_chat_id=principal.telegram_user_id,
            )
        except Exception as exc:
            self._fail(record, "STORE_WRITE_FAILED")
            raise self._store_error(exc) from exc
        if not rejected:
            code = self._request_unavailable_code(request_id)
            self._fail(record, code)
            raise AdminServiceError(code)
        result = self._result(record, "reject_payment_request", user, None, requires_payment, request_id)
        return self._complete(record, result)

    def _user_view(self, user: PortalUser, requires_payment: bool, *, tolerate_xui_error: bool = True) -> AdminUserView:
        try:
            traffic = self._xui_ro.get_client_traffic(user.client_email)
        except Exception as exc:
            if not tolerate_xui_error:
                raise AdminServiceError("XUI_READ_FAILED") from exc
            logger.warning("cannot read x-ui traffic for %s", user.username, exc_info=True)
            traffic = None
        try:
            linked = self._store.get_link_by_username(user.username) is not None
            pending = self._store.get_open_payment_request_for_user(user.username)
        except Exception as exc:
            raise self._store_error(exc) from exc
        return self._view_from_traffic(user, requires_payment, linked, pending, traffic)

    def _view_from_traffic(self, user: PortalUser, requires_payment: bool, linked: bool, pending: PaymentRequest | None, traffic: ClientTraffic | None) -> AdminUserView:
        if traffic is None:
            state: VpnState = "unknown"
            expiry_ms = expiry_display = used_bytes = used_display = last_online_ms = last_online_display = None
        else:
            state = "disabled" if not traffic.enable else "expired" if traffic.is_expired else "active"
            expiry_ms, expiry_display = traffic.expiry_time, traffic.expiry_human
            used_bytes, used_display = traffic.used, traffic.used_human
            last_online_ms, last_online_display = traffic.last_online, traffic.last_online_human
        return AdminUserView(user.username, user.display_name, user.client_email, requires_payment, linked, state, expiry_ms, expiry_display, used_bytes, used_display, last_online_ms, last_online_display, pending.id if pending else None)

    def _payment_view(self, request: PaymentRequest) -> PaymentRequestView:
        user = self._config.users.get(request.username)
        return PaymentRequestView(request.id, request.username, user.display_name if user else request.username, request.client_email, request.chat_id, cast(Literal["pending", "processing", "approved", "rejected"], request.status), request.created_at, request.resolved_at, request.admin_chat_id)

    def _begin_action(self, *, action: ActionName, user: PortalUser, principal: AdminPrincipal, idempotency_key: str, payment_request_id: int | None = None) -> tuple[AdminActionRecord, AdminActionResult | None]:
        try:
            record, created = self._store.begin_admin_action(idempotency_key=idempotency_key, admin_telegram_id=principal.telegram_user_id, action=action, target_username=user.username, payment_request_id=payment_request_id)
        except TelegramStoreError as exc:
            raise AdminServiceError(cast(ErrorCode, exc.code)) from exc
        except Exception as exc:
            raise self._store_error(exc) from exc
        if created:
            return record, None
        if record.status == "failed":
            raise AdminServiceError(cast(ErrorCode, record.error_code or "STORE_WRITE_FAILED"))
        try:
            payload = json.loads(record.result_json or "{}")
            payload["replayed"] = True
            return record, AdminActionResult(**payload)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AdminServiceError("STORE_WRITE_FAILED") from exc

    def _finish_policy_action(self, record: AdminActionRecord, action: ActionName, user: PortalUser, expiry: ExtendResult, requires_payment: bool) -> AdminActionResult:
        try:
            self._store.set_requires_payment(user.username, requires_payment)
        except Exception as exc:
            self._fail(record, "PARTIAL_FAILURE")
            raise AdminServiceError("PARTIAL_FAILURE") from exc
        return self._complete(record, self._result(record, action, user, expiry, requires_payment, None))

    def _result(self, record: AdminActionRecord, action: ActionName, user: PortalUser, expiry: ExtendResult | None, requires_payment: bool, request_id: int | None) -> AdminActionResult:
        expiry_ms = expiry.expiry_ms if expiry else None
        return AdminActionResult(record.id, action, user.username, user.client_email, requires_payment, self._state_for_expiry(expiry_ms), expiry_ms, expiry.expiry_display if expiry else None, request_id, False, None)

    def _complete(self, record: AdminActionRecord, result: AdminActionResult) -> AdminActionResult:
        try:
            self._store.complete_admin_action(record.id, result_json=json.dumps(asdict(result), separators=(",", ":")))
        except Exception as exc:
            self._fail(record, "PARTIAL_FAILURE")
            raise AdminServiceError("PARTIAL_FAILURE") from exc
        return result

    def _request_or_error(self, request_id: int) -> PaymentRequest:
        try:
            request = self._store.get_payment_request(request_id)
        except Exception as exc:
            raise self._store_error(exc) from exc
        if request is None:
            raise AdminServiceError("REQUEST_NOT_FOUND")
        return request

    def _request_unavailable_code(self, request_id: int) -> ErrorCode:
        try:
            return "REQUEST_NOT_FOUND" if self._store.get_payment_request(request_id) is None else "REQUEST_ALREADY_RESOLVED"
        except Exception:
            return "STORE_WRITE_FAILED"

    def _release(self, request: PaymentRequest, admin_id: int) -> None:
        try:
            self._store.release_payment_request(request.id, admin_chat_id=admin_id)
        except Exception:
            logger.exception("cannot release payment request %s", request.id)

    def _fail(self, record: AdminActionRecord, code: ErrorCode) -> None:
        try:
            self._store.fail_admin_action(record.id, error_code=code)
        except Exception:
            logger.exception("cannot save failed admin action %s", record.id)

    def _policy(self, username: str) -> bool:
        try:
            return self._store.get_requires_payment(username)
        except Exception as exc:
            raise self._store_error(exc) from exc

    def _user_or_error(self, username: str) -> PortalUser:
        user = self._config.users.get(username)
        if user is None:
            raise AdminServiceError("USER_NOT_FOUND")
        return user

    def _inbound(self, user: PortalUser) -> str:
        return user.inbound_remark or self._config.inbound_remark

    @staticmethod
    def _state_for_expiry(expiry_ms: int | None) -> VpnState:
        if expiry_ms is None:
            return "unknown"
        if expiry_ms == 0:
            return "active"
        from datetime import datetime, timezone

        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        return "expired" if expiry_ms <= now_ms else "active"

    @staticmethod
    def _store_error(exc: Exception) -> AdminServiceError:
        logger.warning("telegram store operation failed", exc_info=exc)
        return AdminServiceError("STORE_WRITE_FAILED")

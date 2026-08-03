"""HTTP API Telegram Mini App для административных операций."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict, is_dataclass, replace
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.admin_service import AdminPrincipal, AdminService, AdminServiceError
from app.config import AppConfig
from app.telegram_store import TelegramStore
from app.telegram_webapp_auth import TelegramInitDataError, validate_admin_init_data
from app.xui_admin import XuiAdmin
from app.xui_db import XuiDatabase

logger = logging.getLogger("family-portal.tg-admin")

AdminUserNotifier = Callable[[str, str], Awaitable[bool | None]]


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, retryable: bool = False) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable


class AdminApiRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        handler = super().get_route_handler()

        async def wrapped(request: Request):
            try:
                return await handler(request)
            except ApiError as exc:
                return error_response(exc)

        return wrapped


def error_response(error: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={"error": {"code": error.code, "message": error.message, "retryable": error.retryable}},
    )


def _auth_error(exc: TelegramInitDataError) -> ApiError:
    messages = {
        "MISSING_INIT_DATA": "Не переданы данные Telegram",
        "INVALID_SIGNATURE": "Некорректная подпись Telegram",
        "INVALID_USER": "Некорректные данные пользователя Telegram",
        "AUTH_EXPIRED": "Сессия Telegram истекла",
        "NOT_ADMIN": "Недостаточно прав",
    }
    return ApiError(403 if exc.code == "NOT_ADMIN" else 401, exc.code, messages[exc.code])


def _service_error(exc: AdminServiceError) -> ApiError:
    mapping = {
        "USER_NOT_FOUND": (404, "Пользователь не найден", False),
        "REQUEST_NOT_FOUND": (404, "Заявка не найдена", False),
        "REQUEST_ALREADY_RESOLVED": (409, "Заявка уже обработана", False),
        "REQUEST_BUSY": (409, "Операция уже выполняется", True),
        "IDEMPOTENCY_CONFLICT": (409, "Ключ идемпотентности использован для другого действия", False),
        "XUI_READ_FAILED": (503, "Данные VPN временно недоступны", True),
        "XUI_WRITE_FAILED": (500, "Не удалось изменить доступ VPN", False),
        "STORE_WRITE_FAILED": (503, "Сервис биллинга временно недоступен", True),
        "PARTIAL_FAILURE": (500, "Операция выполнена не полностью", False),
    }
    status, message, retryable = mapping.get(exc.code, (500, "Внутренняя ошибка", False))
    logger.warning("tg admin service error: %s", exc.code, exc_info=True)
    return ApiError(status, exc.code, message, retryable)


def _idempotency_key(value: str | None) -> str:
    if value is None or not 16 <= len(value) <= 128 or any(not 0x21 <= ord(char) <= 0x7E for char in value):
        raise ApiError(400, "INVALID_IDEMPOTENCY_KEY", "Некорректный Idempotency-Key")
    return value


def _request_id(value: str) -> int:
    try:
        request_id = int(value)
    except ValueError:
        raise ApiError(400, "INVALID_REQUEST_ID", "Некорректный идентификатор заявки") from None
    if request_id <= 0:
        raise ApiError(400, "INVALID_REQUEST_ID", "Некорректный идентификатор заявки")
    return request_id


def notification_text(action: str, expiry_display: str | None) -> str:
    messages = {
        "require_payment": "Требуется оплата, доступ VPN приостановлен.",
        "set_free": "Включён бесплатный бессрочный доступ VPN.",
        "approve_payment_request": "Оплата подтверждена, срок доступа VPN продлён.",
        "reject_payment_request": "Заявка на оплату отклонена.",
    }
    if action == "extend_30_days":
        suffix = f" до {expiry_display}" if expiry_display else ""
        return f"Срок доступа VPN продлён{suffix}."
    return messages[action]


def create_tg_admin_router(
    *,
    get_config: Callable[[], AppConfig],
    get_store: Callable[[], TelegramStore | None],
    notify_user: AdminUserNotifier,
) -> APIRouter:
    router = APIRouter(prefix="/portal/api/tg-admin", route_class=AdminApiRoute)

    def get_principal(
        init_data: Annotated[str | None, Header(alias="X-Telegram-Init-Data")] = None,
        config: AppConfig = Depends(get_config),
    ) -> AdminPrincipal:
        try:
            return validate_admin_init_data(
                init_data or "",
                bot_token=config.telegram.bot_token,
                admin_chat_ids=config.telegram.admin_chat_ids,
            )
        except TelegramInitDataError as exc:
            raise _auth_error(exc) from exc

    def get_service(
        _: AdminPrincipal = Depends(get_principal),
        config: AppConfig = Depends(get_config),
        store: TelegramStore | None = Depends(get_store),
    ) -> AdminService:
        if store is None:
            raise ApiError(503, "STORE_WRITE_FAILED", "Сервис биллинга временно недоступен", True)
        return AdminService(
            config=config,
            store=store,
            xui_ro=XuiDatabase(config.xui_db_path),
            xui_admin=XuiAdmin(config.xui_db_path),
        )

    async def action_result(call: Callable[[], object]) -> object:
        try:
            return await asyncio.to_thread(call)
        except AdminServiceError as exc:
            raise _service_error(exc) from exc

    def serialize(result: object) -> object:
        if is_dataclass(result):
            return asdict(result)
        if isinstance(result, list):
            return [asdict(item) if is_dataclass(item) else item for item in result]
        return result

    async def action_response(call: Callable[[], object]) -> dict:
        result = await action_result(call)
        if result.replayed:
            return asdict(replace(result, notification_sent=None))
        try:
            notification_sent = await notify_user(
                result.target_username,
                notification_text(result.action, result.expiry_display),
            )
        except Exception:
            logger.exception("cannot notify Telegram user %s", result.target_username)
            notification_sent = False
        return asdict(replace(result, notification_sent=notification_sent))

    @router.get("/me")
    def me(principal: AdminPrincipal = Depends(get_principal)) -> dict[str, object]:
        return {
            "telegram_user_id": principal.telegram_user_id,
            "telegram_username": principal.telegram_username,
            "display_name": principal.display_name,
        }

    @router.get("/summary")
    async def summary(_: AdminPrincipal = Depends(get_principal), service: AdminService = Depends(get_service)) -> object:
        return serialize(await action_result(service.get_summary))

    @router.get("/users")
    async def users(_: AdminPrincipal = Depends(get_principal), service: AdminService = Depends(get_service)) -> dict:
        return {"items": serialize(await action_result(service.list_users))}

    @router.get("/users/{username}")
    async def user(username: str, _: AdminPrincipal = Depends(get_principal), service: AdminService = Depends(get_service)) -> object:
        return serialize(await action_result(lambda: service.get_user(username)))

    @router.get("/payment-requests")
    async def payment_requests(
        status: str = "pending",
        _: AdminPrincipal = Depends(get_principal),
        service: AdminService = Depends(get_service),
    ) -> dict:
        if status not in ("pending", "approved", "rejected"):
            raise ApiError(400, "INVALID_STATUS", "Некорректный статус заявки")
        items = serialize(await action_result(lambda: service.list_payment_requests(status=status)))
        return {"items": [{key: value for key, value in item.items() if key != "telegram_chat_id"} for item in items]}

    @router.post("/users/{username}/require-payment")
    async def require_payment(
        username: str,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        principal: AdminPrincipal = Depends(get_principal),
        service: AdminService = Depends(get_service),
    ) -> dict:
        key = _idempotency_key(idempotency_key)
        return await action_response(lambda: service.require_payment(username, principal=principal, idempotency_key=key))

    @router.post("/users/{username}/set-free")
    async def set_free(username: str, idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None, principal: AdminPrincipal = Depends(get_principal), service: AdminService = Depends(get_service)) -> dict:
        key = _idempotency_key(idempotency_key)
        return await action_response(lambda: service.set_free(username, principal=principal, idempotency_key=key))

    @router.post("/users/{username}/extend")
    async def extend(username: str, idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None, principal: AdminPrincipal = Depends(get_principal), service: AdminService = Depends(get_service)) -> dict:
        key = _idempotency_key(idempotency_key)
        return await action_response(lambda: service.extend_default_period(username, principal=principal, idempotency_key=key))

    @router.post("/payment-requests/{request_id}/approve")
    async def approve(request_id: str, idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None, principal: AdminPrincipal = Depends(get_principal), service: AdminService = Depends(get_service)) -> dict:
        key = _idempotency_key(idempotency_key)
        parsed_request_id = _request_id(request_id)
        return await action_response(lambda: service.approve_payment_request(parsed_request_id, principal=principal, idempotency_key=key))

    @router.post("/payment-requests/{request_id}/reject")
    async def reject(request_id: str, idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None, principal: AdminPrincipal = Depends(get_principal), service: AdminService = Depends(get_service)) -> dict:
        key = _idempotency_key(idempotency_key)
        parsed_request_id = _request_id(request_id)
        return await action_response(lambda: service.reject_payment_request(parsed_request_id, principal=principal, idempotency_key=key))

    return router

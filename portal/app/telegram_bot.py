from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.config import AppConfig, PortalUser
from app.telegram_store import TelegramStore
from app.xui_admin import XuiAdmin
from app.xui_db import XuiDatabase

if TYPE_CHECKING:
    pass

logger = logging.getLogger("family-portal.telegram")

CALLBACK_APPROVE_PREFIX = "pay_ok:"
CALLBACK_REJECT_PREFIX = "pay_no:"
BTN_PAID = "Я оплатил"
BTN_STATUS = "Статус"


class TelegramBotContext:
    def __init__(self, config: AppConfig, store: TelegramStore) -> None:
        self.config = config
        self.store = store
        self.xui_ro = XuiDatabase(config.xui_db_path)
        self.xui_admin = XuiAdmin(config.xui_db_path)

    def portal_user(self, username: str) -> PortalUser | None:
        return self.config.users.get(username)

    def resolve_inbound_remark(self, user: PortalUser) -> str:
        return user.inbound_remark or self.config.inbound_remark

    def is_admin(self, chat_id: int) -> bool:
        return chat_id in self.config.telegram.admin_chat_ids

    def resolve_user_arg(self, raw: str) -> PortalUser | None:
        """Логин портала или client_email (user05)."""
        key = raw.strip()
        if not key:
            return None
        user = self.config.users.get(key)
        if user is not None:
            return user
        key_lower = key.lower()
        for portal_user in self.config.users.values():
            if portal_user.username.lower() == key_lower:
                return portal_user
            if portal_user.client_email.lower() == key_lower:
                return portal_user
        return None


def _user_keyboard(bot_ctx: TelegramBotContext, username: str) -> ReplyKeyboardMarkup:
    buttons = [BTN_STATUS]
    if bot_ctx.store.get_requires_payment(username):
        buttons.append(BTN_PAID)
    return ReplyKeyboardMarkup([buttons], resize_keyboard=True)


def _payment_instructions(config: AppConfig, user: PortalUser) -> str:
    payment = config.telegram.payment
    instructions = payment.instructions.replace("userXX", user.client_email)
    return (
        f"Тариф: {payment.amount_rub} ₽ / {payment.days} дн.\n"
        f"Твой код в комментарии: {user.client_email}\n\n"
        f"{instructions}"
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot_ctx: TelegramBotContext = context.application.bot_data["bot_ctx"]
    if update.effective_chat is None or update.message is None:
        return

    chat_id = update.effective_chat.id
    args = context.args or []

    if args and args[0].startswith("link_"):
        token = args[0][5:]
        username = bot_ctx.store.consume_link_token(token)
        if username is None:
            await update.message.reply_text("Ссылка недействительна или истекла. Получи новую на портале.")
            return
        portal_user = bot_ctx.portal_user(username)
        if portal_user is None:
            await update.message.reply_text("Пользователь не найден. Обратись к админу.")
            return
        bot_ctx.store.link_telegram(username, chat_id)
        await update.message.reply_text(
            f"Telegram привязан к аккаунту {portal_user.display_name}.\n"
            f"Профиль: {portal_user.client_email}",
            reply_markup=_user_keyboard(bot_ctx, username),
        )
        return

    link = bot_ctx.store.get_link_by_chat_id(chat_id)
    if link is None:
        await update.message.reply_text(
            "Сначала привяжи Telegram на портале VPN:\n"
            "Войди → кнопка «Привязать Telegram»."
        )
        return

    portal_user = bot_ctx.portal_user(link.username)
    if portal_user is None:
        await update.message.reply_text("Аккаунт не найден. Обратись к админу.")
        return

    requires_payment = bot_ctx.store.get_requires_payment(link.username)
    hint = "Кнопки ниже: статус"
    if requires_payment:
        hint += " и «Я оплатил»."
    else:
        hint += ". Бесплатный доступ."
    await update.message.reply_text(
        f"Привет, {portal_user.display_name}!\n{hint}",
        reply_markup=_user_keyboard(bot_ctx, link.username),
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot_ctx: TelegramBotContext = context.application.bot_data["bot_ctx"]
    if update.effective_chat is None or update.message is None:
        return

    text = _build_status_text(bot_ctx, update.effective_chat.id)
    if text is None:
        await update.message.reply_text("Telegram не привязан. Сделай это на портале VPN.")
        return
    link = bot_ctx.store.get_link_by_chat_id(update.effective_chat.id)
    username = link.username if link else ""
    await update.message.reply_text(text, reply_markup=_user_keyboard(bot_ctx, username))


def _build_status_text(bot_ctx: TelegramBotContext, chat_id: int) -> str | None:
    link = bot_ctx.store.get_link_by_chat_id(chat_id)
    if link is None:
        return None
    portal_user = bot_ctx.portal_user(link.username)
    if portal_user is None:
        return None

    requires_payment = bot_ctx.store.get_requires_payment(link.username)
    if not requires_payment:
        return (
            f"Аккаунт: {portal_user.display_name} ({portal_user.client_email})\n"
            "Тариф: бесплатный доступ"
        )

    traffic = bot_ctx.xui_ro.get_client_traffic(portal_user.client_email)
    expiry = traffic.expiry_human if traffic else "неизвестно"
    expired_note = ""
    if traffic and traffic.is_expired:
        expired_note = "\n⚠️ Срок истёк — оплати и нажми «Я оплатил»."

    payment = bot_ctx.config.telegram.payment
    return (
        f"Аккаунт: {portal_user.display_name} ({portal_user.client_email})\n"
        f"Оплачено до: {expiry}{expired_note}\n\n"
        f"Тариф: {payment.amount_rub} ₽ / {payment.days} дн.\n\n"
        f"{_payment_instructions(bot_ctx.config, portal_user)}"
    )


async def handle_paid_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot_ctx: TelegramBotContext = context.application.bot_data["bot_ctx"]
    if update.effective_chat is None or update.message is None:
        return

    chat_id = update.effective_chat.id
    link = bot_ctx.store.get_link_by_chat_id(chat_id)
    if link is None:
        await update.message.reply_text("Сначала привяжи Telegram на портале.")
        return

    portal_user = bot_ctx.portal_user(link.username)
    if portal_user is None:
        await update.message.reply_text("Аккаунт не найден.")
        return

    if not bot_ctx.store.get_requires_payment(link.username):
        await update.message.reply_text(
            "Для твоего аккаунта оплата не требуется — бесплатный доступ.",
            reply_markup=_user_keyboard(bot_ctx, link.username),
        )
        return

    request_id = bot_ctx.store.create_payment_request(
        username=link.username,
        client_email=portal_user.client_email,
        chat_id=chat_id,
    )
    if request_id is None:
        await update.message.reply_text(
            "Заявка уже отправлена — жди подтверждения админа.",
            reply_markup=_user_keyboard(bot_ctx, link.username),
        )
        return

    payment = bot_ctx.config.telegram.payment
    admin_text = (
        f"Заявка на оплату #{request_id}\n"
        f"Пользователь: {portal_user.display_name} ({portal_user.client_email})\n"
        f"Логин портала: {link.username}\n"
        f"Сумма: {payment.amount_rub} ₽ / +{payment.days} дн."
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"+{payment.days} дней",
                    callback_data=f"{CALLBACK_APPROVE_PREFIX}{request_id}",
                ),
                InlineKeyboardButton(
                    "Отклонить",
                    callback_data=f"{CALLBACK_REJECT_PREFIX}{request_id}",
                ),
            ]
        ]
    )

    for admin_id in bot_ctx.config.telegram.admin_chat_ids:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=admin_text,
                reply_markup=keyboard,
            )
        except Exception:
            logger.exception("failed to notify admin %s", admin_id)

    await update.message.reply_text(
        "Заявка отправлена админу. После проверки оплаты доступ продлят.",
        reply_markup=_user_keyboard(bot_ctx, link.username),
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None:
        return
    text = update.message.text.strip()
    if text == BTN_PAID:
        await handle_paid_request(update, context)
    elif text == BTN_STATUS:
        await cmd_status(update, context)


async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot_ctx: TelegramBotContext = context.application.bot_data["bot_ctx"]
    query = update.callback_query
    if query is None or query.data is None or query.from_user is None:
        return

    admin_chat_id = query.from_user.id
    if not bot_ctx.is_admin(admin_chat_id):
        await query.answer("Нет прав", show_alert=True)
        return

    data = query.data
    if data.startswith(CALLBACK_APPROVE_PREFIX):
        request_id = int(data[len(CALLBACK_APPROVE_PREFIX) :])
        await _approve_payment(bot_ctx, query, request_id, admin_chat_id)
    elif data.startswith(CALLBACK_REJECT_PREFIX):
        request_id = int(data[len(CALLBACK_REJECT_PREFIX) :])
        await _reject_payment(bot_ctx, query, request_id, admin_chat_id)


async def _approve_payment(
    bot_ctx: TelegramBotContext,
    query,
    request_id: int,
    admin_chat_id: int,
) -> None:
    req = bot_ctx.store.get_payment_request(request_id)
    if req is None or req.status != "pending":
        await query.answer("Заявка уже обработана", show_alert=True)
        return

    portal_user = bot_ctx.portal_user(req.username)
    if portal_user is None:
        await query.answer("Пользователь не найден", show_alert=True)
        return

    try:
        result = bot_ctx.xui_admin.extend_client(
            inbound_remark=bot_ctx.resolve_inbound_remark(portal_user),
            client_email=req.client_email,
            days=bot_ctx.config.telegram.payment.days,
        )
    except Exception as exc:
        logger.exception("extend_client failed")
        await query.answer(f"Ошибка: {exc}", show_alert=True)
        return

    if not bot_ctx.store.resolve_payment_request(
        request_id,
        status="approved",
        admin_chat_id=admin_chat_id,
    ):
        await query.answer("Заявка уже обработана", show_alert=True)
        return

    await query.answer("Продлено")
    if query.message:
        await query.message.edit_text(
            f"{query.message.text}\n\n✅ Продлено до {result.expiry_display}"
        )

    try:
        await query.get_bot().send_message(
            chat_id=req.chat_id,
            text=(
                f"Оплата подтверждена.\n"
                f"Доступ продлён до {result.expiry_display}."
            ),
            reply_markup=_user_keyboard(bot_ctx, req.username),
        )
    except Exception:
        logger.exception("failed to notify user %s", req.chat_id)


async def _reject_payment(
    bot_ctx: TelegramBotContext,
    query,
    request_id: int,
    admin_chat_id: int,
) -> None:
    req = bot_ctx.store.get_payment_request(request_id)
    if req is None or req.status != "pending":
        await query.answer("Заявка уже обработана", show_alert=True)
        return

    if not bot_ctx.store.resolve_payment_request(
        request_id,
        status="rejected",
        admin_chat_id=admin_chat_id,
    ):
        await query.answer("Заявка уже обработана", show_alert=True)
        return

    await query.answer("Отклонено")
    if query.message:
        await query.message.edit_text(f"{query.message.text}\n\n❌ Отклонено")

    try:
        await query.get_bot().send_message(
            chat_id=req.chat_id,
            text="Заявка отклонена. Если оплата прошла — напиши админу.",
            reply_markup=_user_keyboard(bot_ctx, req.username),
        )
    except Exception:
        logger.exception("failed to notify user %s", req.chat_id)


async def _deny_non_admin(update: Update, bot_ctx: TelegramBotContext) -> bool:
    """True = отказ (не админ или нет message)."""
    if update.effective_chat is None or update.message is None:
        return True
    if not bot_ctx.is_admin(update.effective_chat.id):
        await update.message.reply_text("Команда только для админа.")
        return True
    return False


async def _notify_linked_user(bot_ctx: TelegramBotContext, bot, username: str, text: str) -> None:
    link = bot_ctx.store.get_link_by_username(username)
    if link is None:
        return
    try:
        await bot.send_message(
            chat_id=link.chat_id,
            text=text,
            reply_markup=_user_keyboard(bot_ctx, username),
        )
    except Exception:
        logger.exception("failed to notify linked user %s", username)


async def cmd_admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot_ctx: TelegramBotContext = context.application.bot_data["bot_ctx"]
    if await _deny_non_admin(update, bot_ctx):
        return
    assert update.message is not None
    days = bot_ctx.config.telegram.payment.days
    await update.message.reply_text(
        "Админ-команды (логин портала или email клиента):\n"
        "/who — список: тариф, срок, Telegram\n"
        "/pay <user> — требовать оплату (сразу режет доступ)\n"
        "/free <user> — бесплатно без срока\n"
        f"/extend <user> [дни] — продлить (по умолчанию {days})\n"
        "/admin — эта справка"
    )


async def cmd_who(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot_ctx: TelegramBotContext = context.application.bot_data["bot_ctx"]
    if await _deny_non_admin(update, bot_ctx):
        return
    assert update.message is not None

    usernames = sorted(bot_ctx.config.users.keys())
    policies = bot_ctx.store.list_billing_policies(usernames)
    lines: list[str] = ["Пользователи:"]
    for portal_user in sorted(bot_ctx.config.users.values(), key=lambda u: u.client_email):
        requires = policies.get(portal_user.username, False)
        link = bot_ctx.store.get_link_by_username(portal_user.username)
        tg = "TG✓" if link else "TG—"
        if requires:
            traffic = bot_ctx.xui_ro.get_client_traffic(portal_user.client_email)
            expiry = traffic.expiry_human if traffic else "?"
            flag = "💸"
            if traffic and traffic.is_expired:
                flag = "⛔"
            lines.append(
                f"{flag} {portal_user.client_email} ({portal_user.username}) "
                f"до {expiry} {tg}"
            )
        else:
            lines.append(
                f"🆓 {portal_user.client_email} ({portal_user.username}) free {tg}"
            )

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n…"
    await update.message.reply_text(text)


async def cmd_pay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot_ctx: TelegramBotContext = context.application.bot_data["bot_ctx"]
    if await _deny_non_admin(update, bot_ctx):
        return
    assert update.message is not None

    args = context.args or []
    if len(args) != 1:
        await update.message.reply_text("Использование: /pay <user>")
        return

    portal_user = bot_ctx.resolve_user_arg(args[0])
    if portal_user is None:
        await update.message.reply_text("Пользователь не найден.")
        return

    try:
        bot_ctx.xui_admin.expire_client_now(
            inbound_remark=bot_ctx.resolve_inbound_remark(portal_user),
            client_email=portal_user.client_email,
        )
    except Exception as exc:
        logger.exception("admin /pay failed")
        await update.message.reply_text(f"Ошибка x-ui: {exc}")
        return

    bot_ctx.store.set_requires_payment(portal_user.username, True)
    await update.message.reply_text(
        f"💸 {portal_user.display_name} ({portal_user.client_email}): "
        "требуется оплата, доступ отключён до продления."
    )
    await _notify_linked_user(
        bot_ctx,
        context.bot,
        portal_user.username,
        "Админ включил оплату для твоего аккаунта. "
        "Доступ приостановлен — оплати и нажми «Я оплатил».",
    )


async def cmd_free(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot_ctx: TelegramBotContext = context.application.bot_data["bot_ctx"]
    if await _deny_non_admin(update, bot_ctx):
        return
    assert update.message is not None

    args = context.args or []
    if len(args) != 1:
        await update.message.reply_text("Использование: /free <user>")
        return

    portal_user = bot_ctx.resolve_user_arg(args[0])
    if portal_user is None:
        await update.message.reply_text("Пользователь не найден.")
        return

    try:
        bot_ctx.xui_admin.clear_client_expiry(
            inbound_remark=bot_ctx.resolve_inbound_remark(portal_user),
            client_email=portal_user.client_email,
        )
    except Exception as exc:
        logger.exception("admin /free failed")
        await update.message.reply_text(f"Ошибка x-ui: {exc}")
        return

    bot_ctx.store.set_requires_payment(portal_user.username, False)
    await update.message.reply_text(
        f"🆓 {portal_user.display_name} ({portal_user.client_email}): "
        "бесплатный доступ без срока."
    )
    await _notify_linked_user(
        bot_ctx,
        context.bot,
        portal_user.username,
        "Админ включил бесплатный доступ для твоего аккаунта. VPN снова без срока оплаты.",
    )


async def cmd_extend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot_ctx: TelegramBotContext = context.application.bot_data["bot_ctx"]
    if await _deny_non_admin(update, bot_ctx):
        return
    assert update.message is not None

    args = context.args or []
    if len(args) < 1 or len(args) > 2:
        await update.message.reply_text("Использование: /extend <user> [дни]")
        return

    portal_user = bot_ctx.resolve_user_arg(args[0])
    if portal_user is None:
        await update.message.reply_text("Пользователь не найден.")
        return

    days = bot_ctx.config.telegram.payment.days
    if len(args) == 2:
        try:
            days = int(args[1])
        except ValueError:
            await update.message.reply_text("Дни должны быть числом.")
            return
        if days <= 0 or days > 3660:
            await update.message.reply_text("Дни: от 1 до 3660.")
            return

    try:
        result = bot_ctx.xui_admin.extend_client(
            inbound_remark=bot_ctx.resolve_inbound_remark(portal_user),
            client_email=portal_user.client_email,
            days=days,
        )
    except Exception as exc:
        logger.exception("admin /extend failed")
        await update.message.reply_text(f"Ошибка x-ui: {exc}")
        return

    # Продление вручную обычно значит, что человек на платном тарифе.
    bot_ctx.store.set_requires_payment(portal_user.username, True)
    await update.message.reply_text(
        f"✅ {portal_user.display_name} ({portal_user.client_email}): "
        f"+{days} дн. → до {result.expiry_display}"
    )
    await _notify_linked_user(
        bot_ctx,
        context.bot,
        portal_user.username,
        f"Админ продлил доступ на {days} дн.\nОплачено до: {result.expiry_display}.",
    )


def build_bot_application(config: AppConfig, store: TelegramStore) -> Application:
    bot_ctx = TelegramBotContext(config, store)
    application = (
        Application.builder()
        .token(config.telegram.bot_token)
        .build()
    )
    application.bot_data["bot_ctx"] = bot_ctx

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("admin", cmd_admin_help))
    application.add_handler(CommandHandler("who", cmd_who))
    application.add_handler(CommandHandler("pay", cmd_pay))
    application.add_handler(CommandHandler("free", cmd_free))
    application.add_handler(CommandHandler("extend", cmd_extend))
    application.add_handler(CallbackQueryHandler(handle_admin_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    return application

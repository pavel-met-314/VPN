# CONTRACTS.md — Telegram Mini App для администрирования Family VPN

> Версия: 0.5 (MVP)
> Дата: 2026-08-04
> Статус: утверждён тимлидом для декомпозиции
> Владелец контрактов: архитектор

## 1. Цель и границы MVP

Telegram Mini App предоставляет администраторам мобильный веб-интерфейс внутри Telegram для управления существующими пользователями Family VPN.

В MVP входят:

1. Сводка и список пользователей.
2. Карточка пользователя со статусом VPN, сроком доступа, трафиком и Telegram-привязкой.
3. Продление доступа строго на `telegram.payment.days` (сейчас 30 дней).
4. Перевод пользователя в режим «требуется оплата» с немедленным истечением доступа.
5. Перевод пользователя в режим «бесплатный» без срока действия.
6. Просмотр ожидающих заявок «Я оплатил», их подтверждение и отклонение.
7. Сохранение существующих команд `/who`, `/pay`, `/free`, `/extend`, `/admin` и ручного сценария оплаты.

Не входят в MVP:

- приём платежей или webhook платёжного провайдера;
- создание, удаление или переименование пользователей;
- изменение `limitIp`, UUID, Reality или inbound-конфигурации;
- произвольный срок продления из Mini App;
- управление системными сервисами, firewall или 3X-UI;
- замена существующего веб-портала пользователя;
- деплой на VPS.

## 2. Обязательные инварианты

1. Панель 3X-UI остаётся доступна только на `127.0.0.1`.
2. Mini App обращается только к FastAPI; прямого доступа браузера к `x-ui.db` нет.
3. `xui_db.py` остаётся read-only.
4. Все записи в `x-ui.db` выполняются только через публичные методы `XuiAdmin`.
5. Для 3X-UI 3.3.1+ `XuiAdmin` синхронизирует каноническую запись `clients`
   с совместимыми `inbounds.settings` и `client_traffics`; успешная операция
   не должна оставлять эти представления состояния в противоречии.
6. `limitIp` не читается и не изменяется новым функционалом.
7. Администратор определяется по Telegram `user.id`, который должен входить в `config.telegram.admin_chat_ids`.
8. Нельзя доверять `Telegram.WebApp.initDataUnsafe`. Сервер принимает и проверяет только исходную строку `Telegram.WebApp.initData`.
9. Любая изменяющая операция требует уникальный `Idempotency-Key` и не должна применяться дважды.
10. Подтверждение одной заявки «Я оплатил» может продлить доступ только один раз, даже при конкурентных запросах.
11. Ошибка чтения одного клиента не должна скрывать остальных клиентов из списка.
12. Секреты, VLESS-ссылки, UUID и subscription-токены не возвращаются Admin API.
13. Существующие команды бота сохраняют текущее поведение и используют тот же сервис административных операций, что и Mini App.

## 3. Владение модулями

| Область | Разрешённые файлы | Ответственность |
|---|---|---|
| Хранилище | `portal/app/telegram_store.py`, тесты хранилища | заявки, политики оплаты, идемпотентность и журнал действий |
| Сервис операций | новый `portal/app/admin_service.py`, его тесты | чтение агрегированного состояния и оркестрация изменений |
| Авторизация и HTTP API | новые `portal/app/telegram_webapp_auth.py`, `portal/app/tg_admin.py`, минимальное подключение router в `main.py`, тесты API | проверка `initData`, Admin API, HTTP-ошибки |
| Mini App и запуск из бота | новый шаблон и статические файлы Mini App, `telegram_bot.py`, `config.py`, `config.example.yaml`, одна локальная страница `GET /portal/tg-admin/` в `main.py`, UI-тесты | интерфейс, кнопка запуска, конфигурация URL и HTML-оболочка Mini App |

Разработчик не меняет файлы другой области. Если для интеграции требуется соседний файл, он возвращает отдельный минимальный diff и просит тимлида назначить владельца изменения.

## 4. Общие типы данных

Ниже приведены контрактные структуры. Конкретная реализация может использовать `dataclass`, `TypedDict` или Pydantic, но имена полей и семантика должны сохраняться.

### 4.1. AdminPrincipal

```python
@dataclass(frozen=True)
class AdminPrincipal:
    telegram_user_id: int
    telegram_username: str | None
    display_name: str
    auth_date: int
```

Правила:

- `telegram_user_id` берётся только из успешно проверенного `initData.user.id`;
- `telegram_username` не используется для авторизации;
- `auth_date` — Unix timestamp исходной Telegram-сессии.

### 4.2. AdminUserView

```python
@dataclass(frozen=True)
class AdminUserView:
    username: str
    display_name: str
    client_email: str
    requires_payment: bool
    telegram_linked: bool
    vpn_state: Literal["active", "expired", "disabled", "unknown"]
    expiry_ms: int | None
    expiry_display: str | None
    traffic_used_bytes: int | None
    traffic_used_display: str | None
    last_online_ms: int | None
    last_online_display: str | None
    pending_payment_request_id: int | None
```

Правила вычисления `vpn_state`:

1. `traffic is None` или ошибка чтения → `unknown`.
2. `traffic.enable is False` → `disabled`.
3. `traffic.is_expired is True` → `expired`.
4. Иначе → `active`.

`expiry_ms == 0` означает доступ без срока. В JSON он передаётся как `0`, а не `null`. `null` означает, что состояние неизвестно.

### 4.3. PaymentRequestView

```python
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
```

Внешний Admin API не возвращает `telegram_chat_id`; поле доступно только сервису для уведомления пользователя.

### 4.4. AdminActionResult

```python
@dataclass(frozen=True)
class AdminActionResult:
    action_id: int
    action: Literal[
        "require_payment",
        "set_free",
        "extend_30_days",
        "approve_payment_request",
        "reject_payment_request",
    ]
    target_username: str
    client_email: str
    requires_payment: bool
    vpn_state: Literal["active", "expired", "disabled", "unknown"]
    expiry_ms: int | None
    expiry_display: str | None
    payment_request_id: int | None
    replayed: bool
    notification_sent: bool | None
```

`replayed=True` означает, что ответ восстановлен по уже завершённому `Idempotency-Key`; действие повторно не выполнялось.

`notification_sent` заполняется HTTP- или Telegram-адаптером после попытки уведомления: `True` — отправлено, `False` — отправка не удалась, `None` — у пользователя нет Telegram-привязки или уведомление для действия не требуется.

### 4.5. AdminActionRecord

```python
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
```

### 4.6. AdminSummary

```python
@dataclass(frozen=True)
class AdminSummary:
    total: int
    active: int
    expired: int
    disabled: int
    unknown: int
    requires_payment: int
    pending_payment_requests: int
```

## 5. Контракт конфигурации

В `TelegramConfig` добавляется поле:

```python
admin_mini_app_url: str
```

YAML:

```yaml
telegram:
  admin_mini_app_url: "https://<portal-host>/portal/tg-admin/"
```

Правила:

- пустая строка отключает кнопку Mini App, не влияя на остальные функции бота;
- production URL обязан использовать `https://`;
- URL не содержит токенов, подписей и других секретов;
- значение добавляется в `portal/config.example.yaml` только с плейсхолдером;
- `bot_token` никогда не передаётся браузеру.

## 6. Контракт авторизации Telegram Mini App

Модуль: `portal/app/telegram_webapp_auth.py`.

Публичный интерфейс:

```python
class TelegramInitDataError(ValueError):
    code: Literal[
        "MISSING_INIT_DATA",
        "INVALID_SIGNATURE",
        "INVALID_USER",
        "AUTH_EXPIRED",
        "NOT_ADMIN",
    ]


def validate_admin_init_data(
    raw_init_data: str,
    *,
    bot_token: str,
    admin_chat_ids: frozenset[int],
    now_ts: int | None = None,
    max_age_seconds: int = 600,
) -> AdminPrincipal:
    ...
```

Алгоритм проверки:

1. Отклонить пустую строку.
2. Разобрать query string без потери исходных значений.
3. Извлечь `hash`; не включать его в `data_check_string`.
4. Отсортировать остальные пары по имени и соединить `\n`.
5. Вычислить секрет и HMAC-SHA-256 по алгоритму Telegram Web Apps.
6. Сравнить подпись через constant-time comparison.
7. Разобрать `user` как JSON и проверить целочисленный `user.id`.
8. Проверить `0 <= now_ts - auth_date <= max_age_seconds` с допустимым рассинхроном будущего времени не более 30 секунд.
9. Проверить `user.id in admin_chat_ids`.
10. Вернуть `AdminPrincipal`.

HTTP-клиент передаёт исходную строку в заголовке:

```http
X-Telegram-Init-Data: <raw Telegram.WebApp.initData>
```

Admin API не принимает Telegram user ID отдельным параметром запроса.

## 7. Контракт хранилища TelegramStore

Существующие таблицы сохраняются. Статусы `payment_requests` расширяются значением `processing`.

### 7.1. Новая таблица admin_actions

```sql
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
```

Допустимые `status`: `processing`, `succeeded`, `failed`.

### 7.2. Новые публичные методы

Контрактная ошибка хранилища:

```python
class TelegramStoreError(RuntimeError):
    code: Literal["REQUEST_BUSY", "IDEMPOTENCY_CONFLICT"]

    def __init__(self, code: str) -> None:
        ...
```

`str(exc)` не является частью публичного контракта. Вызывающий код принимает решения только по `exc.code`.

```python
def list_payment_requests(
    self,
    *,
    status: str | None = None,
    limit: int = 100,
) -> list[PaymentRequest]:
    ...


def get_open_payment_request_for_user(
    self,
    username: str,
) -> PaymentRequest | None:
    ...


def claim_payment_request(
    self,
    request_id: int,
    *,
    admin_chat_id: int,
) -> PaymentRequest | None:
    ...


def release_payment_request(
    self,
    request_id: int,
    *,
    admin_chat_id: int,
) -> bool:
    ...


def finalize_payment_request(
    self,
    request_id: int,
    *,
    from_status: Literal["pending", "processing"],
    status: Literal["approved", "rejected"],
    admin_chat_id: int,
) -> bool:
    ...


def begin_admin_action(
    self,
    *,
    idempotency_key: str,
    admin_telegram_id: int,
    action: str,
    target_username: str,
    payment_request_id: int | None = None,
) -> tuple[AdminActionRecord, bool]:
    ...


def complete_admin_action(
    self,
    action_id: int,
    *,
    result_json: str,
) -> None:
    ...


def fail_admin_action(
    self,
    action_id: int,
    *,
    error_code: str,
) -> None:
    ...
```

Семантика:

- `list_payment_requests` сортирует записи по `created_at DESC, id DESC`; `limit` находится в диапазоне 1–100;
- `get_open_payment_request_for_user` считает открытыми `pending` и `processing`;
- `create_payment_request` также запрещает новую заявку при наличии `pending` или `processing`;
- `claim_payment_request` выполняет один условный SQL `UPDATE ... WHERE id=? AND status='pending'`, переводит запись в `processing` и возвращает заявку только победившему запросу;
- `release_payment_request` возвращает `processing → pending` только для того же администратора;
- `finalize_payment_request` выполняет условный переход с обязательной проверкой `from_status` и администратора;
- успешное подтверждение использует `processing → approved`;
- отклонение использует `pending → rejected`; заявка в `processing` не отклоняется;
- `begin_admin_action` возвращает `(record, True)` только для новой записи;
- существующий ключ со статусом `succeeded` возвращает `(record, False)`; вызывающий код восстанавливает результат из `record.result_json` и отмечает его как replay;
- существующий ключ со статусом `failed` возвращает `(record, False)`; вызывающий код возвращает сохранённую ошибку из `record.error_code` без автоматического повтора действия;
- существующий ключ со статусом `processing` выбрасывает `TelegramStoreError(code="REQUEST_BUSY")`;
- если для существующего ключа не совпадает хотя бы одно из полей `admin_telegram_id`, `action`, `target_username` или `payment_request_id`, метод выбрасывает `TelegramStoreError(code="IDEMPOTENCY_CONFLICT")` независимо от статуса записи;
- проверка совпадения параметров выполняется до обработки статуса существующей записи;
- в `result_json` запрещено сохранять секреты и VLESS-данные.

Существующий метод `resolve_payment_request()` сохраняется для обратной совместимости команд на период миграции, но новый сервис использует атомарные методы выше.

## 8. Контракт AdminService

Модуль: новый `portal/app/admin_service.py`.

Зависимости конструктора:

```python
class AdminService:
    def __init__(
        self,
        *,
        config: AppConfig,
        store: TelegramStore,
        xui_ro: XuiDatabase,
        xui_admin: XuiAdmin,
    ) -> None:
        ...
```

Публичный интерфейс:

```python
def get_summary(self) -> AdminSummary:
    ...


def list_users(self) -> list[AdminUserView]:
    ...


def get_user(self, username: str) -> AdminUserView:
    ...


def list_payment_requests(
    self,
    *,
    status: Literal["pending", "approved", "rejected"] = "pending",
) -> list[PaymentRequestView]:
    ...


def require_payment(
    self,
    username: str,
    *,
    principal: AdminPrincipal,
    idempotency_key: str,
) -> AdminActionResult:
    ...


def set_free(
    self,
    username: str,
    *,
    principal: AdminPrincipal,
    idempotency_key: str,
) -> AdminActionResult:
    ...


def extend_default_period(
    self,
    username: str,
    *,
    principal: AdminPrincipal,
    idempotency_key: str,
) -> AdminActionResult:
    ...


def approve_payment_request(
    self,
    request_id: int,
    *,
    principal: AdminPrincipal,
    idempotency_key: str,
) -> AdminActionResult:
    ...


def reject_payment_request(
    self,
    request_id: int,
    *,
    principal: AdminPrincipal,
    idempotency_key: str,
) -> AdminActionResult:
    ...
```

### 8.1. Семантика операций

`require_payment`:

1. Проверить пользователя по `config.users`.
2. Зарегистрировать идемпотентное действие.
3. Вызвать `XuiAdmin.expire_client_now(...)`.
4. Только после успешной записи в 3X-UI вызвать `store.set_requires_payment(username, True)`.
5. Завершить действие и вернуть состояние.

`set_free`:

1. Вызвать `XuiAdmin.clear_client_expiry(...)`.
2. После успеха установить `requires_payment=False`.

`extend_default_period`:

1. Использовать только `config.telegram.payment.days`.
2. Вызвать `XuiAdmin.extend_client(...)`.
3. После успеха установить `requires_payment=True`, сохраняя текущую семантику `/extend`.

`approve_payment_request`:

1. Зарегистрировать идемпотентное действие.
2. Атомарно захватить только `pending` заявку.
3. Проверить соответствие `request.username`, `request.client_email` и текущего `PortalUser`.
4. Продлить на `config.telegram.payment.days`.
5. Перевести заявку `processing → approved`.
6. Не менять `requires_payment`: платный режим сохраняется.
7. При ошибке до изменения 3X-UI вернуть заявку в `pending`.
8. Если 3X-UI уже изменён, а финализация заявки не удалась, зафиксировать `PARTIAL_FAILURE`; автоматическое повторное продление запрещено.

`reject_payment_request`:

1. Не изменять 3X-UI и `billing_policy`.
2. Атомарно перевести только `pending → rejected`.

Все операции возвращают доменные ошибки, а не `HTTPException`:

```python
class AdminServiceError(RuntimeError):
    code: Literal[
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
```

## 9. Контракт HTTP API

Router: `portal/app/tg_admin.py`. Префикс: `/portal/api/tg-admin`.

Каждый endpoint требует `X-Telegram-Init-Data`. Каждый `POST` дополнительно требует `Idempotency-Key` длиной 16–128 ASCII-символов. Рекомендуемый клиентский формат ключа — UUID v4.

Авторизация администратора выполняется раньше зависимостей `AdminService`, `TelegramStore` и `XuiAdmin`. Поэтому запрос без валидного `initData` всегда получает `401/403`, даже если внутреннее хранилище или x-ui временно недоступны.

### 9.1. Чтение

| Метод и путь | Ответ |
|---|---|
| `GET /portal/api/tg-admin/me` | `AdminPrincipal` без `auth_date` |
| `GET /portal/api/tg-admin/summary` | счётчики пользователей и открытых заявок |
| `GET /portal/api/tg-admin/users` | `{ "items": AdminUserView[] }` |
| `GET /portal/api/tg-admin/users/{username}` | `AdminUserView` |
| `GET /portal/api/tg-admin/payment-requests?status=pending` | `{ "items": PaymentRequestView[] }` без `telegram_chat_id` |

`AdminSummary` JSON:

```json
{
  "total": 10,
  "active": 7,
  "expired": 1,
  "disabled": 1,
  "unknown": 1,
  "requires_payment": 6,
  "pending_payment_requests": 2
}
```

### 9.2. Изменения

| Метод и путь | Тело | Действие |
|---|---|---|
| `POST /users/{username}/require-payment` | отсутствует | истечь сейчас, включить оплату |
| `POST /users/{username}/set-free` | отсутствует | бессрочный бесплатный доступ |
| `POST /users/{username}/extend` | отсутствует | продлить на настроенные 30 дней |
| `POST /payment-requests/{id}/approve` | отсутствует | подтвердить заявку и продлить |
| `POST /payment-requests/{id}/reject` | отсутствует | отклонить заявку |

Полные пути начинаются с `/portal/api/tg-admin`.

Успех: HTTP `200` и JSON-представление `AdminActionResult` в `snake_case`.

### 9.3. Ошибки

Единый формат:

```json
{
  "error": {
    "code": "REQUEST_ALREADY_RESOLVED",
    "message": "Заявка уже обработана",
    "retryable": false
  }
}
```

| HTTP | Коды |
|---|---|
| `400` | некорректный путь, статус, заголовок или idempotency key |
| `401` | `MISSING_INIT_DATA`, `INVALID_SIGNATURE`, `INVALID_USER`, `AUTH_EXPIRED` |
| `403` | `NOT_ADMIN` |
| `404` | `USER_NOT_FOUND`, `REQUEST_NOT_FOUND` |
| `409` | `REQUEST_ALREADY_RESOLVED`, `REQUEST_BUSY`, `IDEMPOTENCY_CONFLICT` |
| `500` | `XUI_WRITE_FAILED`, `STORE_WRITE_FAILED`, `PARTIAL_FAILURE` |
| `503` | хранилище или x-ui.db временно недоступны |

Текст исключения SQLite, путь к БД и вывод `systemctl` не возвращаются клиенту. Полные детали пишутся только в серверный лог.

## 10. Контракт страницы Mini App

Страница: `GET /portal/tg-admin/`.

Маршрут возвращает только HTML-оболочку Mini App и не выполняет административных операций. Он может открываться без cookie портала; доступ к данным и действиям всё равно закрыт проверкой Telegram `initData` в Admin API. Разработчику UI разрешена только эта локальная добавка в `main.py`; существующие маршруты и зависимости не изменяются.

Минимальная структура:

1. Верхняя сводка: активные, требуют оплату, ожидают подтверждения.
2. Вкладка «Пользователи» с поиском по `display_name`, `username`, `client_email`.
3. Вкладка «Заявки» с числом ожидающих заявок.
4. Карточка пользователя с состоянием VPN, сроком, трафиком и TG-привязкой.
5. Кнопки: «Продлить на 30 дней», «Требовать оплату», «Бесплатный доступ».
6. Для заявки: «Подтвердить +30 дней» и «Отклонить».

UX-инварианты:

- интерфейс mobile-first и использует цвета `Telegram.WebApp.themeParams`;
- до успешной загрузки `/me` изменяющие кнопки недоступны;
- каждое опасное действие требует отдельного подтверждения с именем пользователя и эффектом;
- после первого нажатия кнопка блокируется до ответа;
- один пользовательский жест создаёт один новый `Idempotency-Key`, повтор HTTP-запроса использует тот же ключ;
- ошибка показывается рядом с действием, без вывода внутренних исключений;
- после успеха обновляются карточка, сводка и список заявок без перезагрузки всей страницы;
- VLESS, QR и subscription URL в DOM не загружаются;
- если Mini App открыт вне Telegram и `initData` пуст, отображается только сообщение «Откройте панель из Telegram-бота».

Frontend не вычисляет права администратора самостоятельно. Наличие кнопок не является механизмом авторизации.

## 11. Контракт запуска из Telegram-бота

При непустом `config.telegram.admin_mini_app_url`:

- бот отправляет администраторам отдельное сообщение с `InlineKeyboardMarkup` и `InlineKeyboardButton` «Админ-панель» типа `web_app`;
- inline-кнопка добавляется только для чатов, прошедших текущую проверку `is_admin(chat_id)`;
- `ReplyKeyboardMarkup` сохраняет только обычные кнопки «Список», «Справка админа», «Статус»;
- запуск через `KeyboardButton.web_app` в reply-клавиатуре запрещён: согласно Telegram `WebAppInitData` при таком запуске пуст, поэтому HMAC-авторизация Admin API невозможна;
- inline-кнопка отправляется вместе с ответом на `/start` администратора и при явном вызове `/admin`;
- существующие slash-команды сохраняются;
- ошибка создания кнопки или открытия Mini App не должна останавливать polling;
- URL берётся только из конфигурации.

Для MVP кнопка меню через `setChatMenuButton` и Main Mini App через BotFather необязательны. Они могут быть добавлены позднее как дополнительные точки входа, но не заменяют admin-only inline-кнопку.

## 12. Уведомления после действий

Router получает notifier через фабрику:

```python
from collections.abc import Awaitable, Callable

AdminUserNotifier = Callable[[str, str], Awaitable[bool | None]]


def create_tg_admin_router(
    *,
    get_config: Callable[[], AppConfig],
    get_store: Callable[[], TelegramStore | None],
    notify_user: AdminUserNotifier,
) -> APIRouter:
    ...
```

Аргументы notifier:

- первый — `target_username` портала;
- второй — готовый текст уведомления без секретов.

Результат notifier:

- `True` — сообщение отправлено;
- `False` — Telegram-вызов завершился ошибкой;
- `None` — пользователь не привязан к Telegram или Telegram-приложение недоступно.

Адаптер notifier в `main.py` использует уже работающие `_telegram_store` и `_telegram_app`; он не создаёт второй экземпляр бота и не запускает отдельный event loop.

После успешных действий сервис возвращает данные, необходимые адаптеру для уведомления привязанного пользователя:

| Действие | Уведомление |
|---|---|
| `require_payment` | требуется оплата, доступ приостановлен |
| `set_free` | включён бесплатный бессрочный доступ |
| `extend_30_days` | срок продлён до `expiry_display` |
| `approve_payment_request` | оплата подтверждена, срок продлён |
| `reject_payment_request` | заявка отклонена |

Отправка Telegram-сообщения выполняется best effort: её ошибка логируется, но не откатывает уже успешную операцию с доступом. API в этом случае возвращает успех с дополнительным полем `notification_sent: false`.

Уведомление отправляется только если `AdminActionResult.replayed is False`. Replay HTTP-запроса не отправляет повторное сообщение и возвращает `notification_sent: null`.

Поскольку методы `AdminService` синхронные, async endpoint вызывает изменяющую сервисную операцию в worker thread, после чего ожидает async notifier в основном event loop. Блокировать event loop синхронной записью SQLite или x-ui запрещено.

## 13. Порядок интеграции подзадач

1. **Разработчик хранилища** реализует методы раздела 7 и тесты конкурентного захвата заявки.
2. **Разработчик сервиса** реализует раздел 8 поверх утверждённого интерфейса хранилища и существующих `XuiDatabase`/`XuiAdmin`.
3. **Разработчик API** реализует проверку Telegram и router по разделам 6 и 9.
4. **Разработчик UI/бота** реализует разделы 5, 10 и 11 после стабилизации JSON-схем API.
5. Тимлид интегрирует минимальные изменения `main.py`, затем запускаются общие тесты.

Зависимости направлены только в одну сторону:

```text
Mini App / Telegram bot
          │
          ▼
      tg_admin API
          │
          ▼
     AdminService
       │       │
       ▼       ▼
TelegramStore  XuiDatabase/XuiAdmin
```

UI и API не выполняют SQL и не вызывают приватные методы `XuiAdmin`.

## 14. Минимальные тесты интерфейсов

### Хранилище

- одновременно захватить одну заявку может только один запрос;
- `create_payment_request` не создаёт вторую открытую заявку при статусе `processing`;
- повторный `Idempotency-Key` возвращает существующее действие;
- конфликт параметров при том же ключе отклоняется;
- существующее действие `processing` приводит к `TelegramStoreError(code="REQUEST_BUSY")`;
- существующее действие `failed` возвращается без повторного выполнения и сохраняет исходный `error_code`;
- параметризованные SQL-запросы используются для всех пользовательских значений.

### Авторизация

- корректный `initData` администратора принимается;
- изменённое поле `user` ломает подпись;
- просроченный `auth_date` отклоняется;
- валидный Telegram-пользователь вне `admin_chat_ids` получает 403;
- `initDataUnsafe` нигде не используется для серверной авторизации.

### Сервис

- `require_payment` вызывает expiry, затем меняет policy;
- `set_free` очищает expiry, затем меняет policy;
- `extend_default_period` использует значение из конфигурации;
- двойное подтверждение заявки не вызывает двойное продление;
- ошибка Xui оставляет заявку `pending`;
- ошибка финализации после успешного Xui отмечается `PARTIAL_FAILURE` и не допускает автоматический повтор.

### API и UI

- каждый endpoint закрыт Telegram-авторизацией;
- при недоступном хранилище запрос без авторизации всё равно получает `401`, а не `503`;
- каждый POST требует `Idempotency-Key`;
- API не возвращает `bot_token`, UUID, VLESS или subscription URL;
- успешное новое действие вызывает notifier один раз, replay не вызывает notifier повторно;
- ошибка notifier не меняет успешный результат операции и даёт `notification_sent=false`;
- подтверждение опасного действия содержит пользователя и эффект;
- admin Mini App запускается через `InlineKeyboardButton.web_app`; reply-клавиатура не содержит `KeyboardButton.web_app`;
- существующие команды Telegram продолжают работать.

## 15. Критерии приёмки MVP

MVP считается готовым, когда:

1. Администратор открывает панель кнопкой из приватного чата с ботом.
2. Неадминистратор не может получить данные ни через UI, ни прямым HTTP-запросом.
3. Отображаются все пользователи из `config.users`, включая клиентов с ошибкой чтения `x-ui.db`.
4. Для каждого пользователя корректно показаны policy, VPN-состояние, срок и TG-привязка.
5. Все пять изменяющих операций из раздела 9.2 работают и требуют подтверждения.
6. Повтор или гонка запросов не приводит к двойному продлению.
7. Существующая ручная кнопка «Я оплатил» и административные команды работают.
8. Автотесты раздела 14 проходят.
9. В diff отсутствуют изменения `limitIp`, Reality, inbound-портов, firewall и секретов.
10. Деплой выполняется отдельно и только после явного подтверждения тимлида.

## 16. Правило изменения контракта

Если реализация требует изменить поле, endpoint, статус, порядок побочных эффектов или владение файлами, разработчик останавливает эту часть работы и сообщает тимлиду:

1. какой пункт контракта невозможно выполнить;
2. почему;
3. предлагаемое минимальное изменение;
4. какие другие подзадачи оно затрагивает.

До обновления этого файла зависимые разработчики продолжают работу только по неизменившимся контрактам.

---

# Android-клиент Family VPN — проект контракта входа и профиля v1

> Схема входа через существующую учётную запись портала принята тимлидом
> 2026-09-29; локальная реализация разрешена следующим запросом тимлида.
> Это не свидетельство закрытия Android networking gate и не разрешение деплоя.
> Контракт Telegram Mini App выше остаётся версией 0.5 без изменений.

## A1. Пользователь и право на профиль

- Пользователь вводит в Android-приложении существующие `username` и пароль портала.
  Отдельных десяти аккаунтов или выбираемого списка чужих профилей нет.
- Сервер проверяет пароль по `config.users[username].password_hash`. Пароль не
  сохраняется приложением и не включается в токены, профиль или журналы.
- После входа сервер определяет `client_email` и `inbound_remark` только по
  своей записи `PortalUser`. Клиент не может передать или изменить эти значения
  через API. Один пользователь получает только свой VPN-профиль.
- Существующие cookie-сессии портала и ссылки подписки остаются для сайта и
  Hiddify; Android API не принимает их вместо токена устройства.
- До выдачи профиля сервер проверяет политику оплаты и текущее состояние
  клиента в 3X-UI. Отключённому или просроченному клиенту профиль не выдаётся.
  Ошибка чтения 3X-UI возвращается как временная ошибка сервера, а не как
  подтверждённый отзыв доступа.

## A2. Токены устройства

| Токен | Время жизни | Хранение на телефоне | Хранение на сервере |
| --- | --- | --- | --- |
| Access | 15 минут | только в памяти процесса | хеш, связь с пользователем и сессией устройства |
| Refresh | 30 дней | зашифрованный файл в приватном хранилище; ключ в Android Keystore | хеш, связь с пользователем и сессией устройства |

- Токены — случайные непрозрачные значения; API принимает access token в
  `Authorization: Bearer`. Они не являются VLESS credentials.
- Каждый refresh одноразовый: сервер атомарно заменяет его новым токеном,
  продлевая сессию не более чем на 30 дней от последнего успешного обновления.
  Повторное предъявление уже использованного refresh отзывает сессию устройства.
- Выход из приложения отзывает сессию устройства и удаляет локальные токены и
  профиль. Для утерянного устройства требуется отдельная серверная операция
  отзыва его сессии.
- Недоступность API не разрывает уже работающее VPN-соединение и не удаляет
  последний полученный профиль. Явный отказ авторизации не маскируется как
  временная недоступность.
- Отзыв токена устройства сам по себе не отзывает уже выданный VLESS UUID.
  Избирательный отзыв VPN-доступа одного устройства потребует отдельных
  credentials для каждого устройства в будущем; `limitIp` не меняется.

## A3. HTTPS API (проект)

Префикс: `/portal/api/client/v1`. Все ответы с токенами и профилем:
`Cache-Control: no-store`. Секреты не попадают в URL, логи и сообщения об
ошибках. Допускается только HTTPS.

| Метод и путь | Вход | Результат |
| --- | --- | --- |
| `POST /sessions` | `username`, `password`, `device_name` | `access_token`, `expires_in=900`, `refresh_token`, `refresh_expires_in=2592000` |
| `POST /sessions/refresh` | `refresh_token` | новая пара токенов с теми же сроками |
| `DELETE /sessions/current` | access token | отзыв текущей сессии; повторный запрос безопасен |
| `GET /profile` | access token | только `VpnProfile v1` текущего пользователя |

- Для `POST /sessions` действуют ограничения попыток по учётной записи и
  доверенному адресу клиента, одинаковый ответ на неизвестный логин и неверный
  пароль. API не доверяет произвольному `X-Forwarded-For` от клиента.
- Сессии устройств и хеши токенов хранятся в отдельной таблице SQLite;
  `config.yaml` остаётся источником учётных записей. Схема таблицы и
  административный отзыв будут утверждаться перед реализацией backend.
- `401 AUTH_REQUIRED` — отсутствующий, истёкший или отозванный токен;
  `401 INVALID_CREDENTIALS` — неверный логин или пароль;
  `403 HTTPS_REQUIRED` — запрос пришёл без HTTPS;
  `403 VPN_ACCESS_DENIED` — вход успешен, но VPN-клиент отключён или просрочен;
  `429 RATE_LIMITED` — превышены попытки входа;
  `503 PROFILE_UNAVAILABLE` — временно нельзя прочитать профиль.

## A4. VpnProfile v1 (проект)

JSON-поля:

```text
schema_version: 1
profile_id: string              # стабильный непрозрачный ID профиля
server_id: string               # логический ID узла, сейчас один VPS
display_name: string            # имя для интерфейса
expires_at_ms: integer          # 0 = без срока; неизвестное состояние даёт 503
endpoint: {
  address: string
  port: integer
}
vless: {
  uuid: string
  encryption: string
  flow: string | null
}
reality: {
  server_name: string
  public_key: string
  short_id: string
  fingerprint: string
  spider_x: string | null
}
policy: {
  routing: "full_tunnel"
  dns: "remote"
}
```

- Ответ содержит параметры только текущего пользователя, а не `vless://`,
  subscription URL, полный sing-box JSON или данные других пользователей.
- Поля `vless` и `reality` чувствительны: клиент хранит профиль в приватном
  зашифрованном файле с ключом Android Keystore, исключает его из резервного
  копирования и диагностических отчётов.
- `AndroidConfigBuilder` преобразует эту схему в конфиг закреплённой версии
  sing-box. TUN, DNS-серверы, MTU, IPv4/IPv6 и конкретные правила маршрутизации
  определяются отдельным контрактом ConfigBuilder после networking gate.
- Добавление запасных серверов потребует `VpnProfileSet` и отдельного
  утверждения; текущий ответ содержит один профиль.

## A5. Приёмка контракта перед реализацией

Перед деплоем тимлид проверяет маршруты, схему серверных сессий и способ
отзыва потерянного устройства. Минимальные
проверки: чужой профиль недоступен; повтор refresh не создаёт вторую сессию;
logout отзывает сессию; временный сбой API не удаляет локальный профиль;
заблокированный клиент не получает новый профиль; старый сайт и подписки
сохраняют поведение.

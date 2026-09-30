# PROJECT_SUMMARY — Family VPN

> **Назначение файла:** единый контекст для продолжения работы в другом чате / другой нейросети.
> Укажи: «Прочитай `PROJECT_SUMMARY.md` и продолжи задачу …»
> **Секретов здесь нет** — пароли, токены, ключи только на VPS / в `server-info.local.md` (не в git).

---

## 1. Цели проекта

**Семейный (до ~10 человек) управляемый VPN** на собственном VPS:

| Роль | Что делает |
|------|------------|
| **Админ** | 3X-UI (localhost + SSH-туннель); веб `/portal/admin/*`; **Telegram Mini App** + slash-команды бота |
| **Пользователи** | Логинятся на **веб-портал**, получают QR / `vless://` / Clash / Hiddify; бот «Статус» / «Я оплатил» |
| **Автоматизация** | Telegram-бот (оплата, продление), автобиллинг, health-мониторинг, бэкапы |

**Не цель:** публичный коммерческий VPN-сервис. Биллинг — ручной (СБП + подтверждение админом), без ЮKassa.

**Долгосрочно:** второй VPS как запасной узел (`extra_nodes` → Clash AUTO url-test) — код готов, VPS ещё не куплен.

---

## 2. Продакшен-инфраструктура (эталон)

| Параметр | Значение |
|----------|----------|
| VPS | Ubuntu 24.04, публичный IPv4 `<VPS_HOST>` |
| SSH | `vpnadmin@<VPS_HOST>`, ключ `%USERPROFILE%\.ssh\family_vpn` |
| VPN | **Xray** через **3X-UI**, протокол **VLESS + Reality**, порт **443/tcp** |
| Панель 3X-UI | **только `127.0.0.1:<порт>`** — доступ через SSH-туннель |
| Портал | FastAPI на **`127.0.0.1:3180`**, снаружи через nginx `/portal/` |
| Firewall | UFW: 22, 80, 443 |
| Клиенты в панели | `user01` … `user10` (поле **Email** в 3X-UI = `client_email` в config) |

### Ключевые пути на VPS

| Путь | Содержимое |
|------|------------|
| `/etc/x-ui/x-ui.db` | БД 3X-UI (клиенты, inbounds, expiry) |
| `/etc/family-portal/config.yaml` | Конфиг портала (секреты, пользователи, telegram) |
| `/opt/family-portal/` | Код портала + venv |
| `/var/lib/family-portal/` | `bot.db`, `visits.db`, `health-monitor.json` |
| `/var/log/x-ui/access.log` | Access log Xray (для visit stats) |
| `/var/backups/family-vpn/` | Ежедневные архивы бэкапа |
| `/etc/systemd/system/family-portal.service` | Unit портала |

### Локально (Windows)

| Путь | Назначение |
|------|------------|
| `C:\Users\Huawei\Desktop\VPN` | Git-репозиторий |
| `server-info.local.md` | Локальные заметки (IP, домен — **не в git**) |
| `%USERPROFILE%\Desktop\VPN-backups` | Off-site копии бэкапов (pull-backup.ps1) |

---

## 3. Стек технологий

### Сервер

- **Ubuntu 24.04**
- **3X-UI** + **Xray-core** (VLESS, Reality, flow `xtls-rprx-vision`)
- **Nginx** (прокси `/portal/`, ACME, landing)
- **Certbot** / Let's Encrypt
- **UFW**, **fail2ban**
- **systemd** (портал, таймеры backup/billing/health)

### Портал (`portal/`)

| Компонент | Версия / пакет |
|-----------|----------------|
| Python | 3.x (venv на сервере) |
| FastAPI | 0.115.6 |
| Uvicorn | 0.32.1 |
| Jinja2 | шаблоны HTML |
| passlib + bcrypt | хеши паролей |
| itsdangerous | signed cookies + subscription tokens |
| PyYAML | config.yaml |
| qrcode[pil] | QR PNG |
| python-telegram-bot | ~21.9 (polling в lifespan FastAPI) |

### Клиенты (для семьи)

- Android: v2rayNG, **Hiddify** (+ `hiddify-options.json` с портала)
- iOS: клиент с VLESS+Reality
- Windows: **Clash Verge Rev** / Mihomo (YAML с портала)

---

## 4. Архитектура

```
                    ┌─────────────────────────────────────────┐
                    │              VPS (<VPS_HOST>)            │
                    │                                         │
  Клиент VPN ──────►│  Xray :443  VLESS+Reality               │
  (v2rayNG/Hiddify) │       ▲                                 │
                    │       │ читает/пишет                      │
                    │  /etc/x-ui/x-ui.db                      │
                    │       ▲                                 │
                    │       │ RO (ссылки) / RW (billing)      │
                    │  family-portal :3180  (FastAPI)         │
                    │       ▲                                 │
  Браузер ─────────►│  nginx :80  /portal/ ───────────────────│
                    │                                         │
  Telegram ────────►│  Bot polling + Mini App (HTTPS /tg-admin)│
                    │                                         │
  Админ SSH ───────►│  127.0.0.1:панель 3X-UI                │
                    └─────────────────────────────────────────┘

  Windows ПК ──SCP/SSH──► деплой, pull-backup
```

### Потоки

1. **VPN-трафик:** клиент → `:443` → Xray Reality → интернет
2. **Выдача конфигов:** login → dashboard → QR / vless / clash / hiddify
3. **Биллинг:** admin включает «требовать оплату» → expiry=now в x-ui → пользователь «Я оплатил» → admin approve → +N дней (`telegram.payment.days`)
4. **Visit log:** Xray access.log → ingest loop → SQLite → `/portal/admin/visits`
5. **Admin Mini App:** inline-кнопка `web_app` в боте → `/portal/tg-admin/` → Admin API с HMAC `initData`

---

## 5. Структура репозитория

```
VPN/
├── PROJECT_SUMMARY.md          ← этот файл
├── README.md                   ← индекс этапов развёртывания
├── AGENTS.md / agents.md       ← правила для AI (инфра, деплой, красная зона)
├── team-manifest.md            ← роли мультиагентной работы
├── contracts.md                ← контракт Telegram Mini App (v0.5, утверждён)
├── server-info.example.md      ← шаблон локальных заметок
│
├── portal/                     ← FastAPI-приложение
│   ├── app/                    ← Python-модули (см. §6)
│   ├── templates/              ← Jinja2 HTML (+ tg_admin.html)
│   ├── static/                 ← style.css, tg-admin.css, tg-admin.js
│   ├── tests/                  ← pytest (Mini App, AdminService, x-ui)
│   ├── requirements.txt
│   ├── config.example.yaml     ← эталон config.yaml
│   └── scripts/hash.py         ← генерация bcrypt-хешей
│
├── scripts/                    ← bash/ps1 для VPS и Windows
│   ├── 02-hardening.sh
│   ├── 03-bind-panel-localhost.sh
│   ├── 04-nginx-certbot.sh
│   ├── 05-family-portal.sh     ← установка портала на VPS
│   ├── 05-family-portal-hash.py
│   ├── 07-backup.sh
│   ├── 07-smoke-test.sh
│   ├── pull-backup.ps1         ← off-site бэкап на Windows
│   ├── register-pull-backup-task.ps1
│   └── systemd/                ← unit/timer файлы
│       ├── family-portal.service   (генерится 05-family-portal.sh)
│       ├── family-backup.{service,timer}
│       ├── family-backup-notify-fail.service
│       ├── family-billing.{service,timer}
│       └── family-health.{service,timer}
│
├── templates/
│   ├── nginx/
│   │   ├── family-portal.conf  ← proxy /portal/ → :3180
│   │   └── vpn-landing.conf
│   └── landing/index.html      ← заглушка на :80
│
├── docs/
│   ├── overview-vpn.md         ← краткая «картина» (без секретов)
│   ├── setup.md, update.md, backup.md, clients.md
│   ├── clients-family.txt      ← инструкция для родственников
│   ├── stages/                 ← пошаговые гайды 01–08
│   └── context/                ← Barry Cache (факты/ADR, без секретов)
│       ├── INDEX.md, ARCHITECT_HANDOFF.md, PROPOSAL_WORKFLOW.md
│       └── features/family-vpn-core/
│
└── .cursor/rules/vpn.mdc       ← правила для AI (подтверждение, без секретов, 3X-UI localhost)
```

---

## 6. Ключевые модули `portal/app/`

### `main.py` — точка входа FastAPI

- **Lifespan:** visit log ingest loop; Telegram bot polling (если `telegram.enabled`)
- **Auth:** cookie-сессии, rate limit на login
- **Dashboard:** QR, vless, clash/hiddify URLs, MTProxy links (если enabled)
- **Admin HTML:** `/portal/admin/visits`, `/portal/admin/billing` (cookie; **не** через `AdminService` — legacy)
- **Mini App HTML:** `GET /portal/tg-admin/` — оболочка без cookie-auth
- **Admin API:** `/portal/api/tg-admin/*` (`create_tg_admin_router`)
- **Subscriptions:** `/portal/sub/{token}` — Clash YAML / Hiddify base64 links
- **Биллинг UI:** страница 402 `billing_blocked.html` если клиент отключён/expired
- **Clash builder:** `build_clash_yaml_from_vless_link()` + `extra_nodes` → группа AUTO (url-test)

### `config.py`

Dataclasses + `load_config(path)`:
- `AppConfig`, `PortalUser`, `VisitLogConfig`, `TelegramConfig`, `MtproxyConfig`, `ExtraNode`
- Валидация: `session_secret`, `bot_token` при enabled
- `TelegramConfig.admin_mini_app_url` — **HTTPS** без query/fragment; пусто = кнопка Mini App скрыта

### `auth.py`

- bcrypt verify/hash
- Cookie `family_portal_session` (12ч / 30 дней remember-me)
- Subscription tokens (5 лет) для `/portal/sub/{token}`
- Rate limit: 5 попыток / 15 мин по IP

### `xui_db.py` — read-only доступ к 3X-UI

- SQLite URI `mode=ro`
- `get_client_link()` — inbound по `remark` + client по `email` → `vless://`
- `get_client_traffic()` — up/down/last_online из `client_traffics`
- **WIP (незакоммичено):** enable/expiry согласуются с `inbounds.settings` и таблицей `clients` (3X-UI 3.3.1+); нет таблицы — fallback

### `xui_admin.py` — write-доступ к 3X-UI

- `extend_client()`, `expire_client_now()`, `clear_client_expiry()`, `disable_client()`
- Обновляет `inbounds.settings` JSON + `client_traffics`
- **WIP (незакоммичено):** `_update_canonical_client()` пишет `clients`; INSERT `client_traffics` с `inbound_id`
- `restart_xui_background()` → `sudo -n systemctl restart x-ui` (NOPASSWD в sudoers)
- **`limitIp` не трогать**

### `vless.py`

- `build_vless_link()` — совместимо с генерацией 3X-UI (Reality params: pbk, sni, sid, fp, flow)

### `visit_log.py`

- Парсит `/var/log/x-ui/access.log` (regex `accepted tcp:host email:`)
- Агрегирует в SQLite `visit_daily` (client_email, host, day, hits)
- Фоновый `run_visit_log_ingest_loop()` в lifespan
- Admin page: summary + top hosts за N дней

### `telegram_store.py` — SQLite `bot.db`

Таблицы:
- `telegram_links` — привязка portal username ↔ chat_id
- `link_tokens` — одноразовые токены привязки с портала
- `payment_requests` — «Я оплатил»; `pending|processing|approved|rejected`; claim/finalize/release
- `admin_actions` — идемпотентность Mini App/бота
- `billing_policy` — флаг `requires_payment` per user
- `billing_notifications` — антиспам для cron-напоминаний

### `admin_service.py` — оркестрация админ-операций

Единый слой для Mini App и slash-команд бота (не для HTML `/portal/admin/billing`).
- Views: `AdminUserView`, `PaymentRequestView`, `AdminSummary`, `AdminActionResult`
- Действия: `require_payment`, `set_free`, `extend_default_period`, `approve/reject_payment_request`
- Идемпотентность через `TelegramStore.begin_admin_action`

### `telegram_webapp_auth.py`

- HMAC-SHA256 `Telegram.WebApp.initData` (`HMAC_SHA256("WebAppData", bot_token)`)
- `user.id` ∈ `admin_chat_ids`; max age 600s
- **Нельзя** доверять `initDataUnsafe`

### `tg_admin.py` — HTTP Admin API

Префикс `/portal/api/tg-admin`. Header `X-Telegram-Init-Data`. Мутации: `Idempotency-Key` (16–128 printable ASCII).
- GET `/me`, `/summary`, `/users`, `/users/{username}`, `/payment-requests`
- POST require-payment / set-free / extend / approve / reject
- Не отдаёт `telegram_chat_id`, UUID, vless

### `telegram_bot.py` — Telegram-бот (polling)

**Пользователь:** `/start` (`link_{token}`), «Статус», «Я оплатил»

**Админ** (`chat_id in admin_chat_ids`):
- `/start` без привязки к portal user
- Reply: «Список» / «Справка админа» / «Статус» — **без** `KeyboardButton.web_app` (иначе `initData` пуст)
- Отдельное сообщение: inline «Админ-панель» (`WebAppInfo(url=admin_mini_app_url)`)
- `/who /pay /free /extend /admin` через `AdminService`
- `set_my_commands`: default + `BotCommandScopeChat` per admin

### `telegram_notify.py`

- HTTP `sendMessage` без PTB — для cron/health/backup-fail
- `notify_admins(config, text)`

### `billing_cron.py`

- Запуск: `python -m app.billing_cron` (systemd hourly)
- Для `requires_payment` users: напоминания за 3 дня, nudge после expiry, auto-disable просроченных

### `health_monitor.py`

- Проверки: `x-ui` active, TCP `:443`, portal HTTP
- 2 fail подряд → Telegram alert; recovery → «снова работает»
- State: `/var/lib/family-portal/health-monitor.json`

---

## 7. Конфигурация `/etc/family-portal/config.yaml`

Эталон: `portal/config.example.yaml`

```yaml
server:
  host: 127.0.0.1
  port: 3180
public_address: <IP или домен для vless>
session_secret: <openssl rand -hex 32>
xui_db_path: /etc/x-ui/x-ui.db
inbound_remark: family-reality   # remark inbound в 3X-UI

visit_log: { enabled, access_log_path, db_path, retention_days, admin_usernames }
telegram:  { enabled, bot_token, bot_username, admin_chat_ids, db_path,
             admin_mini_app_url, payment, link_token_ttl_seconds }
mtproxy:   { enabled, host, port, secret }   # опционально
extra_nodes: [{ name, vless_link }]           # второй VPS
users:
  - username, password_hash, client_email, display_name
    inbound_remark: ...   # опционально, per-user inbound
```

**Маппинг пользователя:**
- `username` — логин на портале
- `client_email` — поле **Email** клиента в 3X-UI (`user01` и т.д.)
- `admin_usernames` — кто видит HTML `/portal/admin/*` (логин портала)
- `admin_chat_ids` — админы бота и Mini App (Telegram `user.id`)
- Mini App URL: публичный **HTTPS**; HTTP отклоняется в `load_config`

**Права на VPS:**
- `config.yaml`: `root:family-portal`, `640`
- `family-portal` user: read x-ui.db, write для billing; NOPASSWD restart x-ui

---

## 8. HTTP-маршруты портала

| Маршрут | Доступ | Описание |
|---------|--------|----------|
| `GET /health` | public | healthcheck |
| `GET/POST /portal/login` | public | вход |
| `POST /portal/logout` | user | выход |
| `GET /portal/` | user | dashboard |
| `POST /portal/telegram/link` | user | генерация ссылки привязки TG |
| `GET /portal/qr.png` | user | скачать QR |
| `GET /portal/clash.yaml` | user | Clash профиль |
| `GET /portal/hiddify/options.json` | user | настройки Hiddify |
| `GET /portal/sub/{token}` | token | Clash YAML или `?format=hiddify` |
| `GET /portal/sub/{token}.yaml` | token | Clash YAML |
| `GET /portal/admin/visits` | cookie admin | статистика доменов |
| `GET/POST /portal/admin/billing` | cookie admin | кто платит / free (legacy, не AdminService) |
| `GET /portal/tg-admin/` | public HTML | оболочка Mini App |
| `GET/POST /portal/api/tg-admin/*` | Telegram initData | Admin API |
| `GET /portal/mtproxy-qr.png` | user | QR MTProxy (если enabled) |

Nginx: `templates/nginx/family-portal.conf` → proxy на `127.0.0.1:3180`

---

## 9. Systemd-сервисы и таймеры

| Unit | Расписание | Что делает |
|------|------------|------------|
| `family-portal.service` | always | Uvicorn FastAPI + TG bot |
| `x-ui.service` | always | 3X-UI / Xray |
| `family-backup.timer` | daily ~04:30 | `07-backup.sh` |
| `family-backup-notify-fail.service` | OnFailure | TG alert админам |
| `family-billing.timer` | hourly | `billing_cron` |
| `family-health.timer` | every minute | `health_monitor` |

Установка unit-файлов: см. `docs/stages/07-ops.md`, `06-portal.md`

---

## 10. Бэкапы и восстановление

**На VPS:** `scripts/07-backup.sh`
- SQLite safe backup: `x-ui.db`, `bot.db`, `visits.db`
- Configs: nginx, letsencrypt, family-portal unit
- `/var/backups/family-vpn/vpn-backup-YYYYMMDD-HHMMSS.tar.gz`
- Ротация: последние 14

**Off-site (Windows):**
```powershell
powershell -ExecutionPolicy Bypass -File scripts\pull-backup.ps1
# или scheduled task: register-pull-backup-task.ps1 → 07:00 daily
```

**Восстановление:** см. `docs/stages/07-ops.md` §7.2

---

## 11. Деплой и обновление кода

### Паттерн (важно — права!)

```powershell
# 1. SCP на VPS
scp -i "$env:USERPROFILE\.ssh\family_vpn" `
  "C:\Users\Huawei\Desktop\VPN\portal\app\telegram_bot.py" `
  vpnadmin@<VPS_HOST>:/tmp/telegram_bot.py

# 2. SSH (sudo спросит пароль — у vpnadmin нет NOPASSWD для cp)
ssh -t -i "$env:USERPROFILE\.ssh\family_vpn" vpnadmin@<VPS_HOST>
```

```bash
sudo cp /tmp/telegram_bot.py /opt/family-portal/app/telegram_bot.py
sudo chown family-portal:family-portal /opt/family-portal/app/telegram_bot.py
sudo chmod u=rw,go= /opt/family-portal/app/telegram_bot.py
sudo systemctl restart family-portal
sudo systemctl status family-portal --no-pager
sudo journalctl -u family-portal -n 40 --no-pager
```

**Типичная ошибка:** после `scp`/`cp` владелец `vpnadmin` + `chmod 700` → `Could not import module "app.main"`.
**Фикс:** `chown -R family-portal:family-portal /opt/family-portal/app /opt/family-portal/templates`

### Полная установка портала

`sudo bash scripts/05-family-portal.sh` (первичная установка)

### Git workflow (локально)

- Коммиты **только по явному запросу** пользователя
- Перед коммитом — показать diff, спросить «Commit? (yes/no)»
- `.gitattributes`: `*.py`, `*.sh`, `*.service` → LF (CRLF ломает bash/systemd на Linux)

---

## 12. Биллинг — полная логика

```
Admin HTML / Mini App / bot /pay:
  → billing_policy.requires_payment = true
  → expire_client_now()  (expiry = now)

User: dashboard → «Привязать Telegram» → /start link_TOKEN
User: «Я оплатил» → payment_request pending
Admin Mini App или inline Approve → claim processing → extend(days) → approved

Admin Mini App / bot:
  /pay  = require_payment
  /free = set_free (expiry=0)
  /extend = +telegram.payment.days (из Mini App срок не произвольный)
  /who  = список

Канонический путь: AdminService (Mini App + bot).
HTML /portal/admin/billing всё ещё зовёт XuiAdmin напрямую.

Cron (hourly): billing_cron
  → напоминание за 3 дня
  → nudge после expiry каждые 3 дня
  → disable_client если просрочен но enable=1
```

Пользователь с **отключённым/expired** клиентом видит `billing_blocked.html` (HTTP 402) вместо dashboard.

---

## 13. Безопасность (критично не ломать)

1. **3X-UI слушает только `127.0.0.1`** — не `0.0.0.0`
2. Портал только `127.0.0.1:3180`, снаружи через nginx
3. Секреты не в git: `config.yaml`, bot token, Reality keys, SSH keys
4. UFW/firewall команды — только с предупреждением пользователю
5. Не публиковать `vless://`, QR, subscription URLs
6. `limitIp=0` в 3X-UI — иначе mass disconnects (уже фиксили)
7. Mini App: только HMAC `initData`; не `initDataUnsafe`; мутации с Idempotency-Key
8. Кнопка Mini App только `InlineKeyboardButton.web_app`, не reply `KeyboardButton.web_app`

---

## 14. Известные проблемы и решения

| Симптом | Причина / решение |
|---------|-------------------|
| Портал 502 / import error | Права на `/opt/family-portal/app` — см. §11 |
| VPN timeout на 4G | DPI — Hiddify + options.json; или allowlist IP (не лечится маскировкой) |
| MTProxy не помогает | DPI режет не-TG трафик; MTProxy abandoned для общего обхода |
| sudo password required при деплое | `vpnadmin` не NOPASSWD для cp — деплой интерактивно или через root |
| Нет админ-кнопок в боте | chat_id не в `admin_chat_ids`; нужен `/start` после деплоя |
| Нет кнопки Mini App | пустой/`http` `admin_mini_app_url`; нужен HTTPS публичного хоста портала |
| Mini App «откройте из бота» | открыли вне Telegram / reply web_app (initData пуст) |
| Visit log пустой | Access log не включён в 3X-UI или нет прав на `/var/log/x-ui/access.log` |
| Clash не переключает на 2-й VPS | `extra_nodes` не настроен; второй VPS не куплен |
| Срок в панели 3.3.1+ не совпадает | таблица `clients` vs `client_traffics` — правки xui_* ещё не в git / не на VPS |

---

## 15. Состояние git (обновлено 2026-09-19)

**HEAD:** `8cef2fe` fix: launch admin Mini App from inline button
Перед ним: `b9d7981` feat: add Telegram Mini App admin panel

Mini App, AdminService, бот через сервис, тесты auth/API/UI — **уже в git**.

**Незакоммичено (рабочее дерево):**
```
M  .gitignore                         ← barry-cache dirs
M  contracts.md                       ← инвариант 3X-UI 3.3.1+ clients
M  portal/app/xui_admin.py            ← sync таблицы clients + inbound_id
M  portal/app/xui_db.py               ← read enable/expiry с учётом clients
M  portal/templates/dashboard.html    ← «Привязать Telegram» без requires_payment
M  portal/templates/billing_blocked.html
?? PROJECT_SUMMARY.md
?? agents.md  team-manifest.md  docs/context/
?? portal/tests/test_xui_admin.py  test_xui_db.py
```

`billing_cron.py` и `family-billing.{service,timer}` в status могут быть только CRLF.

**Открытая работа:** синхронизация 3X-UI 3.3.1+ (`clients`) — код локально, не закоммичен, деплой на VPS не подтверждён. Mini App на проде нужен HTTPS `telegram.admin_mini_app_url` в `/etc/family-portal/config.yaml`.

**Не куплено:** второй VPS / `extra_nodes`. MTProxy не развивать.

---

## 16. Этапы развёртывания (индекс)

| # | Документ | Суть |
|---|----------|------|
| 1 | `docs/stages/01-infra.md` | VPS, DNS, SSH |
| 2 | `docs/stages/02-hardening.md` | UFW, fail2ban, hardening |
| 3 | `docs/stages/03-xui-reality.md` | 3X-UI + VLESS Reality :443 |
| 4 | `docs/stages/04-nginx-le.md` | Nginx + Let's Encrypt |
| 5 | `docs/stages/05-admin.md` | SSH-туннель к панели |
| 6 | `docs/stages/06-*.md` | Портал, раздача, TG, MTProxy |
| 7 | `docs/stages/07-ops.md` | Backup, health, smoke-test |
| 8 | `docs/stages/08-second-vps.md` | Второй VPS + extra_nodes |

---

## 17. Правила работы с AI

Источники: `.cursor/rules/vpn.mdc`, `agents.md`, `team-manifest.md`, `contracts.md`.

- Все изменения на VPS / git — только после явного yes
- Перед коммитом — diff + «Commit? (yes/no)»
- Не трогать firewall/limitIp/3X-UI наружу; не печатать секреты и vless
- Не править `x-ui.db` руками — только `XuiAdmin`
- Mini App: не расширять MVP (нет создания юзеров, нет произвольного срока, нет платёжного webhook)
- `docs/context/` менять только после yes (Barry Cache / ARCHITECT_HANDOFF)
- Русский, кратко, эксперт; код английский

---

## 18. Быстрые команды (шпаргалка)

```bash
# VPS
curl -s http://127.0.0.1:3180/health
sudo systemctl status family-portal x-ui --no-pager
sudo journalctl -u family-portal -n 50 --no-pager
sudo ss -tlnp | grep -E ':(443|3180)'
sudo sqlite3 /etc/x-ui/x-ui.db "SELECT remark, port FROM inbounds;"
systemctl list-timers --no-pager | grep family

# Health test alert
sudo -u family-portal FAMILY_PORTAL_CONFIG=/etc/family-portal/config.yaml \
  /opt/family-portal/venv/bin/python -m app.health_monitor --test-alert

# Billing cron manual
sudo systemctl start family-billing.service
journalctl -u family-billing.service -n 30 --no-pager
```

```powershell
# Windows off-site backup
cd C:\Users\Huawei\Desktop\VPN
powershell -ExecutionPolicy Bypass -File scripts\pull-backup.ps1
```

---

## 19. Тесты

```
cd portal
# venv с requirements.txt; pytest может быть не в requirements — ставить локально
python -m pytest tests -q
```

Закоммичены: `test_admin_service`, `test_tg_admin`, `test_tg_admin_ui`, `test_telegram_webapp_auth`, `test_telegram_store`, `test_telegram_admin_service_adapter`.
Незакоммичены: `test_xui_admin.py`, `test_xui_db.py` (под WIP 3.3.1+).

---

## 20. Как использовать в новом чате

1. `@PROJECT_SUMMARY.md` + `@agents.md` (правила)
2. Если Mini App / биллинг: ещё `@contracts.md`
3. Задача одной фразой. Не вставляй секреты.

**Стартовый запрос:**
```
Прочитай PROJECT_SUMMARY.md и agents.md. Продолжи Family VPN.
Не деплой и не коммить без yes. Текущий WIP: sync 3X-UI clients (3.3.1+).
Задача: <...>
```

**Доки:** `docs/overview-vpn.md`, `docs/stages/06-portal.md`, `07-ops.md`, `08-second-vps.md`, `docs/context/INDEX.md`, `docs/clients-family.txt`

---

*Обновлено 2026-09-19. Переписывать после крупных изменений архитектуры или деплоя.*

# Итоговая картина: семейный VPN (3X-UI + VLESS/Reality + портал)

Цель: управляемый “семейный” VPN (до ~10 человек), где **админ** работает через 3X-UI, а **пользователи** получают QR/ссылку через веб‑портал.

> В этом файле **нет секретов** (паролей/ключей/токенов). Он пригоден как “контекст” для следующего чата.

## Состав и роли компонентов

- **VPS**: публичный IPv4 `2.26.9.208`
- **3X-UI**: UI для Xray/Xray-core (управление inbound/клиентами)
  - слушает **только localhost** (`127.0.0.1:<порт панели>`)
  - доступ админа: через SSH‑туннель
- **Xray**: VPN‑ядро
  - основной inbound: **VLESS + Reality** на **`443/tcp`**
- **nginx**: внешний HTTP‑вход на `80/tcp`
  - отдаёт `/portal/*` в локальный FastAPI
  - может обслуживать ACME/заглушку
- **family-portal (FastAPI)**: “личный кабинет” для семьи
  - слушает `127.0.0.1:3180`
  - читает `x-ui` базу **read-only** и генерит:
    - QR (png)
    - `vless://` ссылку
    - `hiddify-options.json`
    - `Clash/Mihomo yaml`
- **UFW**: firewall (минимум `22/tcp`, `80/tcp`, `443/tcp`; остальные порты — по необходимости)

## Потоки трафика (как это работает)

### VPN-трафик

1) Клиент (Android/iOS/Windows) подключается к **`2.26.9.208:443/tcp`** по **VLESS+Reality**  
2) На сервере Xray завершает Reality‑рукопожатие и проксирует трафик в Интернет

Reality маскирует соединение под обычный TLS к “целевому” домену через SNI/uTLS fingerprint (на стороне клиента).

### Управление (админ)

Админ НЕ открывает панель наружу. Вместо этого:

- SSH‑туннель с ПК → `127.0.0.1:<порт панели 3X-UI>` на VPS
- дальше работа в UI

### Выдача конфигов (семья)

1) Пользователь открывает `http://<IP или домен>/portal/login`
2) Логинится
3) На `/portal/` получает:
   - QR
   - `vless://` ссылку
   - кнопки скачивания (QR / Hiddify JSON / Clash YAML)

## Где что лежит на VPS (ключевые пути)

- **3X-UI DB**: `/etc/x-ui/x-ui.db`
- **portal config**: `/etc/family-portal/config.yaml`
- **portal code**: `/opt/family-portal/`
- **systemd unit**: `/etc/systemd/system/family-portal.service`

## Логика портала (что он берёт из 3X-UI)

Портал читает таблицу `inbounds` и достаёт inbound по `remark`, затем ищет клиента по `client_email` (это **Email** клиента в 3X-UI).

В `config.yaml`:

- **`inbound_remark`**: inbound по умолчанию (обычно `family-reality`)
- **per-user override**: у конкретного пользователя можно указать `inbound_remark`, если нужно привязать его к другому inbound

Портал умеет отдавать дополнительные файлы:

- **`/portal/hiddify/options.json`**: настройки Hiddify под LTE/4G (TUN/strict-route/DoH и т.п.)
- **`/portal/clash.yaml`**: минимальный YAML (Mihomo/Clash Meta) собранный из текущей `vless://` ссылки

## Деплой/обновление портала (практически)

Проблема, которая уже случалась: `scp` напрямую в `/opt/family-portal` может быть запрещён правами. Рабочая схема:

1) Залить на VPS в `/tmp/...`
2) Скопировать в `/opt/family-portal` под `sudo`
3) **Обязательно** восстановить владельца/права так, чтобы сервисный пользователь мог читать файлы

Критично: если после деплоя каталоги `app/` или `templates/` стали владельцем `vpnadmin` и правами `700`,
то `family-portal` не импортирует `app.main` и сервис начнёт падать с `Could not import module "app.main"`.

Фикс прав:

- `chown -R family-portal:family-portal /opt/family-portal/app /opt/family-portal/templates`
- `chmod -R u=rwX,go= /opt/family-portal/app /opt/family-portal/templates`

## Быстрые проверки

### На VPS

- здоровье портала:
  - `curl http://127.0.0.1:3180/health`
- статус сервиса:
  - `sudo systemctl status family-portal --no-pager`
  - `sudo journalctl -u family-portal -n 80 --no-pager`
- Xray слушает 443:
  - `sudo ss -tlnp | rg ':443'`

### Проверки в БД 3X-UI

- список inbound:
  - `sudo sqlite3 /etc/x-ui/x-ui.db "SELECT remark, port FROM inbounds;"`
- где находится конкретный клиент (например `user05`):
  - `sudo sqlite3 /etc/x-ui/x-ui.db "SELECT remark FROM inbounds WHERE settings LIKE '%user05%';"`

## Клиенты и “мобильные проблемы”

### DPI vs “режим белых списков”

Есть два разных класса проблем:

- **DPI/сигнатуры/UDP‑ограничения** (часто на 4G):
  - лечится клиентскими настройками (TUN, strict‑route, DoH, IPv4‑only, иногда fragmentation/padding)
- **drop‑all allowlist по IP/CIDR** (когда работает только VK/Yandex/MAX):
  - зарубежный VPS обычно становится **физически недоступен** (timeout до `2.26.9.208:443`)
  - это не лечится “маскировкой” на стороне клиента, т.к. трафик не маршрутизируется

### Рекомендованный baseline для семьи

- **Android**:
  - базово: v2rayNG (QR/vless)
  - если на 4G “подключено, но нет интернета”: Hiddify + импорт `hiddify-options.json` с портала
- **iOS**: использовать клиенты, поддерживающие VLESS+Reality (вариант подбирается по доступности в App Store)
- **Windows**:
  - удобно: Clash Verge Rev / Mihomo (можно импортировать `Clash YAML` с портала)

## Безопасность (что важно не сломать)

- 3X-UI панель должна слушать **только `127.0.0.1`**
- портал слушает **только `127.0.0.1:3180`**, наружу — только через nginx `/portal/`
- не хранить пароли/секреты в git:
  - `/etc/family-portal/config.yaml` содержит `password_hash` и `session_secret`
- не публиковать `vless://`, QR, subscription URL в публичных чатах

## Где смотреть инструкции для семьи

- `docs/clients-family.txt` — “пользовательская” инструкция для родственников


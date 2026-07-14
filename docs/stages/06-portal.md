# Этап 6b: Веб-портал для выдачи vless

**Цель:** каждый член семьи логинится на сайте и видит **свою** ссылку + QR. Панель 3X-UI остаётся на `127.0.0.1`.

## Архитектура

```
Браузер → nginx :80 /portal/ → FastAPI 127.0.0.1:3180 → SQLite /etc/x-ui/x-ui.db (read-only)
```

- Отдельный логин/пароль на человека (не общий)
- vless генерируется из inbound `family-reality` + client `user01`…`user10`
- Пароли — bcrypt в `/etc/family-portal/config.yaml` (не в git)

## 6b.1 Подготовка на VPS

### Скопировать код портала

С Windows:

```powershell
scp -i "$env:USERPROFILE\.ssh\family_vpn" -r portal/* vpnadmin@2.26.9.208:/tmp/family-portal/
```

На VPS:

```bash
sudo mkdir -p /opt/family-portal
sudo rsync -a /tmp/family-portal/ /opt/family-portal/
```

### Конфиг

```bash
sudo mkdir -p /etc/family-portal
sudo cp /opt/family-portal/config.example.yaml /etc/family-portal/config.yaml
sudo chmod 640 /etc/family-portal/config.yaml
```

Отредактируй `/etc/family-portal/config.yaml`:

1. `public_address: 2.26.9.208` (твой IP или домен)
2. `session_secret` — `openssl rand -hex 32`
3. Для каждого человека — `username`, `client_email`, `password_hash`

Хеш пароля:

```bash
cd /opt/family-portal
sudo ./venv/bin/python /opt/family-portal/../scripts/05-family-portal-hash.py
# или после установки venv:
python3 /path/to/05-family-portal-hash.py
```

Пример пользователя:

```yaml
  - username: ivan
    password_hash: "$2b$12$..."
    client_email: user01
    display_name: Иван
```

`client_email` = поле **Email** клиента в панели 3X-UI.

## 6b.2 Установка сервиса

```bash
sudo bash 05-family-portal.sh
sudo systemctl status family-portal
curl -s http://127.0.0.1:3180/health
```

Ожидаемо: `{"status":"ok"}`

## 6b.3 Nginx

В `/etc/nginx/sites-available/vpn-landing` добавь блок из [`templates/nginx/family-portal.conf`](../../templates/nginx/family-portal.conf).

```bash
sudo nginx -t && sudo systemctl reload nginx
```

Проверка снаружи (если есть домен на :80):

`http://ТВОЙ_ДОМЕН/portal/login`

Без домена — по IP:

`http://2.26.9.208/portal/login`

## 6b.4 Проверка

1. Войди под `ivan` / пароль из конфига
2. Должны быть QR + vless со `@2.26.9.208:443`
3. Импорт в v2rayNG → `2ip.ru` = IP VPS

## 6b.5 Безопасность

| Мера | Статус |
|------|--------|
| Панель 3X-UI только 127.0.0.1 | обязательно |
| Портал только 127.0.0.1, снаружи nginx | да |
| Отдельный пароль на пользователя | да |
| Rate limit логина (nginx + app) | да |
| Сессия 12 ч, HttpOnly cookie | да |
| БД x-ui read-only | да |
| HTTPS | опционально :8443 + cert (см. 04-nginx-le) |

Рекомендуется **закрыть :2096** в UFW снаружи — подписка 3X-UI не нужна, если есть портал.

```bash
sudo ufw delete allow 2096/tcp   # только если уверен
sudo ufw status
```

> Перед `ufw delete` — предупреждение: убедись, что никто не использует прямую подписку.

## 6b.6 Добавить пользователя

1. Создай клиента `user03` в панели (inbound `family-reality`)
2. Сгенерируй хеш пароля
3. Добавь блок в `config.yaml`
4. `sudo systemctl restart family-portal`

## 6b.7 Обновление

```bash
# scp новый код → /opt/family-portal
sudo systemctl restart family-portal
```

## 6b.8 Статистика посещений (admin)

В `config.yaml`:

```yaml
visit_log:
  enabled: true
  access_log_path: /var/log/x-ui/access.log
  db_path: /var/lib/family-portal/visits.db
  retention_days: 30
  admin_usernames:
    - admin   # username из users, не client_email
```

В 3X-UI: **Panel Settings → Xray → Logs** — включи **Access log** (путь как в config).

Права на VPS:

```bash
sudo mkdir -p /var/lib/family-portal
sudo chown family-portal:family-portal /var/lib/family-portal
sudo chmod 750 /var/lib/family-portal
# если access.log не читается:
sudo chmod o+r /var/log/x-ui/access.log
```

Страница: `/portal/admin/visits` (кнопка видна только admin).

Логируются **домены** (SNI/sniffing), не полные URL на HTTPS.

## 6b.9 Telegram-бот (оплата)

1. Создай бота у [@BotFather](https://t.me/BotFather) → `/newbot` → сохрани **token**.
2. Узнай свой `chat_id` у [@userinfobot](https://t.me/userinfobot).
3. В `config.yaml`:

```yaml
telegram:
  enabled: true
  bot_token: "..."           # только на VPS, chmod 600
  bot_username: "MyVpnBot"    # без @
  admin_chat_ids: [123456789]
  db_path: /var/lib/family-portal/bot.db
  payment:
    amount_rub: 400
    days: 30
    instructions: |
      Переведи 400 ₽ по СБП на +7XXXXXXXXXX.
      В комментарии: user05
```

4. Права для продления в 3X-UI (группа `x-ui` на сервере обычно **нет** — даём `family-portal`):

```bash
sudo chgrp family-portal /etc/x-ui /etc/x-ui/x-ui.db
sudo chmod g+w /etc/x-ui /etc/x-ui/x-ui.db
echo 'family-portal ALL=(root) NOPASSWD: /bin/systemctl restart x-ui' | sudo tee /etc/sudoers.d/family-portal-xui
sudo chmod 440 /etc/sudoers.d/family-portal-xui
```

В `family-portal.service`: `ReadWritePaths=... /etc/x-ui` (каталог, не только файл — SQLite пишет `-wal` рядом).

5. `sudo systemctl restart family-portal`

**Сценарий:** портал → «Привязать Telegram» → в боте «Я оплатил» → админ жмёт **+30 дней**.

**Кто платит:** `/portal/admin/billing` (только admin). По умолчанию все **бесплатно**; включи «Требовать оплату» только нужным пользователям.

## 6b.10 Автобиллинг (напоминания + автовыключение)

Почасовой таймер `family-billing`:
- шлёт в Telegram «истекает через N дн.» за 3 дня до срока (один раз);
- шлёт «доступ приостановлен» после истечения (повтор раз в 3 дня);
- страховка: если клиент просрочен, но 3X-UI ещё не выключил — выключает сам.

Работает только для тех, у кого включено «Требовать оплату» **и** привязан Telegram.
Использует тот же `bot_token` и `bot.db`, что и бот.

Установка:

```bash
sudo cp /opt/family-portal/scripts/systemd/family-billing.service /etc/systemd/system/
sudo cp /opt/family-portal/scripts/systemd/family-billing.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now family-billing.timer
systemctl list-timers family-billing.timer --no-pager
```

Прогнать сейчас и посмотреть лог:

```bash
sudo systemctl start family-billing.service
journalctl -u family-billing.service -n 30 --no-pager
```

| Симптом | Решение |
|---------|---------|
| Бот молчит | `journalctl -u family-portal -n 50`, проверь `bot_token` |
| +30 дней не работает | права на `x-ui.db`, sudoers для `restart x-ui` |
| Админ не видит заявки | `admin_chat_ids` = твой chat_id из @userinfobot |

## Troubleshooting

| Симптом | Решение |
|---------|---------|
| Пустой `pbk=` в ссылке | В панели пересохрани inbound Reality; проверь `realitySettings.settings.publicKey` в БД |
| `@localhost` в ссылке | Исправь `public_address` в config.yaml |
| 502 от nginx | `sudo systemctl status family-portal`, `journalctl -u family-portal -n 50` |
| Permission denied на x-ui.db | `sudo usermod -aG x-ui family-portal`, `chmod g+r /etc/x-ui/x-ui.db` |
| Клиент не найден | `client_email` в yaml = Email в панели |

---

**Готово?** Семья заходит на `/portal/login`. Инструкция для них: [`clients-family.txt`](../clients-family.txt).

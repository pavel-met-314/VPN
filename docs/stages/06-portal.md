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

# Этап 3: 3X-UI + VLESS + Reality

**Цель:** Xray с inbound VLESS+Reality на порту 443, панель только на localhost.

## 3.1 Установка 3X-UI

Официальный скрипт (полное содержимое — проверь перед запуском):

```bash
# Репозиторий: https://github.com/MHSanaei/3x-ui
bash <(curl -Ls https://raw.githubusercontent.com/MHSanaei/3x-ui/master/install.sh)
```

Во время установки:
- Запомни **логин/пароль** панели (или сразу смени)
- Запомни **порт панели** (часто случайный, например 2053)

Проверка:

```bash
sudo x-ui status
```

## 3.2 Привязать панель к 127.0.0.1

**Обязательно** — панель не должна слушать `0.0.0.0`.

Скрипт из репо:

```bash
sudo bash 03-bind-panel-localhost.sh
```

Или вручную через меню:

```bash
sudo x-ui
# Выбери: 6) Reset Settings → WebBasePath / порт при необходимости
# В настройках панели (через туннель): Settings → Panel listen IP → 127.0.0.1
```

Проверка на сервере:

```bash
ss -tlnp | grep -E 'x-ui|2053'
```

Должно быть `127.0.0.1:ПОРТ`, **не** `0.0.0.0`.

## 3.3 Создать inbound VLESS + Reality

Доступ к панели — через SSH-туннель (см. [05-admin.md](05-admin.md)):

```powershell
ssh -i "$env:USERPROFILE\.ssh\family_vpn" -L 8080:127.0.0.1:ПОРТ_ПАНЕЛИ vpnadmin@ВАШ_IP
```

Браузер: `http://127.0.0.1:8080/ПУТЬ_ПАНЕЛИ`

### Inbound (Inbounds → Add Inbound)

| Поле | Значение |
|------|----------|
| Remark | `family-reality` |
| Protocol | `vless` |
| Port | `443` |
| Transmission | `TCP` |
| Security | `Reality` |
| uTLS | `chrome` |
| Flow | `xtls-rprx-vision` |

### Reality settings

| Поле | Значение |
|------|----------|
| Dest | `www.microsoft.com:443` |
| Server Names (SNI) | `www.microsoft.com` |
| Private Key / Public Key | Сгенерировать в панели (кнопка Get New Cert / Generate) |
| Short ID | Сгенерировать (1–8 hex символов) |

> `dest` и `serverNames` должны совпадать с реальным TLS-сайтом. `www.microsoft.com` — проверенный вариант.

### Sniffing

Включить: HTTP, TLS, QUIC (по умолчанию в новых версиях).

## 3.4 Создать 10 клиентов

В том же inbound → **Clients** → Add Client × 10:

| Email / Remark | Назначение |
|----------------|------------|
| `user01` … `user10` | По одному на человека |

Для каждого:
- Flow: `xtls-rprx-vision`
- Limit IP: `2` (телефон + ноут) — опционально

## 3.5 Проверка на сервере

```bash
sudo ss -tlnp | grep ':443'
sudo x-ui log | tail -30
```

Порт 443 должен слушать `xray`.

## 3.6 Важно: конфликт с Nginx

На этапе 4 Nginx займёт 443 для HTTPS-заглушки. **Порядок:**

**Вариант A (рекомендуется для новичка):** сначала этап 4 (Nginx на 443), потом Reality на **другом порту** (например 8443) — проще с Let's Encrypt.

**Вариант B (как в плане):** Reality на 443, Nginx на 80 только до получения сертификата, затем **fallback**: Nginx не на 443, заглушка через отдельный поддомен или Reality единственный на 443.

Для семейного VPN **оставляем Reality на 443** — Nginx слушает только **80** (редирект + ACME). HTTPS-заглушка на домене не обязательна для работы VPN; сканеры видят Reality-handshake к `www.microsoft.com`.

Уточнение в [04-nginx-le.md](04-nginx-le.md).

---

**Готово?** → [Этап 4: Nginx + Let's Encrypt](04-nginx-le.md)

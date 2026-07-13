# Этап 6c: MTProto-прокси для Telegram (mtg)

**Цель:** резервный канал для Telegram, если он тормозит/блокируется. Один общий секрет для всех
(вариант A). Портал раздаёт готовую ссылку + QR. Не заменяет vless, работает только для Telegram.

## Архитектура

```
Telegram-клиент → VPS :8443 (mtg, fake-TLS под www.cloudflare.com)
Портал /portal/ → показывает https://t.me/proxy?server=…&port=8443&secret=ee…
```

- Секрет один на инстанс — учёта по людям нет.
- Fake-TLS маскирует трафик под TLS-хендшейк к `www.cloudflare.com`.
- Порт `8444` (443 — Reality, 2096 — подписка, 8443 — второй inbound xray).

## 6c.1 Проверить, что порт свободен

```bash
sudo ss -tlnp | grep -E ':(443|2096|8443|8444)'   # 8444 не должен слушаться
sudo ufw status numbered
```

## 6c.2 Установить mtg

```bash
cd /tmp
MTG_VER=2.1.7
wget https://github.com/9seconds/mtg/releases/download/v${MTG_VER}/mtg-${MTG_VER}-linux-amd64.tar.gz
tar -xf mtg-${MTG_VER}-linux-amd64.tar.gz
sudo install mtg-${MTG_VER}-linux-amd64/mtg /usr/local/bin/mtg
mtg --version
```

## 6c.3 Сгенерировать секрет (fake-TLS)

```bash
mtg generate-secret --hex www.cloudflare.com
# выведет ee<32hex><cloudflare-domain-hex> — сохрани, это secret для config.yaml
```

## 6c.4 systemd-сервис

`/etc/systemd/system/mtg.service`:

```ini
[Unit]
Description=mtg MTProto proxy
After=network.target

[Service]
ExecStart=/usr/local/bin/mtg simple-run -n 1.1.1.1 -t 30s -a 128kib 0.0.0.0:8444 <SECRET>
Restart=always
RestartSec=3
DynamicUser=true
AmbientCapabilities=CAP_NET_BIND_SERVICE
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

`<SECRET>` — ee-секрет из 6c.3.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mtg
sudo systemctl status mtg --no-pager
```

## 6c.5 Открыть порт

> Меняет firewall — выполняй осознанно.

```bash
sudo ufw allow 8444/tcp comment 'mtg telegram proxy'
sudo ufw status numbered
```

## 6c.6 Настроить портал

В `/etc/family-portal/config.yaml`:

```yaml
mtproxy:
  enabled: true
  host: ""            # пусто = public_address
  port: 8444
  secret: "ee..."     # секрет из 6c.3
```

```bash
sudo systemctl restart family-portal
```

На дашборде появится блок «Telegram-прокси»: «Открыть в Telegram», копирование ссылки, QR.

## 6c.7 Проверка

- Открой на телефоне ссылку из блока → Telegram предложит подключить прокси → «Подключить».
- В Telegram: Настройки → Данные и память → Прокси — статус «Подключено».
- Погаси mtg (`sudo systemctl stop mtg`) — прокси в Telegram отвалится (проверка, что трафик реально через него).

## Ограничения

- Один секрет на всех: отозвать доступ у одного человека нельзя без смены секрета для всех.
- Только Telegram. Остальной трафик — через vless.

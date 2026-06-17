# Обновление сервера

Ручной цикл: **раз в 1–3 месяца** или при проблемах с подключением.

## Перед обновлением

1. Snapshot VPS в панели провайдера
2. Локальный бэкап: [`backup.md`](backup.md) → `scripts/07-backup.sh`
3. Проверь, что VPN работает с телефона (запомни для сравнения)

## 1. Обновление Ubuntu

```bash
ssh vpnadmin@ВАШ_IP
sudo apt update
sudo apt upgrade -y
sudo apt autoremove -y
```

Если просят перезагрузку ядра:

```bash
sudo reboot
```

Подожди 1–2 мин, переподключись по SSH.

## 2. Обновление 3X-UI / Xray

```bash
# Полный скрипт установки также обновляет панель:
bash <(curl -Ls https://raw.githubusercontent.com/MHSanaei/3x-ui/master/install.sh)
```

В меню выбери **update** (или следуй подсказкам скрипта).

После обновления:

```bash
sudo bash 03-bind-panel-localhost.sh   # на случай сброса listen
sudo x-ui status
sudo ss -tlnp | grep ':443'
```

## 3. Обновление Nginx / Certbot

```bash
sudo apt install --only-upgrade nginx certbot python3-certbot-nginx
sudo certbot renew --dry-run
sudo nginx -t && sudo systemctl reload nginx
```

## 4. Smoke-test

На сервере:

```bash
sudo bash 07-smoke-test.sh
```

На телефоне:

1. Включи VPN
2. https://2ip.ru — IP VPS
3. Открой YouTube / Telegram — быстрая проверка

## 5. Если что-то сломалось

| Симптом | Действие |
|---------|----------|
| Панель не открывается | SSH-туннель, `sudo x-ui status`, bind 127.0.0.1 |
| VPN не коннектится | `sudo x-ui log`, проверь 443: `ss -tlnp \| grep 443` |
| Нет интернета через VPN | `sudo ufw status`, перезапуск: `sudo systemctl restart x-ui` |
| Всё плохо | Восстанови snapshot у провайдера |

## Календарь

Поставь напоминание в телефоне: **каждые 2 месяца** — «VPN: apt upgrade + x-ui update».

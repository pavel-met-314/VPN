# Этап 7: Финализация, бэкап, smoke-test

**Цель:** сервер готов к долгой работе.

## 7.1 Smoke-test на сервере

```bash
sudo bash 07-smoke-test.sh
```

Ожидаемо: x-ui active, nginx active, ufw active, xray на 443.

## 7.2 Бэкап (авто, ежедневно)

Скрипт `07-backup.sh` делает **безопасный** снимок SQLite-баз (через `sqlite3 .backup`, не
ломается при живой записи) + конфиги, кладёт в `/var/backups/family-vpn/`, хранит последние 14.

Бэкапится: `x-ui.db` (клиенты), `bot.db` (привязки TG, платежи, кто платит), `visits.db`,
`config.yaml`, nginx-конфиг, `letsencrypt`, unit портала.

### Первый прогон вручную

```bash
sudo bash /opt/family-portal/scripts/07-backup.sh
```

### Установить автозапуск (systemd-timer, раз в сутки 04:30)

```bash
sudo apt-get install -y sqlite3
sudo cp /opt/family-portal/scripts/systemd/family-backup.service /etc/systemd/system/
sudo cp /opt/family-portal/scripts/systemd/family-backup.timer /etc/systemd/system/
sudo cp /opt/family-portal/scripts/systemd/family-backup-notify-fail.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now family-backup.timer
```

При падении бэкапа (`OnFailure`) админам в Telegram уходит алерт
(`family-backup-notify-fail.service` → `app.telegram_notify`).

Проверка:

```bash
systemctl list-timers family-backup.timer --no-pager
sudo systemctl start family-backup.service   # прогнать сейчас
ls -lh /var/backups/family-vpn/
```

### Off-site копия на свой ПК (важно!)

Локальный бэкап **не спасёт, если VPS умрёт целиком**. Забирай архивы на свою машину.

Разово / по требованию (Windows PowerShell, из папки проекта):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\pull-backup.ps1
```

Скачает свежий архив в `%USERPROFILE%\Desktop\VPN-backups`, хранит там последние 30.

По расписанию (ежедневно 07:00, PowerShell от своего пользователя):

```powershell
cd C:\Users\Huawei\Desktop\VPN
powershell -ExecutionPolicy Bypass -File scripts\register-pull-backup-task.ps1
Start-ScheduledTask -TaskName FamilyVPN-PullBackup
```

### Восстановление

```bash
# распаковать
mkdir -p /tmp/restore && tar -xzf /var/backups/family-vpn/vpn-backup-<STAMP>.tar.gz -C /tmp/restore
# вернуть базы (портал и x-ui остановить перед этим)
sudo systemctl stop family-portal x-ui
sudo cp /tmp/restore/db/x-ui.db /etc/x-ui/x-ui.db
sudo cp /tmp/restore/db/bot.db /var/lib/family-portal/bot.db
sudo cp /tmp/restore/db/visits.db /var/lib/family-portal/visits.db
sudo cp /tmp/restore/etc/family-portal/config.yaml /etc/family-portal/config.yaml
sudo systemctl start x-ui family-portal
```

## 7.3 Snapshot VPS

В панели провайдера: **Create Snapshot** — «vpn-ready».

## 7.4 Документация

| Файл | Назначение |
|------|------------|
| [`setup.md`](../setup.md) | Что установлено |
| [`update.md`](../update.md) | Как обновлять |
| [`backup.md`](../backup.md) | Как бэкапить |
| [`clients.md`](../clients.md) | Для семьи |

## 7.5 Мониторинг и Telegram-алерты

Раз в минуту проверяются `x-ui.service`, TCP-порт Reality `443` и портал. Алерт
отправляется после двух неудачных проверок подряд; после восстановления приходит
отдельное сообщение. Нужны `telegram.bot_token` и `telegram.admin_chat_ids` в
`/etc/family-portal/config.yaml`; `telegram.enabled` может быть `false`.

```bash
sudo cp /opt/family-portal/scripts/systemd/family-health.service /etc/systemd/system/
sudo cp /opt/family-portal/scripts/systemd/family-health.timer /etc/systemd/system/
sudo systemctl daemon-reload

# сначала проверить доставку сообщения
sudo -u family-portal \
  FAMILY_PORTAL_CONFIG=/etc/family-portal/config.yaml \
  /opt/family-portal/venv/bin/python -m app.health_monitor --test-alert

sudo systemctl enable --now family-health.timer
systemctl list-timers family-health.timer --no-pager
```

Состояние: `/var/lib/family-portal/health-monitor.json`. Логи:

```bash
journalctl -u family-health.service -n 30 --no-pager
```

Ограничение: проверка идёт с VPS и не видит локальную блокировку/плохой маршрут
конкретного мобильного оператора.

## 7.6 Чеклист «VPN готов»

- [ ] DNS указывает на VPS
- [ ] SSH только по ключу, root login off
- [ ] UFW: 22, 80, 443
- [ ] 3X-UI на `127.0.0.1`
- [ ] VLESS+Reality на 443, 10 клиентов
- [ ] Nginx заглушка на 80, certbot timer ok
- [ ] Пароль панели сменён
- [ ] Минимум 1 клиент протестирован с телефона
- [ ] Бэкап + snapshot сделаны
- [ ] `server-info.local.md` заполнен

## 7.7 Напоминание об обновлениях

Календарь: **каждые 2 месяца** → [`update.md`](../update.md).

---

Развёртывание завершено.

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
sudo systemctl daemon-reload
sudo systemctl enable --now family-backup.timer
```

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

По расписанию: Планировщик задач Windows → создать задачу → триггер «Ежедневно» →
действие: `powershell` с аргументами
`-ExecutionPolicy Bypass -File C:\Users\Huawei\Desktop\VPN\scripts\pull-backup.ps1`.

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

## 7.5 Чеклист «VPN готов»

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

## 7.6 Напоминание об обновлениях

Календарь: **каждые 2 месяца** → [`update.md`](../update.md).

---

Развёртывание завершено.

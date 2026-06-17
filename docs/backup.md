# Бэкап

## Что бэкапить

| Что | Путь | Зачем |
|-----|------|-------|
| Конфиг 3X-UI | `/etc/x-ui/` | Inbounds, клиенты, ключи Reality |
| БД панели | `/etc/x-ui/x-ui.db` | Все настройки |
| Nginx site | `/etc/nginx/sites-available/vpn-landing` | Заглушка |
| LE certs | `/etc/letsencrypt/` | Сертификаты (можно перевыпустить) |

## Автоматический скрипт

На VPS (скопируй `scripts/07-backup.sh`):

```bash
sudo bash 07-backup.sh
```

Архив: `/root/vpn-backup-YYYYMMDD-HHMMSS.tar.gz`

Скачать на ПК:

```powershell
scp -i "$env:USERPROFILE\.ssh\family_vpn" vpnadmin@ВАШ_IP:/root/vpn-backup-*.tar.gz C:\Users\Huawei\Desktop\VPN\backups\
```

Папка `backups/` в `.gitignore` — не коммить архивы.

## Snapshot у провайдера

Перед каждым крупным обновлением — **snapshot** в панели VPS. Восстановление за 5 минут.

## Восстановление из архива

```bash
# Остановить панель
sudo systemctl stop x-ui

# Распаковать (путь к архиву подставь свой)
sudo tar -xzf /root/vpn-backup-XXXXXXXX.tar.gz -C /

sudo systemctl start x-ui
sudo nginx -t && sudo systemctl reload nginx
```

## Экспорт inbound вручную

Панель → Inbounds → `family-reality` → Export / скриншот настроек Reality (без публикации ключей).

## Частота

| Событие | Действие |
|---------|----------|
| После первой настройки | Snapshot + локальный бэкап |
| Добавил/удалил пользователя | Опционально бэкап |
| Перед обновлением | Snapshot + бэкап |
| Раз в 3 месяца | Бэкап на ПК |

## Безопасность архивов

Архив содержит **приватные ключи Reality** и UUID клиентов. Храни зашифрованно (диск ПК с BitLocker, не облако без шифрования).

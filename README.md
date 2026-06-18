# Семейный VPN (VLESS + Reality)

Личный VPN на Ubuntu 24.04 для до 10 человек: **3X-UI**, **Xray**, **Nginx**, **Let's Encrypt**.

## Быстрый старт

1. Скопируй `server-info.example.md` → `server-info.local.md` и заполни по ходу.
2. Иди по этапам по порядку — каждый этап = отдельный файл в [`docs/stages/`](docs/stages/).

| Этап | Документ | Скрипт (опционально) |
|------|----------|----------------------|
| 1 | [01-infra.md](docs/stages/01-infra.md) | — |
| 2 | [02-hardening.md](docs/stages/02-hardening.md) | [`scripts/02-hardening.sh`](scripts/02-hardening.sh) |
| 3 | [03-xui-reality.md](docs/stages/03-xui-reality.md) | [`scripts/03-bind-panel-localhost.sh`](scripts/03-bind-panel-localhost.sh) |
| 4 | [04-nginx-le.md](docs/stages/04-nginx-le.md) | [`scripts/04-nginx-certbot.sh`](scripts/04-nginx-certbot.sh) |
| 5 | [05-admin.md](docs/stages/05-admin.md) | — |
| 6 | [06-distribution.md](docs/stages/06-distribution.md), [06-portal.md](docs/stages/06-portal.md), [clients-family.txt](docs/clients-family.txt) | [`scripts/05-family-portal.sh`](scripts/05-family-portal.sh) |
| 7 | [07-ops.md](docs/stages/07-ops.md), [setup.md](docs/setup.md), [update.md](docs/update.md), [backup.md](docs/backup.md) | [`scripts/07-backup.sh`](scripts/07-backup.sh), [`scripts/07-smoke-test.sh`](scripts/07-smoke-test.sh) |

## Безопасность

- Панель 3X-UI слушает **только `127.0.0.1`** — доступ через SSH-туннель.
- Секреты храни в менеджере паролей или `server-info.local.md` (не в git).
- Перед включением UFW — прочитай предупреждение в [02-hardening.md](docs/stages/02-hardening.md).

## Структура репо

```
docs/
  stages/       # пошаговые гайды (copy-paste)
  clients.md    # инструкции для семьи
  setup.md      # что установлено
  update.md     # обновления
  backup.md     # бэкапы
scripts/        # вспомогательные скрипты для VPS
portal/         # веб-портал выдачи vless (FastAPI)
templates/      # nginx, статическая заглушка
```

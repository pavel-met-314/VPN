# Этап 7: Финализация, бэкап, smoke-test

**Цель:** сервер готов к долгой работе.

## 7.1 Smoke-test на сервере

```bash
sudo bash 07-smoke-test.sh
```

Ожидаемо: x-ui active, nginx active, ufw active, xray на 443.

## 7.2 Первый бэкап

```bash
sudo bash 07-backup.sh
```

Скачай архив на ПК — см. [`backup.md`](../backup.md).

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

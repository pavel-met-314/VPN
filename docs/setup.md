# Что установлено на сервере

Справочник по стеку семейного VPN.

## Компоненты

| Компонент | Роль | Порт |
|-----------|------|------|
| Ubuntu 24.04 | ОС | — |
| 3X-UI | Панель управления Xray | `127.0.0.1:ПОРТ` (только локально) |
| Xray | VPN-ядро, VLESS+Reality | `443/tcp` |
| Nginx | HTTP-заглушка, ACME | `80/tcp` |
| Certbot | TLS-сертификаты Let's Encrypt | — |
| UFW | Firewall | 22, 80, 443 |
| fail2ban | Защита SSH | — |

## Архитектура

```
Клиент (v2rayNG/Hiddify/…)
    │ VLESS+Reality, порт 443
    ▼
VPS: Xray маскируется под www.microsoft.com (Reality)
    │
    ▼
Интернет

Админ → SSH-туннель → 127.0.0.1:панель → 3X-UI
Посетитель → http://домен → Nginx заглушка (порт 80)
```

## Файлы на сервере

| Путь | Содержимое |
|------|------------|
| `/etc/x-ui/` | Конфиг и БД 3X-UI |
| `/usr/local/x-ui/` | Бинарники панели |
| `/var/www/vpn-landing/` | Статическая заглушка |
| `/etc/nginx/sites-available/vpn-landing` | Конфиг Nginx |
| `/etc/letsencrypt/live/ДОМЕН/` | Сертификаты LE |

## Inbound Reality (эталон)

- Protocol: VLESS
- Port: 443
- Security: Reality
- Flow: xtls-rprx-vision
- Dest / SNI: www.microsoft.com:443
- uTLS: chrome

## Пользователи

До 10 клиентов: `user01` … `user10` (или по именам).

## Локальные заметки

Заполняй `server-info.local.md` на своём ПК (не в git).

## Связанные документы

- [Этапы развёртывания](../README.md)
- [Обновление](update.md)
- [Бэкап](backup.md)
- [Клиенты](clients.md)

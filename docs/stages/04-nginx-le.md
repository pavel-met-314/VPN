# Этап 4: Nginx + Let's Encrypt

**Цель:** валидный TLS на домене (порт 80), легитимная заглушка. **Reality остаётся на 443** — Nginx на 443 не ставим.

## Почему так

- Xray (VLESS+Reality) занимает **443** — это основной VPN-порт
- Nginx слушает **80**: ACME-challenge + редирект на HTTPS... но HTTPS на 443 занят Xray
- Решение: на **80** — статическая заглушка + `/.well-known/acme-challenge/` для Certbot; сертификат получаем для домена (пригодится если позже понадобится HTTPS на другом порту или поддомене)

Альтернатива с полноценным HTTPS-сайтом: поддомен `www` на Nginx:8443 — усложняет setup; для семьи не нужно.

## 4.1 Установка Nginx

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

## 4.2 Статическая заглушка

На VPS:

```bash
sudo mkdir -p /var/www/vpn-landing
```

Скопируй `templates/landing/index.html` на сервер:

```powershell
scp -i "$env:USERPROFILE\.ssh\family_vpn" templates/landing/index.html vpnadmin@ВАШ_IP:/tmp/
```

На VPS:

```bash
sudo mv /tmp/index.html /var/www/vpn-landing/
sudo chown -R www-data:www-data /var/www/vpn-landing
```

## 4.3 Конфиг Nginx

Замени `YOUR_DOMAIN` на свой домен.

```bash
sudo nano /etc/nginx/sites-available/vpn-landing
```

Вставь содержимое из [`templates/nginx/vpn-landing.conf`](../../templates/nginx/vpn-landing.conf), подставив домен.

```bash
sudo ln -sf /etc/nginx/sites-available/vpn-landing /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

## 4.4 Let's Encrypt (только webroot, порт 80)

```bash
sudo certbot certonly --webroot \
  -w /var/www/vpn-landing \
  -d YOUR_DOMAIN \
  -d www.YOUR_DOMAIN \
  --agree-tos \
  -m your@email.com \
  --non-interactive
```

Проверка автообновления:

```bash
sudo systemctl status certbot.timer
sudo certbot renew --dry-run
```

## 4.5 Проверка

```bash
curl -I http://YOUR_DOMAIN
sudo ss -tlnp | grep -E ':80|:443'
```

- `:80` — nginx
- `:443` — xray (не nginx!)

С браузера: `http://YOUR_DOMAIN` — видна заглушка.

## 4.6 Скрипт (опционально)

```bash
sudo bash 04-nginx-certbot.sh YOUR_DOMAIN your@email.com
```

---

**Готово?** → [Этап 5: админ-доступ](05-admin.md)

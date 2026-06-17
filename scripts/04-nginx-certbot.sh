#!/usr/bin/env bash
# Этап 4: Nginx + Certbot webroot
# Использование: sudo bash 04-nginx-certbot.sh DOMAIN EMAIL
# Пример: sudo bash 04-nginx-certbot.sh myvpn.xyz admin@example.com

set -euo pipefail

DOMAIN="${1:?Укажи домен}"
EMAIL="${2:?Укажи email}"

apt-get install -y nginx certbot python3-certbot-nginx

mkdir -p /var/www/vpn-landing
if [[ ! -f /var/www/vpn-landing/index.html ]]; then
  cat >/var/www/vpn-landing/index.html <<'HTML'
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Welcome</title></head>
<body><h1>Welcome</h1><p>Site is being set up.</p></body>
</html>
HTML
fi
chown -R www-data:www-data /var/www/vpn-landing

cat >/etc/nginx/sites-available/vpn-landing <<NGINX
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN} www.${DOMAIN};

    root /var/www/vpn-landing;
    index index.html;

    location /.well-known/acme-challenge/ {
        root /var/www/vpn-landing;
    }

    location / {
        try_files \$uri \$uri/ =404;
    }
}
NGINX

ln -sf /etc/nginx/sites-available/vpn-landing /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable --now nginx
systemctl reload nginx

certbot certonly --webroot \
  -w /var/www/vpn-landing \
  -d "${DOMAIN}" \
  -d "www.${DOMAIN}" \
  --agree-tos \
  -m "${EMAIL}" \
  --non-interactive

certbot renew --dry-run
echo "Готово. Сертификат: /etc/letsencrypt/live/${DOMAIN}/"

#!/usr/bin/env bash
# Этап 6b: Family VPN Portal (FastAPI на 127.0.0.1)
# Использование: sudo bash 05-family-portal.sh
#
# Перед запуском:
# 1) Скопируй portal/ на сервер в /opt/family-portal
# 2) Создай /etc/family-portal/config.yaml из portal/config.example.yaml
# 3) Сгенерируй пароли: python3 scripts/05-family-portal-hash.py

set -euo pipefail

INSTALL_DIR="/opt/family-portal"
CONFIG_DIR="/etc/family-portal"
CONFIG_FILE="${CONFIG_DIR}/config.yaml"
SERVICE_USER="family-portal"
SERVICE_NAME="family-portal"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Запусти с sudo" >&2
  exit 1
fi

if [[ ! -f "${CONFIG_FILE}" ]]; then
  echo "Нет ${CONFIG_FILE}. Скопируй config.example.yaml и заполни." >&2
  exit 1
fi

apt-get install -y python3 python3-venv python3-pip

id -u "${SERVICE_USER}" &>/dev/null || useradd --system --home "${INSTALL_DIR}" --shell /usr/sbin/nologin "${SERVICE_USER}"

mkdir -p "${CONFIG_DIR}"
chown root:"${SERVICE_USER}" "${CONFIG_DIR}"
chmod 750 "${CONFIG_DIR}"
chown root:"${SERVICE_USER}" "${CONFIG_FILE}"
chmod 640 "${CONFIG_FILE}"

if [[ ! -d "${INSTALL_DIR}/app" ]]; then
  echo "Нет ${INSTALL_DIR}/app. Скопируй каталог portal/ с репо:" >&2
  echo "  scp -r portal/* vpnadmin@IP:/tmp/family-portal/" >&2
  echo "  sudo rsync -a /tmp/family-portal/ ${INSTALL_DIR}/" >&2
  exit 1
fi

python3 -m venv "${INSTALL_DIR}/venv"
"${INSTALL_DIR}/venv/bin/pip" install --upgrade pip
"${INSTALL_DIR}/venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt"

chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"

# Доступ к БД 3X-UI (read-only)
if getent group x-ui >/dev/null; then
  usermod -aG x-ui "${SERVICE_USER}"
fi
if [[ -f /etc/x-ui/x-ui.db ]]; then
  chmod g+r /etc/x-ui/x-ui.db || true
  chgrp x-ui /etc/x-ui/x-ui.db 2>/dev/null || true
fi

cat >/etc/systemd/system/${SERVICE_NAME}.service <<UNIT
[Unit]
Description=Family VPN Portal
After=network.target x-ui.service
Wants=x-ui.service

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${INSTALL_DIR}
Environment=FAMILY_PORTAL_CONFIG=${CONFIG_FILE}
ExecStart=${INSTALL_DIR}/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 3180 --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${INSTALL_DIR}
ReadOnlyPaths=/etc/x-ui /etc/family-portal

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}"

echo ""
echo "Портал: http://127.0.0.1:3180/portal/login"
echo "Добавь location /portal/ в nginx (templates/nginx/family-portal.conf)"
echo "Проверка: curl -s http://127.0.0.1:3180/health"

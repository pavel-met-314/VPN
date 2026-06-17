#!/usr/bin/env bash
# Этап 2: настройка UFW для семейного VPN
# ВНИМАНИЕ: убедись, что SSH по ключу работает ДО запуска!
# Использование: sudo bash 02-hardening.sh [SSH_PORT]
# По умолчанию SSH_PORT=22

set -euo pipefail

SSH_PORT="${1:-22}"

echo "=============================================="
echo " ВНИМАНИЕ: будет включён UFW (firewall)"
echo " Откроются порты: ${SSH_PORT}/tcp (SSH), 80, 443"
echo " Всё остальное входящее — ЗАБЛОКИРОВАНО"
echo "=============================================="
read -r -p "Продолжить? (yes/no): " CONFIRM
if [[ "${CONFIRM}" != "yes" ]]; then
  echo "Отменено."
  exit 1
fi

ufw default deny incoming
ufw default allow outgoing
ufw allow "${SSH_PORT}/tcp" comment 'SSH'
ufw allow 80/tcp comment 'HTTP ACME'
ufw allow 443/tcp comment 'VLESS Reality'
ufw --force enable

echo ""
ufw status verbose

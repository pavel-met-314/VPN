#!/usr/bin/env bash
# Бэкап конфигов VPN
# Использование: sudo bash 07-backup.sh
# Архив: /root/vpn-backup-YYYYMMDD-HHMMSS.tar.gz

set -euo pipefail

STAMP=$(date +%Y%m%d-%H%M%S)
ARCHIVE="/root/vpn-backup-${STAMP}.tar.gz"
TMP="/tmp/vpn-backup-${STAMP}"
mkdir -p "${TMP}"

copy_if_exists() {
  local src="$1"
  local dst="$2"
  if [[ -e "${src}" ]]; then
    mkdir -p "$(dirname "${dst}")"
    cp -a "${src}" "${dst}"
  fi
}

copy_if_exists /etc/x-ui "${TMP}/etc/x-ui"
copy_if_exists /etc/nginx/sites-available/vpn-landing "${TMP}/etc/nginx/sites-available/vpn-landing"
copy_if_exists /var/www/vpn-landing "${TMP}/var/www/vpn-landing"
copy_if_exists /etc/letsencrypt "${TMP}/etc/letsencrypt"

{
  echo "backup_date=${STAMP}"
  uname -a
  x-ui version 2>/dev/null || true
} >"${TMP}/manifest.txt"

tar -czf "${ARCHIVE}" -C "${TMP}" .
rm -rf "${TMP}"

echo "Бэкап создан: ${ARCHIVE}"
ls -lh "${ARCHIVE}"

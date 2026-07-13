#!/usr/bin/env bash
# Бэкап VPN: конфиги + SQLite-базы (безопасный дамп live-баз через sqlite3 .backup).
# Использование: sudo bash 07-backup.sh
# Архив: /var/backups/family-vpn/vpn-backup-YYYYMMDD-HHMMSS.tar.gz
# Ротация: хранится последние ${KEEP} архивов.

set -euo pipefail

KEEP="${KEEP:-14}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/family-vpn}"
# Владелец архивов: чтобы off-site pull по SSH работал без sudo.
# По умолчанию — тот, кто вызвал через sudo (SUDO_USER), иначе root.
BACKUP_OWNER="${BACKUP_OWNER:-${SUDO_USER:-root}}"
STAMP=$(date +%Y%m%d-%H%M%S)
ARCHIVE="${BACKUP_DIR}/vpn-backup-${STAMP}.tar.gz"
TMP="$(mktemp -d /tmp/vpn-backup-XXXXXX)"

trap 'rm -rf "${TMP}"' EXIT

mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"

copy_if_exists() {
  local src="$1" dst="$2"
  if [[ -e "${src}" ]]; then
    mkdir -p "$(dirname "${dst}")"
    cp -a "${src}" "${dst}"
  fi
}

# Безопасный снимок SQLite: .backup не ломается при параллельной записи.
# Фолбэк на cp, если sqlite3 не установлен.
backup_sqlite() {
  local src="$1" dst="$2"
  [[ -e "${src}" ]] || return 0
  mkdir -p "$(dirname "${dst}")"
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "file:${src}?mode=ro" ".backup '${dst}'"
  else
    cp -a "${src}" "${dst}"
  fi
}

# --- SQLite-базы (безопасный дамп) ---
backup_sqlite /etc/x-ui/x-ui.db              "${TMP}/db/x-ui.db"
backup_sqlite /var/lib/family-portal/bot.db  "${TMP}/db/bot.db"
backup_sqlite /var/lib/family-portal/visits.db "${TMP}/db/visits.db"

# --- Конфиги ---
copy_if_exists /etc/x-ui/x-ui.db.bak         "${TMP}/etc/x-ui/x-ui.db.bak"
copy_if_exists /etc/family-portal/config.yaml "${TMP}/etc/family-portal/config.yaml"
copy_if_exists /etc/nginx/sites-available/vpn-landing "${TMP}/etc/nginx/sites-available/vpn-landing"
copy_if_exists /var/www/vpn-landing          "${TMP}/var/www/vpn-landing"
copy_if_exists /etc/letsencrypt              "${TMP}/etc/letsencrypt"
copy_if_exists /etc/systemd/system/family-portal.service "${TMP}/etc/systemd/system/family-portal.service"

{
  echo "backup_date=${STAMP}"
  uname -a
  x-ui version 2>/dev/null || true
} >"${TMP}/manifest.txt"

umask 077
tar -czf "${ARCHIVE}" -C "${TMP}" .
chmod 600 "${ARCHIVE}"

# --- Ротация: оставить последние ${KEEP} ---
mapfile -t OLD < <(ls -1t "${BACKUP_DIR}"/vpn-backup-*.tar.gz 2>/dev/null | tail -n +"$((KEEP + 1))")
if [[ ${#OLD[@]} -gt 0 ]]; then
  rm -f "${OLD[@]}"
fi

# Отдать архивы владельцу, чтобы pull по SSH работал без sudo.
if [[ "${BACKUP_OWNER}" != "root" ]] && id "${BACKUP_OWNER}" >/dev/null 2>&1; then
  chown -R "${BACKUP_OWNER}:${BACKUP_OWNER}" "${BACKUP_DIR}"
fi

echo "Бэкап создан: ${ARCHIVE}"
ls -lh "${ARCHIVE}"
echo "Всего архивов: $(ls -1 "${BACKUP_DIR}"/vpn-backup-*.tar.gz 2>/dev/null | wc -l) (хранится ${KEEP})"

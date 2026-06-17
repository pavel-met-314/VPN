#!/usr/bin/env bash
# Привязка панели 3X-UI к 127.0.0.1
# Использование: sudo bash 03-bind-panel-localhost.sh

set -euo pipefail

DB="/etc/x-ui/x-ui.db"

if [[ ! -f "${DB}" ]]; then
  echo "Ошибка: ${DB} не найден. Сначала установи 3X-UI."
  exit 1
fi

# sqlite3 из пакета
apt-get install -y sqlite3 >/dev/null 2>&1 || true

# webListen в settings (JSON) — типичное поле в 3x-ui
CURRENT=$(sqlite3 "${DB}" "SELECT value FROM settings WHERE key='webListen';" 2>/dev/null || echo "")

if [[ "${CURRENT}" == "127.0.0.1" ]]; then
  echo "webListen уже 127.0.0.1"
else
  sqlite3 "${DB}" "INSERT OR REPLACE INTO settings (key, value) VALUES ('webListen', '127.0.0.1');"
  echo "webListen установлен в 127.0.0.1"
fi

systemctl restart x-ui
sleep 2

echo ""
echo "Проверка слушающих портов:"
ss -tlnp | grep -E 'x-ui|xray' || ss -tlnp | head -20

echo ""
echo "Убедись, что панель на 127.0.0.1, не 0.0.0.0."
echo "Если панель всё ещё на 0.0.0.0 — зайди в Settings панели и выставь Listen IP вручную."

#!/usr/bin/env bash
# Smoke-test после установки или обновления
# Использование: sudo bash 07-smoke-test.sh

set -euo pipefail

FAIL=0

check() {
  local name="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    echo "[OK] ${name}"
  else
    echo "[FAIL] ${name}"
    FAIL=1
  fi
}

echo "=== Smoke-test VPN ==="
echo ""

check "x-ui service" systemctl is-active x-ui
check "nginx service" systemctl is-active nginx
check "ufw active" ufw status | grep -q "Status: active"

echo ""
echo "Порты:"
ss -tlnp | grep -E ':22|:80|:443' || true

echo ""
if ss -tlnp | grep ':443' | grep -q xray; then
  echo "[OK] Xray слушает 443"
else
  echo "[FAIL] Xray не найден на 443"
  FAIL=1
fi

if ss -tlnp | grep -E 'x-ui|xray' | grep -q '127.0.0.1'; then
  echo "[OK] Панель/сервис на localhost (проверь порт панели вручную)"
else
  echo "[WARN] Проверь bind панели: ss -tlnp | grep x-ui"
fi

echo ""
if [[ "${FAIL}" -eq 0 ]]; then
  echo "Все проверки пройдены. Тест с клиента: 2ip.ru"
else
  echo "Есть ошибки — см. docs/update.md"
  exit 1
fi

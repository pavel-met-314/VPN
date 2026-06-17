# Этап 1: VPS, домен, DNS

**Цель:** рабочий сервер с фиксированным IP и доменом, указывающим на него.

## 1.1 Выбор VPS

Рекомендуемые параметры для семьи до 10 человек:

| Параметр | Значение |
|----------|----------|
| ОС | Ubuntu 24.04 LTS |
| CPU / RAM | 1 vCPU / 1 GB (хватит для серфинга) |
| Диск | 20+ GB SSD |
| Локация | EU: DE, FI, NL — ближе к РФ/СНГ по латентности |
| Бюджет | ~$3–5/мес |

Провайдеры в бюджете (на выбор): Hetzner, Aeza, Timeweb Cloud, Vultr, DigitalOcean.

При создании VPS:
- Выбери **Ubuntu 24.04**
- Добавь **SSH-ключ** (см. ниже) — так безопаснее, чем только пароль

## 1.2 SSH-ключ на Windows

В PowerShell (один раз на твоём ПК):

```powershell
ssh-keygen -t ed25519 -C "family-vpn" -f "$env:USERPROFILE\.ssh\family_vpn"
```

Публичный ключ для панели VPS:

```powershell
Get-Content "$env:USERPROFILE\.ssh\family_vpn.pub"
```

Скопируй вывод целиком в поле «SSH key» при создании VPS.

Подключение:

```powershell
ssh -i "$env:USERPROFILE\.ssh\family_vpn" root@ВАШ_IP
```

## 1.3 Домен

Дешёвые зоны: `.xyz`, `.site`, `.click` (~$1–3/год).

Регистратор: Namecheap, Porkbun, Cloudflare Registrar.

## 1.4 DNS

В панели регистратора домена создай записи:

| Имя | Тип | TTL | Значение |
|-----|-----|-----|----------|
| `@` | A | 300 | IP твоего VPS |
| `www` | A | 300 | IP твоего VPS |

Проверка (с твоего ПК, подожди 5–15 мин после сохранения):

```powershell
nslookup твой-домен.xyz
```

Должен вернуть IP VPS.

## 1.5 Зафиксировать в репо

```powershell
cd C:\Users\Huawei\Desktop\VPN
copy server-info.example.md server-info.local.md
```

Заполни IP, домен, провайдера. **Без паролей.**

## 1.6 Проверка доступа

```powershell
ssh -i "$env:USERPROFILE\.ssh\family_vpn" root@ВАШ_IP "uname -a"
```

Ожидаемый вывод: `Ubuntu` и версия ядра.

---

**Готово?** → [Этап 2: hardening](02-hardening.md)

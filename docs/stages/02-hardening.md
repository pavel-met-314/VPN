# Этап 2: Базовая защита Ubuntu

**Цель:** обновлённая ОС, отдельный пользователь, SSH по ключу, firewall.

> Выполняй команды на VPS под `root` (первый вход), дальше — под своим пользователем.

## 2.1 Обновление системы

```bash
apt update && apt upgrade -y
apt install -y curl wget ufw fail2ban unattended-upgrades
timedatectl set-timezone Europe/Moscow
```

## 2.2 Создать sudo-пользователя

Замени `vpnadmin` на своё имя:

```bash
adduser vpnadmin
usermod -aG sudo vpnadmin
mkdir -p /home/vpnadmin/.ssh
cp /root/.ssh/authorized_keys /home/vpnadmin/.ssh/
chown -R vpnadmin:vpnadmin /home/vpnadmin/.ssh
chmod 700 /home/vpnadmin/.ssh
chmod 600 /home/vpnadmin/.ssh/authorized_keys
```

Проверь **в новом окне терминала** (не закрывая root-сессию):

```powershell
ssh -i "$env:USERPROFILE\.ssh\family_vpn" vpnadmin@ВАШ_IP
```

## 2.3 Ужесточить SSH

```bash
sudo sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl reload sshd
```

Смена порта SSH — **опционально** (можно пропустить на первом развёртывании).

## 2.4 UFW — ВНИМАНИЕ

**Перед включением firewall:**

- Убедись, что SSH по ключу работает под `vpnadmin`
- Скрипт откроет только: **22** (SSH), **80** (ACME), **443** (VPN/Reality)
- Если менял SSH-порт — отредактируй скрипт до запуска

Скрипт из репо (скопируй на сервер или выполни вручную):

```bash
# На VPS — скачай скрипт или скопируй содержимое scripts/02-hardening.sh
sudo bash 02-hardening.sh
```

Или вручную:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp comment 'SSH'
sudo ufw allow 80/tcp comment 'HTTP ACME'
sudo ufw allow 443/tcp comment 'VLESS Reality'
sudo ufw --force enable
sudo ufw status verbose
```

## 2.5 Fail2ban (базово)

```bash
sudo systemctl enable --now fail2ban
```

## 2.6 Снимок VPS

В панели провайдера создай **snapshot** чистого сервера — пригодится перед обновлениями.

## 2.7 Проверка

```bash
df -h
free -h
sudo ufw status
```

---

**Готово?** → [Этап 3: 3X-UI + Reality](03-xui-reality.md)

# Забирает свежий бэкап с VPS на локальную машину (off-site копия).
# Запуск вручную:  powershell -ExecutionPolicy Bypass -File scripts\pull-backup.ps1
# Или по расписанию через Планировщик задач Windows (см. docs/stages/07-ops.md).

$ErrorActionPreference = "Stop"

$Server     = "vpnadmin@2.26.9.208"
$KeyPath    = "$env:USERPROFILE\.ssh\family_vpn"
$RemoteDir  = "/var/backups/family-vpn"
$LocalDir   = "$env:USERPROFILE\Desktop\VPN-backups"
$Keep       = 30   # сколько off-site архивов хранить локально

New-Item -ItemType Directory -Force -Path $LocalDir | Out-Null

# Архивы принадлежат BACKUP_OWNER (vpnadmin) → sudo не нужен.
$latest = ssh -i $KeyPath $Server "ls -1t $RemoteDir/vpn-backup-*.tar.gz 2>/dev/null | head -n1"
if (-not $latest) { throw "На сервере нет бэкапов в $RemoteDir (или нет прав чтения)" }
$latest = $latest.Trim()
$name   = Split-Path $latest -Leaf
$dest   = Join-Path $LocalDir $name

if (Test-Path $dest) {
    Write-Host "Уже есть локально: $name"
} else {
    scp -i $KeyPath "${Server}:$latest" $dest
    Write-Host "Скачан: $dest"
}

# Локальная ротация.
Get-ChildItem $LocalDir -Filter "vpn-backup-*.tar.gz" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip $Keep |
    Remove-Item -Force

Write-Host "Off-site архивов локально: $((Get-ChildItem $LocalDir -Filter 'vpn-backup-*.tar.gz').Count) (хранится $Keep)"

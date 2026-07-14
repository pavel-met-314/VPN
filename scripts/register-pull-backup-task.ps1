# Регистрирует ежедневный off-site pull бэкапа в Планировщике Windows.
# Запуск (от своего пользователя, PowerShell):
#   powershell -ExecutionPolicy Bypass -File scripts\register-pull-backup-task.ps1

$ErrorActionPreference = "Stop"

$TaskName = "FamilyVPN-PullBackup"
$ProjectDir = Split-Path -Parent $PSScriptRoot
$ScriptPath = Join-Path $PSScriptRoot "pull-backup.ps1"

if (-not (Test-Path $ScriptPath)) {
    throw "Не найден $ScriptPath"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`"" `
    -WorkingDirectory $ProjectDir

# Каждый день в 07:00 (после серверного бэкапа 04:30 MSK)
$trigger = New-ScheduledTaskTrigger -Daily -At 7:00am

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Off-site copy of family VPN backup from VPS" `
    -Force | Out-Null

Write-Host "Задача создана: $TaskName"
Write-Host "Проверка: Get-ScheduledTask -TaskName $TaskName"
Write-Host "Пробный запуск: Start-ScheduledTask -TaskName $TaskName"

param(
    [string]$SigningDirectory = (Join-Path $env:USERPROFILE '.android\family-vpn-signing')
)

$ErrorActionPreference = 'Stop'
$keyStore = Join-Path $SigningDirectory 'family-vpn-release.p12'
$passwordFile = Join-Path $SigningDirectory 'password.dpapi'
if (-not (Test-Path -LiteralPath $keyStore) -or -not (Test-Path -LiteralPath $passwordFile)) {
    throw 'Permanent Family VPN signing key and DPAPI password file are required.'
}
$sdk = Join-Path $env:LOCALAPPDATA 'Android\Sdk'
$tools = Join-Path $sdk 'build-tools\36.1.0'
$output = Join-Path $PSScriptRoot 'app\build\distribution'
New-Item -ItemType Directory -Force -Path $output | Out-Null
$apk = Join-Path $output 'FamilyVPN-0.1.0-alpha.1-arm64.apk'
$env:ANDROID_HOME = $sdk
$password = Get-Content -LiteralPath $passwordFile -Raw | ConvertTo-SecureString
try {
    $env:FAMILY_VPN_SIGNING_PASSWORD = [System.Net.NetworkCredential]::new('', $password).Password
    Push-Location $PSScriptRoot
    try {
        & .\gradlew.bat :app:assembleRelease :app:lintRelease --console=plain
        if ($LASTEXITCODE -ne 0) { throw 'Release build or lint failed.' }
    } finally {
        Pop-Location
    }
    $unsigned = Join-Path $PSScriptRoot 'app\build\outputs\apk\release\app-release-unsigned.apk'
    $aligned = Join-Path $output 'aligned-unsigned.apk'
    & (Join-Path $tools 'zipalign.exe') -f -p 4 $unsigned $aligned
    if ($LASTEXITCODE -ne 0) { throw 'APK alignment failed.' }
    & (Join-Path $tools 'apksigner.bat') sign --ks $keyStore --ks-key-alias family-vpn `
        --ks-pass env:FAMILY_VPN_SIGNING_PASSWORD --key-pass env:FAMILY_VPN_SIGNING_PASSWORD `
        --out $apk $aligned
    if ($LASTEXITCODE -ne 0) { throw 'APK signing failed.' }
    & (Join-Path $tools 'apksigner.bat') verify --verbose --print-certs $apk
    if ($LASTEXITCODE -ne 0) { throw 'APK signature verification failed.' }
    Get-FileHash -LiteralPath $apk -Algorithm SHA256
} finally {
    Remove-Item Env:FAMILY_VPN_SIGNING_PASSWORD -ErrorAction SilentlyContinue
    $password.Dispose()
}

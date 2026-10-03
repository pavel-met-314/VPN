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
    $badging = @(& (Join-Path $tools 'aapt.exe') dump badging $unsigned)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect APK metadata.' }
    $packageLine = $badging | Where-Object { $_ -match '^package:' } | Select-Object -First 1
    if ($packageLine -notmatch "name='com.familyvpn.android' versionCode='([0-9]+)' versionName='([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)'") {
        throw 'Release APK must have the expected package and four-part version.'
    }
    $versionCode = [int]$Matches[1]
    $versionName = $Matches[2]
    $sdkLine = $badging | Where-Object { $_ -match '^sdkVersion:' } | Select-Object -First 1
    if ($sdkLine -notmatch "^sdkVersion:'([0-9]+)'") { throw 'Cannot inspect APK minSdk.' }
    $minSdk = [int]$Matches[1]
    $output = Join-Path $PSScriptRoot "app\build\distribution\$versionName"
    New-Item -ItemType Directory -Force -Path $output | Out-Null
    $apkName = "FamilyVPN-$versionName-arm64.apk"
    $apk = Join-Path $output $apkName
    $aligned = Join-Path $output 'aligned-unsigned.apk'
    & (Join-Path $tools 'zipalign.exe') -f -p 4 $unsigned $aligned
    if ($LASTEXITCODE -ne 0) { throw 'APK alignment failed.' }
    & (Join-Path $tools 'apksigner.bat') sign --ks $keyStore --ks-key-alias family-vpn `
        --ks-pass env:FAMILY_VPN_SIGNING_PASSWORD --key-pass env:FAMILY_VPN_SIGNING_PASSWORD `
        --out $apk $aligned
    if ($LASTEXITCODE -ne 0) { throw 'APK signing failed.' }
    & (Join-Path $tools 'apksigner.bat') verify --verbose --print-certs $apk
    if ($LASTEXITCODE -ne 0) { throw 'APK signature verification failed.' }
    $hash = (Get-FileHash -LiteralPath $apk -Algorithm SHA256).Hash.ToLowerInvariant()
    $metadata = [ordered]@{
        schema_version = 1
        application_id = 'com.familyvpn.android'
        version_name = $versionName
        version_code = $versionCode
        min_sdk = $minSdk
        abi = 'arm64-v8a'
        apk_asset = $apkName
        sha256 = $hash
    }
    $utf8 = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText((Join-Path $output 'update.json'), ($metadata | ConvertTo-Json) + "`n", $utf8)
    [System.IO.File]::WriteAllText((Join-Path $output 'SHA256SUMS.txt'), "$hash  $apkName`n", $utf8)
    Get-FileHash -LiteralPath $apk -Algorithm SHA256
} finally {
    Remove-Item Env:FAMILY_VPN_SIGNING_PASSWORD -ErrorAction SilentlyContinue
    $password.Dispose()
}

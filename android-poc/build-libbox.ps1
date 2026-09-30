param(
    [Parameter(Mandatory = $true)][string]$SingBoxSource,
    [Parameter(Mandatory = $true)][string]$AndroidNdkPath
)

$ErrorActionPreference = 'Stop'
$expectedCommit = 'af6e64c3b69e6132ebaee0e1a3d24e93903f6709'
$goVersion = (& go version)
if ($LASTEXITCODE -ne 0 -or $goVersion -notmatch '^go version go1\.25\.5 ') {
    throw "Go 1.25.5 is required; got: $goVersion"
}
$source = (Resolve-Path -LiteralPath $SingBoxSource).Path
$ndk = (Resolve-Path -LiteralPath $AndroidNdkPath).Path
$sdk = Join-Path $env:LOCALAPPDATA 'Android\Sdk'
if (-not (Test-Path -LiteralPath (Join-Path $sdk 'platforms\android-36\android.jar'))) {
    throw 'Android SDK 36 is required.'
}
if (-not (Test-Path -LiteralPath (Join-Path $ndk 'source.properties'))) {
    throw 'Android NDK source.properties not found.'
}

$archiveRevision = Join-Path $source 'SOURCE_COMMIT'
if (Test-Path -LiteralPath (Join-Path $source '.git')) {
    $actualCommit = (& git -C $source rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read sing-box Git revision.' }
} elseif (Test-Path -LiteralPath $archiveRevision) {
    $actualCommit = (Get-Content -LiteralPath $archiveRevision -Raw).Trim()
} else {
    throw 'Use the pinned Git checkout or the source bundle from the APK release.'
}
if ($actualCommit -ne $expectedCommit) {
    throw "Expected sing-box v1.14.2 commit $expectedCommit, got $actualCommit"
}

$env:ANDROID_HOME = $sdk
$env:ANDROID_NDK_HOME = $ndk
$env:GOTOOLCHAIN = 'local'
$tags = 'with_gvisor,with_quic,with_wireguard,with_utls,with_naive_outbound,with_clash_api,with_usbip,with_openvpn,with_openconnect,badlinkname,tfogo_checklinkname0,with_tailscale,ts_omit_logtail,ts_omit_ssh,ts_omit_drive,ts_omit_taildrop,ts_omit_webclient,ts_omit_doctor,ts_omit_capture,ts_omit_kube,ts_omit_aws,ts_omit_synology,ts_omit_bird'
$output = Join-Path $PSScriptRoot 'app\libs\libbox.aar'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $output) | Out-Null

Push-Location $source
try {
    $bindArgs = @(
        'bind', '-target', 'android/arm64', '-androidapi', '24',
        '-javapkg=io.nekohasekai', '-libname=box', '-o', $output,
        '-trimpath', '-tags', $tags, '-ldflags',
        '-X github.com/sagernet/sing-box/constant.Version=1.14.2 -X runtime.godebugDefault=multipathtcp=0,tlssha1=1 -checklinkname=0 -s -w -buildid=',
        './experimental/libbox'
    )
    & gomobile @bindArgs
    if ($LASTEXITCODE -ne 0) { throw "gomobile bind failed: $LASTEXITCODE" }
} finally {
    Pop-Location
}

$entries = & tar.exe -tf $output
if ($LASTEXITCODE -ne 0 -or -not ($entries -match '^jni/arm64-v8a/libbox\.so$')) {
    throw 'AAR is missing the arm64 native libbox.so.'
}
Get-FileHash -LiteralPath $output -Algorithm SHA256

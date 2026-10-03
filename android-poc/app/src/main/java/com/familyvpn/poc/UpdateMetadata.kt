package com.familyvpn.poc

import java.net.URI

internal data class UpdateMetadata(
    val schemaVersion: Int,
    val applicationId: String,
    val versionName: String,
    val versionCode: Int,
    val minSdk: Int,
    val abi: String,
    val apkAsset: String,
    val sha256: String,
) {
    fun validate() {
        require(schemaVersion == 1)
        require(applicationId == "com.familyvpn.android")
        require(versionName.matches(Regex("(0|[1-9][0-9]{0,5})(\\.(0|[1-9][0-9]{0,5})){3}")))
        require(versionCode > 0 && minSdk >= 24)
        require(abi == "arm64-v8a")
        require(apkAsset == "FamilyVPN-$versionName-arm64.apk")
        require(sha256.matches(Regex("[0-9a-f]{64}")))
    }
    fun isNewer(installedCode: Int): Boolean = versionCode > installedCode
}

internal object ReleasePolicy {
    const val REPOSITORY = "pavel-met-314/VPN"
    private val hosts = setOf("github.com", "api.github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com")
    fun requireDownloadUrl(value: String) {
        val uri = URI(value)
        require(uri.scheme == "https" && uri.host in hosts && uri.userInfo == null)
        require(uri.port == -1 || uri.port == 443)
    }
    fun requireAssetUrl(value: String, tag: String, name: String) {
        val uri = URI(value)
        requireDownloadUrl(value)
        require(uri.host == "github.com" && uri.rawQuery == null && uri.fragment == null)
        require(uri.path == "/$REPOSITORY/releases/download/$tag/$name")
    }
    fun accepts(tag: String, draft: Boolean, prerelease: Boolean): Boolean =
        !draft && !prerelease && tag.matches(Regex("android-v[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+"))
}

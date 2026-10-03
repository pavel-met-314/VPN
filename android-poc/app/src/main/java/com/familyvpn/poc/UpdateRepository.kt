package com.familyvpn.poc

import android.content.Context
import android.content.Intent
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.atomic.AtomicBoolean

internal data class AvailableUpdate(val metadata: UpdateMetadata, val downloadUrl: String, val size: Long)

internal object ReleaseHttp {
    fun open(value: String): HttpURLConnection {
        var address = value
        repeat(6) {
            ReleasePolicy.requireDownloadUrl(address)
            val connection = URL(address).openConnection() as HttpURLConnection
            connection.connectTimeout = 10_000
            connection.readTimeout = 10_000
            connection.instanceFollowRedirects = false
            connection.useCaches = false
            connection.setRequestProperty("User-Agent", "FamilyVPN/${BuildConfig.VERSION_NAME}")
            connection.setRequestProperty("Accept", "application/vnd.github+json")
            val status = try { connection.responseCode } catch (error: Exception) {
                connection.disconnect(); throw error
            }
            if (status in setOf(301, 302, 303, 307, 308)) {
                val location = connection.getHeaderField("Location")
                connection.disconnect()
                require(!location.isNullOrBlank())
                address = URL(URL(address), location).toString()
            } else {
                if (status != 200) { connection.disconnect(); error("RELEASE_HTTP_$status") }
                return connection
            }
        }
        error("TOO_MANY_REDIRECTS")
    }
    fun json(address: String): String {
        val connection = open(address)
        try {
            return connection.inputStream.use { input ->
                val output = ByteArrayOutputStream()
                val buffer = ByteArray(8192)
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    check(output.size() + count <= 1_048_576)
                    output.write(buffer, 0, count)
                }
                output.toString("UTF-8")
            }
        } finally { connection.disconnect() }
    }
}

internal object UpdateRepository {
    const val ACTION_CHANGED = "com.familyvpn.poc.UPDATE_CHANGED"
    val busy = AtomicBoolean(false)
    @Volatile var failed = false
        private set
    private fun prefs(context: Context) = context.getSharedPreferences("update_state", Context.MODE_PRIVATE)
    fun lastCheck(context: Context): Long = prefs(context).getLong("checked_at", 0)
    fun cached(context: Context): AvailableUpdate? = runCatching {
        val text = prefs(context).getString("candidate", null) ?: return null
        val json = JSONObject(text)
        AvailableUpdate(parseMetadata(json.getJSONObject("metadata")), json.getString("url"), json.getLong("size"))
            .takeIf { it.metadata.isNewer(BuildConfig.VERSION_CODE) }
    }.getOrNull()

    fun check(context: Context): Boolean {
        if (!busy.compareAndSet(false, true)) return true
        val app = context.applicationContext
        publish(app)
        return try {
            val candidate = findUpdate()
            val editor = prefs(app).edit().putLong("checked_at", System.currentTimeMillis())
            if (candidate == null) editor.remove("candidate")
            else editor.putString("candidate", JSONObject()
                .put("metadata", metadataJson(candidate.metadata)).put("url", candidate.downloadUrl)
                .put("size", candidate.size).toString())
            check(editor.commit())
            failed = false
            if (candidate != null) UpdateNotifications.notify(app, candidate.metadata)
            true
        } catch (_: Exception) {
            failed = true
            false
        } finally { busy.set(false); publish(app) }
    }

    private fun findUpdate(): AvailableUpdate? {
        var best: AvailableUpdate? = null
        var page = 1
        while (true) {
            // Обрабатываются все страницы, чтобы порядок публикации не заменял versionCode.
            check(page <= 100)
            val releases = JSONArray(ReleaseHttp.json(
                "https://api.github.com/repos/${ReleasePolicy.REPOSITORY}/releases?per_page=100&page=$page",
            ))
            for (index in 0 until releases.length()) {
                val release = releases.getJSONObject(index)
                val tag = release.getString("tag_name")
                if (!ReleasePolicy.accepts(tag, release.getBoolean("draft"), release.getBoolean("prerelease"))) continue
                val assets = release.getJSONArray("assets")
                val manifest = (0 until assets.length()).map { assets.getJSONObject(it) }
                    .singleOrNull { it.getString("name") == "update.json" } ?: error("MISSING_METADATA")
                val manifestUrl = manifest.getString("browser_download_url")
                ReleasePolicy.requireAssetUrl(manifestUrl, tag, "update.json")
                val metadata = parseMetadata(JSONObject(ReleaseHttp.json(manifestUrl)))
                require(tag == "android-v${metadata.versionName}")
                if (!metadata.isNewer(BuildConfig.VERSION_CODE)) continue
                if (metadata.minSdk > android.os.Build.VERSION.SDK_INT || metadata.abi !in android.os.Build.SUPPORTED_ABIS) continue
                val apk = (0 until assets.length()).map { assets.getJSONObject(it) }
                    .singleOrNull { it.getString("name") == metadata.apkAsset } ?: error("MISSING_APK")
                val url = apk.getString("browser_download_url")
                ReleasePolicy.requireAssetUrl(url, tag, metadata.apkAsset)
                val size = apk.getLong("size")
                require(size in 1..209_715_200)
                val digest = apk.optString("digest")
                require(digest.isBlank() || digest == "null" || digest == "sha256:${metadata.sha256}")
                if (best == null || metadata.versionCode > best.metadata.versionCode) best = AvailableUpdate(metadata, url, size)
            }
            if (releases.length() < 100) break
            page++
        }
        return best
    }

    internal fun parseMetadata(json: JSONObject): UpdateMetadata {
        fun integer(name: String): Int {
            val value = json.get(name)
            require(value is Int || value is Long)
            val number = (value as Number).toLong()
            require(number in 0..Int.MAX_VALUE.toLong())
            return number.toInt()
        }
        fun string(name: String): String = (json.get(name) as? String) ?: error("INVALID_METADATA")
        return UpdateMetadata(integer("schema_version"), string("application_id"), string("version_name"),
            integer("version_code"), integer("min_sdk"), string("abi"), string("apk_asset"), string("sha256"))
            .also { it.validate() }
    }

    private fun metadataJson(value: UpdateMetadata) = JSONObject()
        .put("schema_version", value.schemaVersion).put("application_id", value.applicationId)
        .put("version_name", value.versionName).put("version_code", value.versionCode)
        .put("min_sdk", value.minSdk).put("abi", value.abi)
        .put("apk_asset", value.apkAsset).put("sha256", value.sha256)
    private fun publish(context: Context) = context.sendBroadcast(Intent(ACTION_CHANGED).setPackage(context.packageName))
}

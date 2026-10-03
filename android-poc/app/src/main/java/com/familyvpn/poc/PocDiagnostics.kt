package com.familyvpn.poc

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Build
import io.nekohasekai.libbox.Libbox
import org.json.JSONObject
import java.io.File

internal object PocDiagnostics {
    private const val MAX_LINES = 100

    @Synchronized
    fun record(context: Context, stage: String, code: String = "OK", durationMs: Long? = null) {
        val record = JSONObject()
            .put("time_ms", System.currentTimeMillis())
            .put("app", BuildConfig.VERSION_NAME)
            .put("core", runCatching { Libbox.version() }.getOrDefault("unknown"))
            .put("android", Build.VERSION.RELEASE)
            .put("network", networkType(context))
            .put("stage", stage)
            .put("code", code)
        if (durationMs != null) record.put("duration_ms", durationMs)

        val journal = File(context.filesDir, "poc-events.jsonl")
        runCatching {
            journal.appendText(record.toString() + "\n")
            if (journal.length() > 32_768L) {
                val tail = journal.readLines().takeLast(MAX_LINES)
                journal.writeText(tail.joinToString("\n", postfix = "\n"))
            }
        }
    }

    private fun networkType(context: Context): String {
        val manager = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        return runCatching {
            val capabilities = manager.allNetworks.mapNotNull { manager.getNetworkCapabilities(it) }
                .firstOrNull { !it.hasTransport(NetworkCapabilities.TRANSPORT_VPN) }
                ?: return@runCatching "NONE"
            when {
                capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "WIFI"
                capabilities.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "CELLULAR"
                capabilities.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "ETHERNET"
                else -> "OTHER"
            }
        }.getOrDefault("UNKNOWN")
    }
}

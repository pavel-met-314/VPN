package com.familyvpn.poc

import android.content.Context
import android.content.res.Configuration
import android.content.pm.PackageManager
import org.json.JSONObject
import java.io.File
import java.util.Locale

internal object AppPreferences {
    private fun prefs(context: Context) = context.getSharedPreferences("app_settings", Context.MODE_PRIVATE)
    fun language(context: Context): String = prefs(context).getString("language", null)
        ?: if (Locale.getDefault().language == "ru") "ru" else "en"
    fun theme(context: Context): String = prefs(context).getString("theme", "system") ?: "system"
    fun setLanguage(context: Context, value: String) {
        require(value in setOf("ru", "en"))
        check(prefs(context).edit().putString("language", value).commit())
    }
    fun setTheme(context: Context, value: String) {
        require(value in setOf("system", "light", "dark"))
        check(prefs(context).edit().putString("theme", value).commit())
    }
    fun localized(context: Context): Context {
        val config = Configuration(context.resources.configuration)
        config.setLocale(Locale.forLanguageTag(language(context)))
        return context.createConfigurationContext(config)
    }
    fun exclusions(context: Context): Set<String> =
        prefs(context).getStringSet("bypass", emptySet())!!.toSet() - context.packageName
    fun setExclusions(context: Context, values: Set<String>) {
        check(prefs(context).edit().putStringSet("bypass", values - context.packageName).commit())
    }
}

internal class BypassConflict : IllegalArgumentException("BYPASS_CONFLICT")

internal object BypassPolicy {
    fun merge(included: Set<String>, existing: Set<String>, selected: Set<String>): Set<String> {
        if (included.isNotEmpty() && selected.isNotEmpty()) throw BypassConflict()
        if (included.isNotEmpty() && existing.isNotEmpty()) throw BypassConflict()
        return existing + selected
    }
}

internal object RuntimeConfig {
    fun build(context: Context, selected: Set<String> = AppPreferences.exclusions(context)): String {
        val saved = SecureClientStore.load(context)
        val source = if (saved != null) ClientProfile.buildConfig(saved.profile)
            else ReferenceConfig.prepare(File(context.filesDir, "reference-profile.json").readText())
        val json = JSONObject(source)
        val inbounds = json.getJSONArray("inbounds")
        fun installed(packageName: String): Boolean {
            if (packageName == context.packageName) return false
            return try {
                @Suppress("DEPRECATION")
                context.packageManager.getPackageInfo(packageName, 0)
                true
            } catch (_: PackageManager.NameNotFoundException) { false }
        }
        val activeSelection = selected.filter(::installed).toSet()
        for (index in 0 until inbounds.length()) {
            val tun = inbounds.getJSONObject(index)
            if (tun.optString("type") != "tun") continue
            fun packages(name: String): Set<String> {
                val array = tun.optJSONArray(name) ?: return emptySet()
                return (0 until array.length()).map { array.getString(it) }.toSet()
            }
            val merged = BypassPolicy.merge(packages("include_package"), packages("exclude_package"), activeSelection)
            tun.put("exclude_package", org.json.JSONArray(merged.filter(::installed)))
        }
        return json.toString()
    }
}

package com.familyvpn.poc

import android.app.Activity
import android.app.Instrumentation
import android.content.Intent
import android.os.Bundle
import android.text.method.PasswordTransformationMethod
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.ImageButton
import android.widget.Button
import android.view.KeyEvent
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** Проверки Android JSON/PackageManager на изолированном debug-приложении без credentials. */
class ClientSmokeInstrumentation : Instrumentation() {
    override fun onCreate(arguments: Bundle?) { super.onCreate(arguments); start() }
    override fun onStart() {
        val result = Bundle()
        try {
            val context = targetContext
            check(context.packageName.endsWith(".debug"))
            check(SecureClientStore.load(context) == null) { "Use a disposable debug installation without a portal profile" }
            val profile = File(context.filesDir, "reference-profile.json")
            check(!profile.exists()) { "Existing import must be preserved; use a clean test instance" }
            val metadata = JSONObject()
                .put("schema_version", 1).put("application_id", "com.familyvpn.android")
                .put("version_name", "0.1.0.3").put("version_code", 4).put("min_sdk", 24)
                .put("abi", "arm64-v8a").put("apk_asset", "FamilyVPN-0.1.0.3-arm64.apk").put("sha256", "a".repeat(64))
            check(UpdateRepository.parseMetadata(metadata).versionCode == 4)
            fun reject(action: () -> Unit) {
                var failed = false
                try { action() } catch (_: Exception) { failed = true }
                check(failed)
            }
            reject { UpdateRepository.parseMetadata(JSONObject(metadata.toString()).put("version_code", "4")) }
            reject { UpdateRepository.parseMetadata(JSONObject(metadata.toString()).put("version_code", 4.5)) }
            reject { UpdateRepository.parseMetadata(JSONObject(metadata.toString()).put("version_code", 2147483648L)) }
            reject { UpdateRepository.parseMetadata(JSONObject(metadata.toString()).put("abi", "x86_64")) }
            @Suppress("DEPRECATION")
            val installed = context.packageManager.getInstalledApplications(0)
                .first { it.packageName != context.packageName && it.uid != context.applicationInfo.uid }.packageName
            val tun = JSONObject().put("type", "tun").put("address", JSONArray().put("172.19.0.1/30"))
                .put("exclude_package", JSONArray().put(installed))
            val full = JSONObject().put("inbounds", JSONArray().put(tun))
                .put("outbounds", JSONArray().put(JSONObject().put("type", "direct"))).toString()
            try {
                profile.writeText(full)
                val built = JSONObject(RuntimeConfig.build(context, setOf("invalid.uninstalled.app", context.packageName)))
                val packages = built.getJSONArray("inbounds").getJSONObject(0).getJSONArray("exclude_package")
                check(packages.length() == 1 && packages.getString(0) == installed)
                check(profile.readText() == full)
                tun.remove("exclude_package")
                tun.put("include_package", JSONArray().put(installed))
                profile.writeText(JSONObject().put("inbounds", JSONArray().put(tun))
                    .put("outbounds", JSONArray().put(JSONObject().put("type", "direct"))).toString())
                reject { RuntimeConfig.build(context, setOf(installed)) }
            } finally { profile.delete() }
            PingMonitor.invalidate(context)
            check(PingMonitor.state == "OFF" && PingMonitor.milliseconds == null)
            checkUi()
            result.putString("summary", "15 Android checks passed: 9 policy/runtime checks, password hidden/show/hide/recreation, back icon, active VPN dialog/cancel")
            finish(Activity.RESULT_OK, result)
        } catch (error: Throwable) {
            result.putString("failure", error.stackTraceToString())
            finish(Activity.RESULT_CANCELED, result)
        }
    }

    private fun checkUi() {
        fun views(root: View): List<View> = listOf(root) +
            if (root is ViewGroup) (0 until root.childCount).flatMap { views(root.getChildAt(it)) } else emptyList()
        fun onUi(action: () -> Unit) {
            var failure: Throwable? = null
            runOnMainSync { failure = runCatching(action).exceptionOrNull() }
            failure?.let { throw it }
        }
        fun password(activity: Activity) = views(activity.window.decorView).filterIsInstance<EditText>()
            .single { it.inputType and android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD != 0 }
        val context = targetContext
        var main = startActivitySync(Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        waitForIdleSync()
        try {
            onUi {
                val field = password(main)
                check(field.transformationMethod is PasswordTransformationMethod && !field.isSaveEnabled)
                field.setText("ui-mask-fixture")
                field.setSelection(3, 5)
                val masked = field.transformationMethod.getTransformation(field.text, field)
                check(masked.length == field.text.length && masked.all { it == '\u2022' || it == '\u066D' })
                val toggle = views(main.window.decorView).filterIsInstance<ImageButton>().single {
                    it.contentDescription == AppPreferences.localized(context).getString(R.string.show_password)
                }
                toggle.performClick()
                check(field.transformationMethod == null && field.text.toString() == "ui-mask-fixture")
                check(toggle.contentDescription == AppPreferences.localized(context).getString(R.string.hide_password))
                toggle.performClick()
                check(field.transformationMethod is PasswordTransformationMethod)
                check(field.selectionStart == 3 && field.selectionEnd == 5)
            }
            val monitor = addMonitor(MainActivity::class.java.name, null, false)
            onUi { main.recreate() }
            main = monitor.waitForActivityWithTimeout(10_000) ?: error("RECREATION_TIMEOUT")
            removeMonitor(monitor)
            waitForIdleSync()
            onUi { check(password(main).text.isEmpty() && password(main).transformationMethod is PasswordTransformationMethod) }
            val settings = startActivitySync(Intent(context, SettingsActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            waitForIdleSync()
            val wasRunning = FamilyVpnService.running
            val initialExclusions = AppPreferences.exclusions(context)
            try {
                onUi {
                    FamilyVpnService.running = true
                    views(settings.window.decorView).filterIsInstance<Button>().single {
                        it.text.toString() == AppPreferences.localized(context).getString(R.string.apply)
                    }.performClick()
                }
                waitForIdleSync()
                fun awaitFocus(expected: Boolean) {
                    repeat(50) {
                        var focused = false
                        onUi { focused = settings.hasWindowFocus() }
                        if (focused == expected) return
                        android.os.SystemClock.sleep(100)
                    }
                    error("Dialog window focus did not become $expected")
                }
                awaitFocus(false)
                sendKeyDownUpSync(KeyEvent.KEYCODE_BACK)
                waitForIdleSync()
                awaitFocus(true)
                onUi { check(!settings.isFinishing) }
                check(AppPreferences.exclusions(context) == initialExclusions)
            } finally { onUi { FamilyVpnService.running = wasRunning } }
            onUi {
                val back = views(settings.window.decorView).filterIsInstance<ImageButton>().single {
                    it.contentDescription == AppPreferences.localized(context).getString(R.string.back)
                }
                check(back.drawable != null)
                back.performClick()
                check(settings.isFinishing)
            }
        } finally { onUi { main.finish() } }
    }
}

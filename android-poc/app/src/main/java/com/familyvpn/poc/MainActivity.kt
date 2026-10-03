package com.familyvpn.poc

import android.app.Activity
import android.annotation.SuppressLint
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.res.Configuration
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import android.text.InputType
import android.text.SpannableString
import android.text.Spanned
import android.text.method.PasswordTransformationMethod
import android.text.style.ForegroundColorSpan
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import io.nekohasekai.libbox.Libbox
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

internal object ClientOperations {
    val busy = AtomicBoolean(false)
    val initialized = AtomicBoolean(false)
    @Volatile var message = R.string.profile_ready
    @Volatile var error: Throwable? = null
}

class MainActivity : Activity() {
    private lateinit var ui: UiKit
    private lateinit var stateView: TextView
    private lateinit var profileView: TextView
    private lateinit var portalUrlField: EditText
    private lateinit var usernameField: EditText
    private lateinit var passwordField: EditText
    private lateinit var loginStateView: TextView
    private lateinit var pingButton: Button
    private lateinit var connectButton: Button
    private lateinit var signInButton: Button
    private lateinit var signOutButton: Button
    private val importRequest = 1001
    private val vpnRequest = 1002
    private var appearance = ""
    private val stateReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) = refresh()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        render()
        portalUrlField.setText(savedInstanceState?.getString("portal")
            ?: runCatching { SecureClientStore.load(this)?.portalUrl }.getOrNull())
        usernameField.setText(savedInstanceState?.getString("username"))
        if (ClientOperations.initialized.compareAndSet(false, true)) syncSavedProfile()
    }

    private fun render() {
        val portal = if (::portalUrlField.isInitialized) portalUrlField.text.toString() else ""
        val username = if (::usernameField.isInitialized) usernameField.text.toString() else ""
        ui = UiKit(this)
        appearance = AppPreferences.language(this) + AppPreferences.theme(this) + ui.dark
        val title = ui.line()
        val branding = ui.column()
        val name = SpannableString("Family VPN").apply {
            setSpan(ForegroundColorSpan(ui.accent), 7, length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        }
        branding.addView(ui.text("", 34f, true).apply { text = name }, ui.params(4))
        branding.addView(ui.text(ui.s(R.string.tagline), 15f).apply { setTextColor(ui.secondary) }, ui.params(0))
        title.addView(branding, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        title.addView(ui.iconButton(R.drawable.ic_settings, ui.s(R.string.settings)) {
            startActivity(Intent(this, SettingsActivity::class.java))
        },
            LinearLayout.LayoutParams(ui.dp(50), ui.dp(52)).apply { leftMargin = ui.dp(8) })
        val (layout, _) = ui.root(title)
        val login = ui.card(layout)
        fun fieldLabel(id: Int) = login.addView(ui.text(ui.s(id), 15f).apply { setTextColor(ui.secondary) }, ui.params(8))
        fieldLabel(R.string.portal_address)
        portalUrlField = ui.input("https://portal.example", InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI, R.drawable.ic_link)
        portalUrlField.setText(portal)
        portalUrlField.isSaveEnabled = false
        val addressRow = ui.line()
        addressRow.addView(portalUrlField, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        addressRow.addView(ui.button("×") { portalUrlField.text.clear() }.apply { contentDescription = ui.s(R.string.clear_address) },
            LinearLayout.LayoutParams(ui.dp(48), ui.dp(52)).apply { leftMargin = ui.dp(4) })
        login.addView(addressRow, ui.params(14))
        fieldLabel(R.string.portal_username)
        usernameField = ui.input(ui.s(R.string.portal_username), InputType.TYPE_CLASS_TEXT, R.drawable.ic_user)
        usernameField.setText(username); usernameField.isSaveEnabled = false
        login.addView(usernameField, ui.params(14))
        fieldLabel(R.string.portal_password)
        passwordField = ui.input(ui.s(R.string.portal_password), InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD, R.drawable.ic_lock)
        passwordField.transformationMethod = PasswordTransformationMethod.getInstance()
        passwordField.isSaveEnabled = false
        val passwordRow = ui.line()
        passwordRow.addView(passwordField, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        val visibilityButton = ui.iconButton(R.drawable.ic_eye_off, ui.s(R.string.show_password)) {}
        visibilityButton.setOnClickListener {
            val reveal = passwordField.transformationMethod is PasswordTransformationMethod
            val selectionStart = passwordField.selectionStart
            val selectionEnd = passwordField.selectionEnd
            passwordField.transformationMethod = if (reveal) null else PasswordTransformationMethod.getInstance()
            passwordField.setSelection(selectionStart.coerceAtLeast(0), selectionEnd.coerceAtLeast(0))
            visibilityButton.setImageResource(if (reveal) R.drawable.ic_eye else R.drawable.ic_eye_off)
            visibilityButton.contentDescription = ui.s(if (reveal) R.string.hide_password else R.string.show_password)
        }
        passwordRow.addView(visibilityButton,
            LinearLayout.LayoutParams(ui.dp(48), ui.dp(52)).apply { leftMargin = ui.dp(4) })
        login.addView(passwordRow, ui.params(16))
        signInButton = ui.button(ui.s(R.string.sign_in), primary = true, icon = R.drawable.ic_user) { signIn() }
        login.addView(signInButton, ui.params())
        signOutButton = ui.button(ui.s(R.string.sign_out)) { signOut() }
        signOutButton.background = ui.shape(fill = android.graphics.Color.TRANSPARENT, stroke = android.graphics.Color.TRANSPARENT)
        signOutButton.setTextColor(ui.accent)
        login.addView(signOutButton, ui.params())
        val profileCard = ui.card(layout)
        val profileRow = ui.line()
        profileRow.addView(ImageView(ui.context).apply {
            setImageResource(R.drawable.ic_profile); setColorFilter(ui.accent); background = ui.shape()
            setPadding(ui.dp(10), ui.dp(10), ui.dp(10), ui.dp(10)); importantForAccessibility = android.view.View.IMPORTANT_FOR_ACCESSIBILITY_NO
        }, LinearLayout.LayoutParams(ui.dp(52), ui.dp(62)).apply { rightMargin = ui.dp(14) })
        val profileText = ui.column()
        loginStateView = ui.text("", 14f).apply { setTextColor(ui.secondary) }
        profileView = ui.text("", 17f, true)
        profileText.addView(loginStateView, ui.params(6)); profileText.addView(profileView, ui.params(0))
        profileRow.addView(profileText, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        profileCard.addView(profileRow, ui.params(12))
        stateView = ui.text("", 16f, true).apply { setPadding(ui.dp(12), ui.dp(10), ui.dp(12), ui.dp(10)); background = ui.shape() }
        profileCard.addView(stateView, ui.params())
        pingButton = ui.button("—", icon = R.drawable.ic_refresh) { PingMonitor.refresh(this) }
        val pingRow = ui.line()
        pingRow.addView(ui.text(ui.s(R.string.ping)), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        pingRow.addView(pingButton, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        profileCard.addView(pingRow, ui.params(6))
        profileCard.addView(ui.text(ui.s(R.string.ping_help) + " · " + ui.s(R.string.ping_refresh), 12f).apply { setTextColor(ui.secondary) }, ui.params())
        val controls = ui.card(layout)
        controls.addView(ui.button(ui.s(R.string.import_json), icon = R.drawable.ic_profile) { importProfile() }, ui.params())
        connectButton = ui.button(ui.s(R.string.connect), primary = true, icon = R.drawable.ic_link) { validateAndConnect() }
        controls.addView(connectButton, ui.params())
        controls.addView(ui.button(ui.s(R.string.disconnect), danger = true, icon = R.drawable.ic_disconnect) { disconnect() }, ui.params())
        if (BuildConfig.DEBUG) controls.addView(ui.text(ui.s(R.string.test_version), 12f).apply { setTextColor(ui.secondary) }, ui.params())
        refresh()
    }

    @SuppressLint("UnspecifiedRegisterReceiverFlag")
    override fun onStart() {
        super.onStart()
        val filter = IntentFilter(PocState.ACTION_CHANGED).apply { addAction(PingMonitor.ACTION_CHANGED) }
        if (Build.VERSION.SDK_INT >= 33) registerReceiver(stateReceiver, filter, RECEIVER_NOT_EXPORTED)
        else @Suppress("DEPRECATION") registerReceiver(stateReceiver, filter)
        refresh()
    }
    override fun onResume() {
        super.onResume()
        if (appearance != AppPreferences.language(this) + AppPreferences.theme(this) + UiKit(this).dark) render()
        refresh()
        UpdateScheduler.onOpen(this)
    }
    override fun onStop() { unregisterReceiver(stateReceiver); super.onStop() }
    override fun onConfigurationChanged(newConfig: Configuration) { super.onConfigurationChanged(newConfig); render() }
    override fun onSaveInstanceState(outState: Bundle) {
        outState.putString("portal", portalUrlField.text.toString()); outState.putString("username", usernameField.text.toString())
        super.onSaveInstanceState(outState)
    }

    @Deprecated("Android VPN permission and document picker activity results")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == vpnRequest && resultCode == RESULT_OK) connect()
        if (requestCode == vpnRequest && resultCode != RESULT_OK) PocState.set(this, "DISCONNECTED")
        if (requestCode != importRequest || resultCode != RESULT_OK) return
        val uri = data?.data ?: return
        operation(R.string.validating) {
            val text = contentResolver.openInputStream(uri).use { input ->
                requireNotNull(input)
                val output = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(8192)
                while (true) { val count = input.read(buffer); if (count < 0) break; require(output.size() + count <= 1_048_576); output.write(buffer, 0, count) }
                output.toString("UTF-8")
            }
            SingBoxRuntime.ensureSetup(this)
            Libbox.checkConfig(ReferenceConfig.prepare(text))
            profileFile().writeText(text)
            R.string.local_profile
        }
    }

    private fun importProfile() {
        if (ClientOperations.busy.get()) return
        if (FamilyVpnService.running) { toast(R.string.import_running); return }
        startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE); type = "application/json"
            putExtra(Intent.EXTRA_MIME_TYPES, arrayOf("application/json", "text/plain", "*/*"))
        }, importRequest)
    }
    private fun validateAndConnect() {
        if (ClientOperations.busy.get() || FamilyVpnService.running) return
        if (!hasProfile()) { toast(R.string.no_profile); return }
        if (!ClientOperations.busy.compareAndSet(false, true)) return
        PocState.set(this, "VALIDATING")
        Thread {
            val result = runCatching { SingBoxRuntime.ensureSetup(this); Libbox.checkConfig(RuntimeConfig.build(this)) }
            ClientOperations.busy.set(false)
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                if (result.isFailure) {
                    PocState.set(this, "FAILED", if (result.exceptionOrNull() is BypassConflict) "BYPASS_CONFLICT" else "CONFIG_REJECTED")
                } else {
                    val permission = VpnService.prepare(this)
                    if (permission != null) startActivityForResult(permission, vpnRequest) else connect()
                }
                refresh()
            }
        }.start()
    }
    private fun connect() {
        PocState.set(this, "CONNECTING")
        val intent = Intent(this, FamilyVpnService::class.java).setAction(FamilyVpnService.ACTION_CONNECT)
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(intent) else startService(intent)
    }
    private fun disconnect() { startService(Intent(this, FamilyVpnService::class.java).setAction(FamilyVpnService.ACTION_DISCONNECT)) }
    private fun profileFile() = File(filesDir, "reference-profile.json")
    private fun hasProfile() = runCatching { SecureClientStore.load(this) != null }.getOrDefault(false) || profileFile().isFile

    private fun operation(message: Int, successNotice: Int? = null, action: () -> Int) {
        if (!ClientOperations.busy.compareAndSet(false, true)) return
        ClientOperations.message = message; ClientOperations.error = null; refresh()
        Thread {
            val result = runCatching(action)
            ClientOperations.message = result.getOrDefault(R.string.operation_failed)
            ClientOperations.error = result.exceptionOrNull()
            ClientOperations.busy.set(false)
            sendBroadcast(Intent(PocState.ACTION_CHANGED).setPackage(packageName))
            if (result.isSuccess && successNotice != null) runOnUiThread {
                android.widget.Toast.makeText(applicationContext,
                    AppPreferences.localized(applicationContext).getString(successNotice),
                    android.widget.Toast.LENGTH_LONG).show()
            }
        }.start()
    }
    private fun signIn() {
        val address = portalUrlField.text.toString().trim()
        val username = usernameField.text.toString().trim()
        val password = passwordField.text.toString(); passwordField.text.clear()
        operation(R.string.signing_in, successNotice = R.string.profile_added) {
            val api = ClientApi(address)
            val tokens = api.login(username, password)
            val access = tokens.getString("access_token")
            val profile = try { api.profile(access) } catch (error: Exception) { runCatching { api.logout(access) }; throw error }
            SingBoxRuntime.ensureSetup(this); Libbox.checkConfig(ClientProfile.buildConfig(profile))
            SecureClientStore.save(this, SavedClient(api.baseUrl, tokens.getString("refresh_token"), profile))
            R.string.profile_ready
        }
    }
    private fun syncSavedProfile() {
        if (!runCatching { SecureClientStore.load(this) != null }.getOrDefault(false)) return
        operation(R.string.syncing) {
            val saved = SecureClientStore.load(this) ?: return@operation R.string.no_profile
            try {
                val api = ClientApi(saved.portalUrl)
                val tokens = api.refresh(saved.refreshToken)
                val rotated = saved.copy(refreshToken = tokens.getString("refresh_token"))
                SecureClientStore.save(this, rotated)
                val profile = api.profile(tokens.getString("access_token"))
                SingBoxRuntime.ensureSetup(this); Libbox.checkConfig(ClientProfile.buildConfig(profile))
                SecureClientStore.save(this, rotated.copy(profile = profile))
                R.string.profile_updated
            } catch (error: ClientApiException) {
                if (error.status == 401 || error.code == "VPN_ACCESS_DENIED") {
                    SecureClientStore.clear(this); disconnect(); R.string.sign_in_again
                } else R.string.saved_profile
            } catch (_: Exception) { R.string.saved_profile }
        }
    }
    private fun signOut() = operation(R.string.signing_out) {
        val saved = SecureClientStore.load(this)
        if (saved != null) {
            val api = ClientApi(saved.portalUrl)
            try {
                val tokens = api.refresh(saved.refreshToken)
                SecureClientStore.save(this, saved.copy(refreshToken = tokens.getString("refresh_token")))
                api.logout(tokens.getString("access_token"))
            } catch (error: ClientApiException) { if (error.status != 401) throw error }
            SecureClientStore.clear(this)
        }
        disconnect(); R.string.signed_out
    }
    private fun safeError(error: Throwable?): String = ui.s(when (error) {
        is BypassConflict -> R.string.bypass_conflict
        is ClientApiException -> when (error.code) {
            "INVALID_CREDENTIALS" -> R.string.credentials_error
            "AUTH_REQUIRED", "VPN_ACCESS_DENIED" -> R.string.sign_in_again
            "RATE_LIMITED" -> R.string.rate_limit
            else -> R.string.network_error
        }
        is IllegalArgumentException -> R.string.url_error
        else -> R.string.network_error
    })
    private fun refresh() {
        if (!::ui.isInitialized) return
        val saved = runCatching { SecureClientStore.load(this) }.getOrNull()
        profileView.text = if (saved != null) ui.s(R.string.my_profile, saved.profile.optString("display_name"))
            else if (profileFile().isFile) ui.s(R.string.local_profile) else ui.s(R.string.no_profile)
        loginStateView.text = if (ClientOperations.message == R.string.operation_failed) ui.s(R.string.operation_failed, safeError(ClientOperations.error))
            else if (saved == null && !ClientOperations.busy.get() && ClientOperations.message == R.string.profile_ready) "" else ui.s(ClientOperations.message)
        val (state, error) = PocState.get(this)
        stateView.text = if (FamilyVpnService.running) ui.s(if (PingMonitor.state == "READY") R.string.connected else R.string.core_running)
            else ui.s(when (state) { "CONNECTING" -> R.string.connecting; "VALIDATING" -> R.string.validating; "STOPPING" -> R.string.stopping; "FAILED" -> R.string.vpn_failed; else -> R.string.disconnected })
        if (error == "BYPASS_CONFLICT") stateView.text = ui.s(R.string.bypass_conflict)
        stateView.setTextColor(if (FamilyVpnService.running && PingMonitor.state == "READY") ui.success else if (state == "FAILED") ui.error else ui.secondary)
        pingButton.text = when (PingMonitor.state) { "READY" -> ui.s(R.string.ping_ms, PingMonitor.milliseconds ?: 0L); "BUSY" -> ui.s(R.string.ping_busy); "UNAVAILABLE" -> ui.s(R.string.ping_unavailable); else -> "—" }
        pingButton.isEnabled = FamilyVpnService.running && PingMonitor.state != "BUSY"
        val busy = ClientOperations.busy.get()
        signInButton.isEnabled = !busy; signOutButton.isEnabled = !busy
        connectButton.isEnabled = !busy && !FamilyVpnService.running && state !in setOf("VALIDATING", "CONNECTING", "STOPPING")
    }
    private fun toast(id: Int) = android.widget.Toast.makeText(this, ui.s(id), android.widget.Toast.LENGTH_LONG).show()
}

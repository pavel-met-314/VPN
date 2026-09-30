package com.familyvpn.poc

import android.app.Activity
import android.annotation.SuppressLint
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.view.WindowManager
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import io.nekohasekai.libbox.Libbox
import java.io.File

class MainActivity : Activity() {
    private lateinit var stateView: TextView
    private lateinit var profileView: TextView
    private lateinit var portalUrlField: EditText
    private lateinit var usernameField: EditText
    private lateinit var passwordField: EditText
    private lateinit var loginStateView: TextView
    private val importRequest = 1001
    private val vpnRequest = 1002
    private var validating = false

    private val stateReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) = refresh()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        actionBar?.hide()
        if (Build.VERSION.SDK_INT >= 30) {
            window.insetsController?.setSystemBarsAppearance(
                WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS,
                WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS,
            )
        } else {
            @Suppress("DEPRECATION")
            window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR
        }
        window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE)
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.TOP
            setPadding(32, 32, 32, 32)
        }
        profileView = TextView(this).apply { textSize = 16f }
        stateView = TextView(this).apply { textSize = 20f }
        layout.addView(TextView(this).apply {
            text = "Family VPN"
            textSize = 24f
        }, row())
        portalUrlField = EditText(this).apply {
            hint = "https://portal.example"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setSingleLine(true)
            setText(runCatching { SecureClientStore.load(this@MainActivity)?.portalUrl }.getOrNull())
        }
        usernameField = EditText(this).apply {
            hint = "Portal username"
            setSingleLine(true)
        }
        passwordField = EditText(this).apply {
            hint = "Portal password"
            setSingleLine(true)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        loginStateView = TextView(this).apply { textSize = 16f }
        layout.addView(TextView(this).apply { text = "Portal HTTPS address" }, row())
        layout.addView(portalUrlField, row())
        layout.addView(TextView(this).apply { text = "Portal username" }, row())
        layout.addView(usernameField, row())
        layout.addView(TextView(this).apply { text = "Portal password" }, row())
        layout.addView(passwordField, row())
        layout.addView(Button(this).apply {
            text = "Sign in and load my profile"
            setOnClickListener { signIn() }
        }, row())
        layout.addView(Button(this).apply {
            text = "Sign out"
            setOnClickListener { signOut() }
        }, row())
        layout.addView(loginStateView, row())
        layout.addView(profileView, row())
        layout.addView(stateView, row())
        layout.addView(Button(this).apply {
            text = getString(R.string.import_json)
            setOnClickListener {
                startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE)
                    type = "application/json"
                    putExtra(Intent.EXTRA_MIME_TYPES, arrayOf("application/json", "text/plain", "*/*"))
                }, importRequest)
            }
        }, row())
        layout.addView(Button(this).apply {
            text = getString(R.string.connect)
            setOnClickListener {
                if (validating) return@setOnClickListener
                if (!hasProfile()) {
                    PocState.set(this@MainActivity, "FAILED", "Sign in or import a local JSON first")
                    return@setOnClickListener
                }
                validating = true
                PocState.set(this@MainActivity, "VALIDATING")
                Thread {
                    val valid = runCatching {
                        SingBoxRuntime.ensureSetup(this@MainActivity)
                        val saved = SecureClientStore.load(this@MainActivity)
                        val config = if (saved != null) ClientProfile.buildConfig(saved.profile)
                            else ReferenceConfig.prepare(profileFile().readText())
                        Libbox.checkConfig(config)
                    }.isSuccess
                    runOnUiThread {
                        validating = false
                        if (!valid) {
                            PocState.set(this@MainActivity, "FAILED", "Config rejected by sing-box")
                        } else {
                            val permission = VpnService.prepare(this@MainActivity)
                            if (permission != null) startActivityForResult(permission, vpnRequest)
                            else connect()
                        }
                    }
                }.start()
            }
        }, row())
        layout.addView(Button(this).apply {
            text = getString(R.string.disconnect)
            setOnClickListener {
                startService(Intent(this@MainActivity, FamilyVpnService::class.java)
                    .setAction(FamilyVpnService.ACTION_DISCONNECT))
            }
        }, row())
        setContentView(ScrollView(this).apply {
            addView(layout)
            setOnApplyWindowInsetsListener { view, insets ->
                val top: Int
                val bottom: Int
                if (Build.VERSION.SDK_INT >= 30) {
                    val bars = insets.getInsets(WindowInsets.Type.systemBars())
                    top = bars.top
                    bottom = bars.bottom
                } else {
                    @Suppress("DEPRECATION")
                    top = insets.systemWindowInsetTop
                    @Suppress("DEPRECATION")
                    bottom = insets.systemWindowInsetBottom
                }
                view.setPadding(0, top, 0, bottom)
                insets
            }
        })
        refresh()
        syncSavedProfile()
    }

    @SuppressLint("UnspecifiedRegisterReceiverFlag")
    override fun onStart() {
        super.onStart()
        val filter = IntentFilter(PocState.ACTION_CHANGED)
        if (Build.VERSION.SDK_INT >= 33) registerReceiver(stateReceiver, filter, RECEIVER_NOT_EXPORTED)
        else @Suppress("DEPRECATION") registerReceiver(stateReceiver, filter)
        refresh()
    }

    override fun onStop() {
        unregisterReceiver(stateReceiver)
        super.onStop()
    }

    @Deprecated("Android's VPN permission and document picker still use activity results")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == vpnRequest && resultCode == RESULT_OK) connect()
        if (requestCode == importRequest && resultCode == RESULT_OK) {
            val uri = data?.data ?: return
            try {
                val text = contentResolver.openInputStream(uri).use { input ->
                    requireNotNull(input) { "Cannot open selected file" }
                    val bytes = input.readBytes()
                    require(bytes.size in 2..1_048_576) { "JSON must be 1 MB or less" }
                    bytes.toString(Charsets.UTF_8)
                }
                require(ReferenceConfig.kind(text) != ReferenceConfig.Kind.INVALID) {
                    "A full config or a single VLESS outbound is required"
                }
                PocState.set(this, "VALIDATING")
                Thread {
                    val validated = runCatching {
                        SingBoxRuntime.ensureSetup(this)
                        Libbox.checkConfig(ReferenceConfig.prepare(text))
                        profileFile().writeText(text)
                    }.isSuccess
                    runOnUiThread {
                        if (validated) PocState.set(this, "DISCONNECTED")
                        else PocState.set(this, "FAILED", "Config rejected by sing-box")
                        refresh()
                    }
                }.start()
            } catch (_: IllegalArgumentException) {
                PocState.set(this, "FAILED", "Full VPN JSON or one VLESS outbound required")
            } catch (_: Exception) {
                PocState.set(this, "FAILED", "Could not import JSON")
            }
            refresh()
        }
    }

    private fun connect() {
        PocState.set(this, "CONNECTING")
        val intent = Intent(this, FamilyVpnService::class.java)
            .setAction(FamilyVpnService.ACTION_CONNECT)
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(intent) else startService(intent)
    }

    private fun profileFile(): File = File(filesDir, "reference-profile.json")

    private fun hasProfile(): Boolean =
        runCatching { SecureClientStore.load(this) != null }.getOrDefault(false) ||
            profileFile().isFile

    private fun signIn() {
        if (validating) return
        val portalUrl = portalUrlField.text.toString().trim()
        val username = usernameField.text.toString().trim()
        val password = passwordField.text.toString()
        passwordField.text.clear()
        validating = true
        loginStateView.text = "Signing in..."
        Thread {
            val result = runCatching {
                val api = ClientApi(portalUrl)
                val tokens = api.login(username, password)
                val accessToken = tokens.getString("access_token")
                val profile = try {
                    api.profile(accessToken)
                } catch (error: Exception) {
                    runCatching { api.logout(accessToken) }
                    throw error
                }
                SingBoxRuntime.ensureSetup(this)
                Libbox.checkConfig(ClientProfile.buildConfig(profile))
                SecureClientStore.save(
                    this,
                    SavedClient(api.baseUrl, tokens.getString("refresh_token"), profile),
                )
            }
            runOnUiThread {
                validating = false
                loginStateView.text = if (result.isSuccess) "My profile is ready"
                    else "Sign in failed: ${safeError(result.exceptionOrNull())}"
                refresh()
            }
        }.start()
    }

    private fun syncSavedProfile() {
        val saved = runCatching { SecureClientStore.load(this) }.getOrNull() ?: return
        Thread {
            val result = runCatching {
                val api = ClientApi(saved.portalUrl)
                val tokens = api.refresh(saved.refreshToken)
                val rotated = saved.copy(refreshToken = tokens.getString("refresh_token"))
                SecureClientStore.save(this, rotated)
                val profile = api.profile(tokens.getString("access_token"))
                SingBoxRuntime.ensureSetup(this)
                Libbox.checkConfig(ClientProfile.buildConfig(profile))
                SecureClientStore.save(this, rotated.copy(profile = profile))
            }
            val error = result.exceptionOrNull()
            val denied = error is ClientApiException &&
                (error.status == 401 || error.code == "VPN_ACCESS_DENIED")
            if (denied) {
                SecureClientStore.clear(this)
                startService(
                    Intent(this, FamilyVpnService::class.java)
                        .setAction(FamilyVpnService.ACTION_DISCONNECT),
                )
            }
            runOnUiThread {
                loginStateView.text = when {
                    result.isSuccess -> "My profile is up to date"
                    denied -> "Sign in again: ${safeError(error)}"
                    else -> "Using saved profile; ${safeError(error)}"
                }
                refresh()
            }
        }.start()
    }

    private fun signOut() {
        if (validating) return
        validating = true
        loginStateView.text = "Signing out..."
        Thread {
            val result = runCatching {
                val saved = SecureClientStore.load(this)
                if (saved != null) {
                    val api = ClientApi(saved.portalUrl)
                    try {
                        val tokens = api.refresh(saved.refreshToken)
                        SecureClientStore.save(
                            this, saved.copy(refreshToken = tokens.getString("refresh_token")),
                        )
                        api.logout(tokens.getString("access_token"))
                    } catch (error: ClientApiException) {
                        if (error.status != 401) throw error
                    }
                    SecureClientStore.clear(this)
                }
                startService(
                    Intent(this, FamilyVpnService::class.java)
                        .setAction(FamilyVpnService.ACTION_DISCONNECT),
                )
            }
            runOnUiThread {
                validating = false
                loginStateView.text = if (result.isSuccess) "Signed out"
                    else "Sign out failed: ${safeError(result.exceptionOrNull())}"
                refresh()
            }
        }.start()
    }

    private fun safeError(error: Throwable?): String = when (error) {
        is ClientApiException -> error.code
        is IllegalArgumentException -> "Check portal URL or profile"
        else -> "Network or storage unavailable"
    }

    private fun refresh() {
        val saved = runCatching { SecureClientStore.load(this) }.getOrNull()
        profileView.text = if (saved != null) {
            "My profile: ${saved.profile.optString("display_name", "ready")}"
        } else if (profileFile().isFile) {
            when (runCatching { ReferenceConfig.kind(profileFile().readText()) }.getOrNull()) {
                ReferenceConfig.Kind.COMPLETE -> "Full local JSON imported"
                ReferenceConfig.Kind.HIDDIFY_OUTBOUND -> "VLESS outbound: experimental wrapper"
                else -> "Invalid local JSON"
            }
        } else "No local JSON"
        val (state, error) = PocState.get(this)
        stateView.text = if (error.isBlank()) state else "$state: $error"
    }

    private fun row() = LinearLayout.LayoutParams(
        ViewGroup.LayoutParams.MATCH_PARENT,
        ViewGroup.LayoutParams.WRAP_CONTENT,
    ).apply { bottomMargin = 18 }
}

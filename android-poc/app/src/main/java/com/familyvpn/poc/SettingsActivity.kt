package com.familyvpn.poc

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.annotation.SuppressLint
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.graphics.drawable.Drawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.Editable
import android.text.TextWatcher
import android.text.InputType
import android.view.View
import android.view.ContextThemeWrapper
import android.view.ViewGroup
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Switch
import android.widget.TextView
import io.nekohasekai.libbox.Libbox
import java.util.Locale

private data class InstalledApp(val packageName: String, val label: String, val system: Boolean, val uid: Int, val icon: Drawable)

class SettingsActivity : Activity() {
    private lateinit var ui: UiKit
    private lateinit var updateStatus: TextView
    private lateinit var installButton: Button
    private lateinit var cancelButton: Button
    private lateinit var checkButton: Button
    private lateinit var bypassStatus: TextView
    private lateinit var appsList: LinearLayout
    private lateinit var applyButton: Button
    private lateinit var scroll: ScrollView
    private lateinit var updateCard: LinearLayout
    private val selected = mutableSetOf<String>()
    private var apps = emptyList<InstalledApp>()
    private var appsLoaded = false
    private var showSystem = false
    private var search = ""
    private var applying = false
    private var resumed = false
    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            refreshUpdates()
            if (resumed) continueInstall()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        selected.addAll(savedInstanceState?.getStringArrayList("selected") ?: AppPreferences.exclusions(this))
        showSystem = savedInstanceState?.getBoolean("system") ?: false
        search = savedInstanceState?.getString("search") ?: ""
        render()
        loadApps()
        if (intent.getBooleanExtra("open_update", false)) scroll.post { scroll.smoothScrollTo(0, updateCard.top) }
    }
    private fun render() {
        val oldScroll = if (::scroll.isInitialized) scroll.scrollY else 0
        ui = UiKit(this)
        val header = ui.line()
        header.addView(ui.iconButton(R.drawable.ic_back, ui.s(R.string.back)) { finish() }.apply {
            background = ui.shape(fill = android.graphics.Color.TRANSPARENT, stroke = android.graphics.Color.TRANSPARENT)
        },
            LinearLayout.LayoutParams(ui.dp(52), ViewGroup.LayoutParams.WRAP_CONTENT).apply { rightMargin = ui.dp(16) })
        header.addView(ui.text(ui.s(R.string.settings), 30f, true), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        val root = ui.root(header)
        val layout = root.first; scroll = root.second
        fun heading(card: LinearLayout, id: Int, help: Int? = null) {
            card.addView(ui.text(ui.s(id), 24f, true), ui.params(8))
            help?.let { card.addView(ui.text(ui.s(it), 15f).apply { setTextColor(ui.secondary) }, ui.params(14)) }
        }
        val language = ui.card(layout)
        heading(language, R.string.language, R.string.language_help)
        choices(language, listOf("ru" to R.string.russian, "en" to R.string.english), AppPreferences.language(this)) {
            AppPreferences.setLanguage(this, it); render()
            if (FamilyVpnService.running) startService(Intent(this, FamilyVpnService::class.java).setAction(FamilyVpnService.ACTION_NOTIFICATION))
        }
        val theme = ui.card(layout)
        heading(theme, R.string.theme)
        choices(theme, listOf("system" to R.string.system_theme, "light" to R.string.light_theme, "dark" to R.string.dark_theme), AppPreferences.theme(this)) {
            AppPreferences.setTheme(this, it); render()
        }
        updateCard = ui.card(layout)
        heading(updateCard, R.string.update)
        updateCard.addView(ui.text(ui.s(R.string.current_version, BuildConfig.VERSION_NAME), 16f), ui.params(6))
        if (BuildConfig.DEBUG) updateCard.addView(ui.text(ui.s(R.string.test_version), 12f).apply { setTextColor(ui.secondary) }, ui.params(6))
        updateCard.addView(ui.text(ui.s(R.string.stable_only), 13f).apply { setTextColor(ui.secondary) }, ui.params())
        checkButton = ui.button(ui.s(R.string.check_update), icon = R.drawable.ic_refresh) {
            Thread { UpdateRepository.check(applicationContext) }.start()
        }
        updateCard.addView(checkButton, ui.params())
        updateStatus = ui.text("").apply { setTextColor(ui.secondary) }
        updateCard.addView(updateStatus, ui.params())
        installButton = ui.button("", primary = true, icon = R.drawable.ic_download) {
            when (UpdateInstaller.state) {
                "READY", "PERMISSION" -> UpdateInstaller.beginInstall(this)
                "CONFIRM" -> UpdateInstaller.confirm(this)
                else -> UpdateRepository.cached(this)?.let { UpdateInstaller.download(this, it) }
            }
        }
        updateCard.addView(installButton, ui.params())
        cancelButton = ui.button(ui.s(R.string.cancel)) { UpdateInstaller.cancel() }
        updateCard.addView(cancelButton, ui.params())
        updateCard.addView(ui.button(ui.s(R.string.notifications)) { allowNotifications() }, ui.params())
        updateCard.addView(ui.text(ui.s(R.string.notifications_help), 12f).apply { setTextColor(ui.secondary) }, ui.params())
        val bypass = ui.card(layout)
        heading(bypass, R.string.app_traversal, R.string.bypass_help)
        val searchField = ui.input(ui.s(R.string.search_apps), InputType.TYPE_CLASS_TEXT, R.drawable.ic_user)
        searchField.setText(search)
        searchField.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) = Unit
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) { search = s.toString(); renderApps() }
            override fun afterTextChanged(s: Editable?) = Unit
        })
        bypass.addView(searchField, ui.params())
        @Suppress("DEPRECATION")
        val systemToggle = Switch(ui.context).apply {
            text = ui.s(R.string.show_system); isChecked = showSystem; minHeight = ui.dp(48); setTextColor(ui.foreground)
            setOnCheckedChangeListener { _, checked -> showSystem = checked; renderApps() }
        }
        bypass.addView(systemToggle, ui.params())
        appsList = ui.column()
        bypass.addView(appsList, ui.params())
        bypassStatus = ui.text(if (selected != AppPreferences.exclusions(this)) ui.s(R.string.bypass_pending)
            else ui.s(R.string.bypass_saved, selected.size), 13f).apply { setTextColor(ui.secondary) }
        bypass.addView(bypassStatus, ui.params())
        applyButton = ui.button(ui.s(R.string.apply), primary = true) {
            if (applying) return@button
            if (FamilyVpnService.running) AlertDialog.Builder(ContextThemeWrapper(this@SettingsActivity,
                if (ui.dark) android.R.style.Theme_Material_NoActionBar else android.R.style.Theme_Material_Light_NoActionBar))
                .setTitle(ui.s(R.string.reconnect_title)).setMessage(ui.s(R.string.reconnect_help))
                .setNegativeButton(ui.s(R.string.cancel), null).setPositiveButton(ui.s(R.string.apply)) { _, _ -> applyBypass() }.show()
            else applyBypass()
        }
        applyButton.isEnabled = !applying
        bypass.addView(applyButton, ui.params())
        bypass.addView(ui.text(ui.s(R.string.shared_uid), 12f).apply { setTextColor(ui.secondary) }, ui.params())
        renderApps(); refreshUpdates()
        scroll.post { scroll.scrollTo(0, oldScroll) }
    }

    private fun choices(parent: LinearLayout, values: List<Pair<String, Int>>, current: String, action: (String) -> Unit) {
        // На узком экране и с увеличенным шрифтом кнопки не обрезаются.
        val horizontal = values.size == 2 && resources.configuration.fontScale <= 1.2f
        val row = if (horizontal) ui.line() else ui.column()
        for ((value, label) in values) {
            val button = ui.button(ui.s(label), primary = value == current) { action(value) }
            button.isSelected = value == current
            row.addView(button, if (horizontal) LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply {
                if (value != values.last().first) rightMargin = ui.dp(8)
            } else ui.params(8))
        }
        parent.addView(row, ui.params())
    }

    private fun loadApps() {
        Thread {
            val result = runCatching {
                @Suppress("DEPRECATION")
                packageManager.getInstalledApplications(0).filter {
                    it.packageName != packageName && it.uid != applicationInfo.uid &&
                        packageManager.checkPermission(Manifest.permission.INTERNET, it.packageName) == PackageManager.PERMISSION_GRANTED
                }.map {
                    InstalledApp(it.packageName, it.loadLabel(packageManager).toString(),
                        it.flags and ApplicationInfo.FLAG_SYSTEM != 0, it.uid, it.loadIcon(packageManager))
                }.sortedWith(compareBy(String.CASE_INSENSITIVE_ORDER) { it.label })
            }
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                apps = result.getOrDefault(emptyList())
                appsLoaded = true
                renderApps()
            }
        }.start()
    }
    private fun renderApps() {
        if (!::appsList.isInitialized) return
        appsList.removeAllViews()
        val query = search.trim().lowercase(Locale.ROOT)
        val shown = apps.filter { (showSystem || !it.system) && (query.isBlank() || it.label.lowercase(Locale.ROOT).contains(query) || it.packageName.lowercase(Locale.ROOT).contains(query)) }
        if (shown.isEmpty()) appsList.addView(ui.text(ui.s(if (!appsLoaded) R.string.loading_apps else R.string.no_apps), 14f), ui.params())
        for (app in shown) {
            val row = ui.line().apply { background = ui.shape(radius = 12); setPadding(ui.dp(10), ui.dp(6), ui.dp(6), ui.dp(6)) }
            row.addView(ImageView(ui.context).apply { setImageDrawable(app.icon); importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO },
                LinearLayout.LayoutParams(ui.dp(32), ui.dp(32)).apply { rightMargin = ui.dp(10) })
            val name = ui.column()
            name.addView(ui.text(app.label, 15f), ui.params(2))
            name.addView(ui.text(app.packageName + if (app.system) " · " + ui.s(R.string.system_app) else "", 11f).apply { setTextColor(ui.secondary) }, ui.params(0))
            row.addView(name, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            val checkBox = CheckBox(ui.context).apply {
                isChecked = app.packageName in selected; contentDescription = app.label; ui.tint(this)
                minWidth = ui.dp(48); minHeight = ui.dp(48)
                setOnCheckedChangeListener { _, checked ->
                    val group = apps.filter { it.uid == app.uid }.map { it.packageName }
                    if (checked) selected.addAll(group) else selected.removeAll(group.toSet())
                    bypassStatus.text = ui.s(R.string.bypass_pending)
                    appsList.post { renderApps() }
                }
            }
            row.addView(checkBox)
            row.setOnClickListener { checkBox.isChecked = !checkBox.isChecked }
            appsList.addView(row, ui.params(6))
        }
    }
    private fun applyBypass() {
        applying = true; applyButton.isEnabled = false
        val snapshot = selected.toSet()
        Thread {
            val result = runCatching {
                val hasProfile = SecureClientStore.load(this) != null || java.io.File(filesDir, "reference-profile.json").isFile
                if (hasProfile) { SingBoxRuntime.ensureSetup(this); Libbox.checkConfig(RuntimeConfig.build(this, snapshot)) }
                AppPreferences.setExclusions(this, snapshot)
                if (FamilyVpnService.running) startService(Intent(this, FamilyVpnService::class.java).setAction(FamilyVpnService.ACTION_RECONNECT))
            }
            runOnUiThread {
                applying = false
                if (isDestroyed) return@runOnUiThread
                applyButton.isEnabled = true
                bypassStatus.text = when {
                    result.isFailure -> ui.s(if (result.exceptionOrNull() is BypassConflict) R.string.bypass_conflict else R.string.bypass_failed)
                    selected != snapshot -> ui.s(R.string.bypass_pending)
                    else -> ui.s(R.string.bypass_saved, snapshot.size)
                }
            }
        }.start()
    }

    private fun refreshUpdates() {
        if (!::updateStatus.isInitialized) return
        val update = UpdateRepository.cached(this)
        val state = UpdateInstaller.state
        updateStatus.text = when {
            state == "DOWNLOADING" -> ui.s(R.string.downloading, UpdateInstaller.progress)
            state == "ERROR" -> ui.s(R.string.install_failed)
            state == "INSTALLING" -> ui.s(R.string.installing)
            state == "CONFIRM" || state == "PERMISSION" -> ui.s(R.string.confirm_install)
            state == "DONE" -> ui.s(R.string.installed)
            UpdateRepository.busy.get() -> ui.s(R.string.checking_update)
            UpdateRepository.failed -> ui.s(R.string.check_failed)
            update != null -> ui.s(R.string.update_available, update.metadata.versionName)
            UpdateRepository.lastCheck(this) == 0L -> ui.s(R.string.not_checked)
            else -> ui.s(R.string.no_update)
        }
        installButton.text = update?.let { ui.s(R.string.install_version, it.metadata.versionName) } ?: ""
        installButton.visibility = if (update != null && !BuildConfig.DEBUG) View.VISIBLE else View.GONE
        installButton.isEnabled = state !in setOf("DOWNLOADING", "INSTALLING") && !UpdateRepository.busy.get() && !UpdateRepository.failed
        checkButton.isEnabled = !UpdateRepository.busy.get() && state !in setOf("DOWNLOADING", "INSTALLING", "CONFIRM", "PERMISSION")
        cancelButton.visibility = if (state == "DOWNLOADING") View.VISIBLE else View.GONE
        if (BuildConfig.DEBUG && update != null) updateStatus.text = ui.s(R.string.debug_update)
    }
    private fun continueInstall() {
        when (UpdateInstaller.state) {
            "READY" -> if (UpdateInstaller.autoInstall) UpdateInstaller.beginInstall(this)
            "PERMISSION" -> if (Build.VERSION.SDK_INT < 26 || packageManager.canRequestPackageInstalls()) UpdateInstaller.beginInstall(this)
            "CONFIRM" -> UpdateInstaller.confirm(this)
        }
    }
    private fun allowNotifications() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 2404)
        } else {
            val intent = if (Build.VERSION.SDK_INT >= 26) Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, packageName)
                else Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName"))
            startActivity(intent)
        }
    }
    @SuppressLint("UnspecifiedRegisterReceiverFlag")
    override fun onStart() {
        super.onStart()
        if (Build.VERSION.SDK_INT >= 33) registerReceiver(receiver, IntentFilter(UpdateRepository.ACTION_CHANGED), RECEIVER_NOT_EXPORTED)
        else @Suppress("DEPRECATION") registerReceiver(receiver, IntentFilter(UpdateRepository.ACTION_CHANGED))
    }
    override fun onResume() { super.onResume(); resumed = true; refreshUpdates(); continueInstall(); UpdateScheduler.onOpen(this) }
    override fun onPause() { resumed = false; super.onPause() }
    override fun onStop() { unregisterReceiver(receiver); super.onStop() }
    override fun onConfigurationChanged(newConfig: Configuration) { super.onConfigurationChanged(newConfig); render() }
    override fun onSaveInstanceState(outState: Bundle) {
        outState.putStringArrayList("selected", ArrayList(selected)); outState.putBoolean("system", showSystem); outState.putString("search", search)
        super.onSaveInstanceState(outState)
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 2404) UpdateRepository.cached(this)?.let { UpdateNotifications.notify(this, it.metadata) }
    }
}

package com.familyvpn.poc

import android.app.Activity
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageInstaller
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import java.io.File
import java.io.InterruptedIOException
import java.net.HttpURLConnection
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicBoolean

internal object UpdateInstaller {
    @Volatile var state = "IDLE"
        private set
    @Volatile var progress = 0
        private set
    @Volatile var confirmation: Intent? = null
        private set
    private val cancelled = AtomicBoolean()
    @Volatile private var connection: HttpURLConnection? = null
    @Volatile private var candidate: AvailableUpdate? = null
    private var sessionId = -1
    @Volatile var autoInstall = false
        private set

    @Synchronized fun download(context: Context, update: AvailableUpdate) {
        if (state in setOf("DOWNLOADING", "INSTALLING", "CONFIRM")) return
        check(!BuildConfig.DEBUG)
        update.metadata.validate()
        ReleasePolicy.requireDownloadUrl(update.downloadUrl)
        state = "DOWNLOADING"
        autoInstall = true
        candidate = update
        progress = 0
        cancelled.set(false)
        val app = context.applicationContext
        publish(app)
        Thread {
            val destination = file(app, update)
            try {
                val next = ReleaseHttp.open(update.downloadUrl)
                connection = next
                try {
                    next.inputStream.use { input ->
                        destination.outputStream().use { output ->
                            val buffer = ByteArray(32768)
                            var total = 0L
                            var displayed = -1
                            while (true) {
                                if (cancelled.get()) throw InterruptedIOException()
                                val count = input.read(buffer)
                                if (count < 0) break
                                total += count
                                check(total <= update.size)
                                output.write(buffer, 0, count)
                                progress = (total * 100 / update.size).toInt()
                                if (displayed != progress) { displayed = progress; publish(app) }
                            }
                            check(total == update.size && !cancelled.get())
                        }
                    }
                } finally { next.disconnect(); connection = null }
                verify(app, destination, update.metadata)
                check(!cancelled.get())
                state = "READY"
            } catch (_: Exception) {
                destination.delete()
                state = if (cancelled.get()) "IDLE" else "ERROR"
            }
            publish(app)
        }.start()
    }

    fun cancel() { cancelled.set(true); connection?.disconnect() }

    fun beginInstall(activity: Activity) {
        if (state !in setOf("READY", "PERMISSION")) return
        autoInstall = false
        if (Build.VERSION.SDK_INT >= 26 && !activity.packageManager.canRequestPackageInstalls()) {
            state = "PERMISSION"
            activity.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${activity.packageName}")))
            return
        }
        val update = candidate ?: return
        val app = activity.applicationContext
        state = "INSTALLING"
        publish(app)
        Thread {
            try {
                val archive = file(app, update)
                verify(app, archive, update.metadata)
                val installer = app.packageManager.packageInstaller
                val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
                params.setAppPackageName(app.packageName)
                params.setSize(archive.length())
                if (Build.VERSION.SDK_INT >= 31) params.setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_REQUIRED)
                sessionId = installer.createSession(params)
                installer.openSession(sessionId).use { session ->
                    archive.inputStream().use { input ->
                        session.openWrite("base.apk", 0, archive.length()).use { output ->
                            input.copyTo(output); session.fsync(output)
                        }
                    }
                    val intent = Intent(app, InstallResultReceiver::class.java).putExtra("expected_session", sessionId)
                    val flags = PendingIntent.FLAG_UPDATE_CURRENT or if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0
                    session.commit(PendingIntent.getBroadcast(app, sessionId, intent, flags).intentSender)
                }
            } catch (_: Exception) {
                if (sessionId >= 0) runCatching { app.packageManager.packageInstaller.abandonSession(sessionId) }
                state = "ERROR"
                publish(app)
            }
        }.start()
    }

    fun confirm(activity: Activity) {
        val intent = confirmation ?: return
        confirmation = null
        state = "INSTALLING"
        runCatching { activity.startActivity(intent) }.onFailure { state = "ERROR" }
    }

    fun onResult(context: Context, intent: Intent) {
        val expected = intent.getIntExtra("expected_session", -1)
        val actual = intent.getIntExtra(PackageInstaller.EXTRA_SESSION_ID, -2)
        if (expected < 0 || expected != actual) return
        when (intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                @Suppress("DEPRECATION")
                confirmation = intent.getParcelableExtra(Intent.EXTRA_INTENT)
                state = if (confirmation == null) "ERROR" else "CONFIRM"
                InstallationNotifications.pending(context)
            }
            PackageInstaller.STATUS_SUCCESS -> {
                state = "DONE"
                candidate?.let { file(context, it).delete() }
            }
            PackageInstaller.STATUS_FAILURE_ABORTED -> {
                autoInstall = false
                state = if (candidate == null) "IDLE" else "READY"
            }
            else -> state = "ERROR"
        }
        publish(context)
    }

    private fun file(context: Context, update: AvailableUpdate): File =
        File(File(context.cacheDir, "updates").apply { mkdirs() }, update.metadata.apkAsset)

    private fun verify(context: Context, file: File, metadata: UpdateMetadata) {
        metadata.validate()
        check(metadata.applicationId == context.packageName && metadata.isNewer(BuildConfig.VERSION_CODE))
        check(metadata.minSdk <= Build.VERSION.SDK_INT && metadata.abi in Build.SUPPORTED_ABIS)
        ApkIntegrity.requireHash(file, metadata.sha256)
        val flags = if (Build.VERSION.SDK_INT >= 28) PackageManager.GET_SIGNING_CERTIFICATES else {
            @Suppress("DEPRECATION") PackageManager.GET_SIGNATURES
        }
        @Suppress("DEPRECATION")
        val archive = context.packageManager.getPackageArchiveInfo(file.absolutePath, flags) ?: error("INVALID_APK")
        @Suppress("DEPRECATION")
        val installed = context.packageManager.getPackageInfo(context.packageName, flags)
        check(archive.packageName == metadata.applicationId && archive.versionName == metadata.versionName)
        check(archive.applicationInfo?.minSdkVersion == metadata.minSdk)
        @Suppress("DEPRECATION")
        val code = if (Build.VERSION.SDK_INT >= 28) archive.longVersionCode else archive.versionCode.toLong()
        check(code == metadata.versionCode.toLong())
        fun signers(info: PackageInfo): Set<String> {
            @Suppress("DEPRECATION")
            val signatures = if (Build.VERSION.SDK_INT >= 28) info.signingInfo?.apkContentsSigners else info.signatures
            return signatures.orEmpty().map { signature ->
                MessageDigest.getInstance("SHA-256").digest(signature.toByteArray()).joinToString("") { "%02x".format(it) }
            }.toSet()
        }
        val current = signers(installed)
        check(current.isNotEmpty() && signers(archive) == current)
    }

    private fun publish(context: Context) = context.sendBroadcast(Intent(UpdateRepository.ACTION_CHANGED).setPackage(context.packageName))
}

class InstallResultReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) = UpdateInstaller.onResult(context, intent)
}

internal object InstallationNotifications {
    fun pending(context: Context) {
        // Если приложение свёрнуто, Android-запрос установки открывается только пользователем.
        val localized = AppPreferences.localized(context)
        val manager = context.getSystemService(android.app.NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 33 && context.checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        if (Build.VERSION.SDK_INT >= 26) manager.createNotificationChannel(android.app.NotificationChannel(
            "installation", localized.getString(R.string.update), android.app.NotificationManager.IMPORTANCE_DEFAULT,
        ))
        @Suppress("DEPRECATION")
        val builder = if (Build.VERSION.SDK_INT >= 26) android.app.Notification.Builder(context, "installation") else android.app.Notification.Builder(context)
        val pending = PendingIntent.getActivity(context, 2403, Intent(context, SettingsActivity::class.java)
            .putExtra("open_update", true), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        manager.notify(2403, builder.setSmallIcon(R.drawable.ic_download).setContentTitle(localized.getString(R.string.confirm_install))
            .setContentIntent(pending).setAutoCancel(true).build())
    }
}

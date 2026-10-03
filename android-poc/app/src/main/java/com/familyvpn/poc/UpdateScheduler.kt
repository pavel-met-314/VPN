package com.familyvpn.poc

import android.Manifest
import android.app.Application
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.job.JobInfo
import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.app.job.JobService
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import java.util.concurrent.Executors

class FamilyVpnApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        PingMonitor.initialize(this)
        if (!BuildConfig.DEBUG) UpdateScheduler.schedule(this)
    }
}

internal object UpdateScheduler {
    const val INTERVAL = 24 * 60 * 60 * 1000L
    private const val JOB_ID = 2401
    fun schedule(context: Context) {
        val scheduler = context.getSystemService(JobScheduler::class.java)
        if (scheduler.getPendingJob(JOB_ID) == null) {
            scheduler.schedule(JobInfo.Builder(JOB_ID, ComponentName(context, UpdateJobService::class.java))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY).setPeriodic(INTERVAL)
                .setPersisted(true).build())
        }
    }
    fun onOpen(context: Context) {
        if (BuildConfig.DEBUG) return
        val now = System.currentTimeMillis()
        val previous = UpdateRepository.lastCheck(context)
        if (previous == 0L || now < previous || now - previous >= INTERVAL) {
            Thread { UpdateRepository.check(context.applicationContext) }.start()
        } else UpdateRepository.cached(context)?.let { UpdateNotifications.notify(context, it.metadata) }
    }
}

class UpdateJobService : JobService() {
    private val worker = Executors.newSingleThreadExecutor()
    @Volatile private var active: JobParameters? = null
    override fun onStartJob(params: JobParameters): Boolean {
        active = params
        worker.execute {
            val success = UpdateRepository.check(applicationContext)
            if (active === params) { active = null; jobFinished(params, !success) }
        }
        return true
    }
    override fun onStopJob(params: JobParameters): Boolean { active = null; return true }
    override fun onDestroy() { worker.shutdown(); super.onDestroy() }
}

internal object UpdateNotifications {
    private const val CHANNEL = "app_updates"
    @Synchronized fun notify(context: Context, metadata: UpdateMetadata) {
        val app = context.applicationContext
        val prefs = app.getSharedPreferences("update_state", Context.MODE_PRIVATE)
        if (prefs.getInt("notified_code", 0) >= metadata.versionCode) return
        if (Build.VERSION.SDK_INT >= 33 && app.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        val manager = app.getSystemService(NotificationManager::class.java)
        if (!manager.areNotificationsEnabled()) return
        val localized = AppPreferences.localized(app)
        if (Build.VERSION.SDK_INT >= 26) {
            manager.createNotificationChannel(NotificationChannel(CHANNEL, localized.getString(R.string.update), NotificationManager.IMPORTANCE_DEFAULT))
            if (manager.getNotificationChannel(CHANNEL).importance == NotificationManager.IMPORTANCE_NONE) return
        }
        val intent = Intent(app, SettingsActivity::class.java).putExtra("open_update", true)
        val pending = PendingIntent.getActivity(app, 2402, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        @Suppress("DEPRECATION")
        val builder = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(app, CHANNEL) else Notification.Builder(app)
        manager.notify(2402, builder.setSmallIcon(R.drawable.ic_download)
            .setContentTitle(localized.getString(R.string.update_available, metadata.versionName))
            .setContentText(localized.getString(R.string.tap_update)).setContentIntent(pending).setAutoCancel(true).build())
        prefs.edit().putInt("notified_code", metadata.versionCode).apply()
    }
}

package com.familyvpn.poc

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.IpPrefix
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor
import android.os.SystemClock
import android.util.Log
import io.nekohasekai.libbox.CommandServer
import io.nekohasekai.libbox.CommandServerHandler
import io.nekohasekai.libbox.Libbox
import io.nekohasekai.libbox.OverrideOptions
import io.nekohasekai.libbox.SystemProxyStatus
import io.nekohasekai.libbox.TunOptions
import java.io.File
import java.net.InetAddress
import java.util.concurrent.Executors

class FamilyVpnService : VpnService(), CommandServerHandler {
    companion object {
        const val ACTION_CONNECT = "com.familyvpn.poc.CONNECT"
        const val ACTION_DISCONNECT = "com.familyvpn.poc.DISCONNECT"
        private const val CHANNEL = "family_vpn_poc"
        private const val NOTIFICATION_ID = 1
    }

    private val worker = Executors.newSingleThreadExecutor()
    private var server: CommandServer? = null
    private var tun: ParcelFileDescriptor? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_CONNECT -> {
                startInForeground()
                worker.execute { startVpn() }
            }
            ACTION_DISCONNECT -> worker.execute { stopVpn() }
        }
        return START_STICKY
    }

    override fun onRevoke() {
        worker.execute { stopVpn() }
    }

    override fun onDestroy() {
        worker.execute {
            cleanup()
            val state = PocState.get(this).first
            if (state != "FAILED" && state != "DISCONNECTED") {
                PocState.set(this, "DISCONNECTED")
            }
        }
        worker.shutdown()
        super.onDestroy()
    }

    private fun startVpn() {
        if (server != null) return
        val startedAt = SystemClock.elapsedRealtime()
        PocDiagnostics.record(this, "START_ENTER")
        try {
            check(prepare(this) == null) { "VPN permission missing" }
            val saved = SecureClientStore.load(this)
            val config = if (saved != null) ClientProfile.buildConfig(saved.profile)
                else ReferenceConfig.prepare(File(filesDir, "reference-profile.json").readText())
            SingBoxRuntime.ensureSetup(this)
            Libbox.checkConfig(config)
            PocDiagnostics.record(this, "CONFIG_VALID")
            val engine = Libbox.newCommandServer(this, AndroidPlatformBridge(this))
            server = engine
            engine.start()
            PocDiagnostics.record(this, "CORE_STARTING")
            engine.startOrReloadService(config, OverrideOptions())
            // Core startup is not proof of internet or DNS reachability.
            PocState.set(this, "CORE_RUNNING")
            PocDiagnostics.record(this, "CORE_START", durationMs = SystemClock.elapsedRealtime() - startedAt)
        } catch (e: Exception) {
            Log.w("FamilyVpnPoC", "Connect failed: ${e.javaClass.simpleName}")
            PocState.set(this, "FAILED", e.javaClass.simpleName)
            PocDiagnostics.record(this, "CORE_START", e.javaClass.simpleName, SystemClock.elapsedRealtime() - startedAt)
            stopVpn(false)
        }
    }

    private fun stopVpn(updateState: Boolean = true) {
        if (updateState) PocState.set(this, "STOPPING")
        cleanup()
        if (updateState) PocState.set(this, "DISCONNECTED")
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun cleanup() {
        runCatching { server?.closeService() }
        runCatching { server?.close() }
        server = null
        runCatching { tun?.close() }
        tun = null
    }

    internal fun openTun(options: TunOptions): Int {
        check(prepare(this) == null) { "VPN permission revoked" }
        val builder = Builder().setSession("Family VPN PoC").setMtu(options.mtu)
        if (Build.VERSION.SDK_INT >= 29) builder.setMetered(false)
        val v4 = options.inet4Address
        while (v4.hasNext()) v4.next().also { builder.addAddress(it.address(), it.prefix()) }
        val v6 = options.inet6Address
        while (v6.hasNext()) v6.next().also { builder.addAddress(it.address(), it.prefix()) }

        if (options.autoRoute) {
            val dnsMode = options.dnsMode
            if (dnsMode != null && dnsMode.value != Libbox.DNSModeDisabled) {
                val dns = options.dnsServerAddress
                while (dns.hasNext()) builder.addDnsServer(dns.next())
            }
            if (Build.VERSION.SDK_INT >= 33) {
                val route4 = options.inet4RouteAddress
                if (route4.hasNext()) while (route4.hasNext()) {
                    route4.next().also { builder.addRoute(IpPrefix(InetAddress.getByName(it.address()), it.prefix())) }
                } else if (options.inet4Address.hasNext()) builder.addRoute("0.0.0.0", 0)
                val route6 = options.inet6RouteAddress
                if (route6.hasNext()) while (route6.hasNext()) {
                    route6.next().also { builder.addRoute(IpPrefix(InetAddress.getByName(it.address()), it.prefix())) }
                } else if (options.inet6Address.hasNext()) builder.addRoute("::", 0)
                val excluded4 = options.inet4RouteExcludeAddress
                while (excluded4.hasNext()) excluded4.next().also {
                    builder.excludeRoute(IpPrefix(InetAddress.getByName(it.address()), it.prefix()))
                }
                val excluded6 = options.inet6RouteExcludeAddress
                while (excluded6.hasNext()) excluded6.next().also {
                    builder.excludeRoute(IpPrefix(InetAddress.getByName(it.address()), it.prefix()))
                }
            } else {
                val route4 = options.inet4RouteRange
                while (route4.hasNext()) route4.next().also { builder.addRoute(it.address(), it.prefix()) }
                val route6 = options.inet6RouteRange
                while (route6.hasNext()) route6.next().also { builder.addRoute(it.address(), it.prefix()) }
            }
            val included = options.includePackage
            while (included.hasNext()) builder.addAllowedApplication(included.next())
            val excluded = options.excludePackage
            while (excluded.hasNext()) builder.addDisallowedApplication(excluded.next())
        }
        val descriptor = builder.establish() ?: error("TUN establishment failed")
        tun = descriptor
        PocDiagnostics.record(this, "TUN_ESTABLISHED")
        return descriptor.fd
    }

    internal fun protectSocket(fd: Int) {
        check(protect(fd)) { "Cannot protect core socket" }
    }

    private fun startInForeground() {
        val manager = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) {
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL, "Family VPN PoC", NotificationManager.IMPORTANCE_LOW),
            )
        }
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val builder = if (Build.VERSION.SDK_INT >= 26) {
            Notification.Builder(this, CHANNEL)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
        }
        val notification = builder
            .setContentTitle("Family VPN PoC")
            .setContentText("VPN test is running")
            .setSmallIcon(android.R.drawable.stat_sys_download_done)
            .setContentIntent(open)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else startForeground(NOTIFICATION_ID, notification)
    }

    override fun serviceStop() { worker.execute { stopVpn() } }
    override fun serviceReload() = Unit
    override fun getSystemProxyStatus(): SystemProxyStatus = SystemProxyStatus()
    override fun setSystemProxyEnabled(enabled: Boolean) = Unit
    override fun triggerNativeCrash() = Unit
    override fun writeDebugMessage(message: String?) = Unit
    override fun connectSSHAgent(): Int = -1
}

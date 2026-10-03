package com.familyvpn.poc

import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger

internal object PingMonitor {
    const val ACTION_CHANGED = "com.familyvpn.poc.PING_CHANGED"
    @Volatile var state = "OFF"
        private set
    @Volatile var milliseconds: Long? = null
        private set
    private val generation = AtomicInteger()
    private val worker = Executors.newSingleThreadExecutor()
    private val handler = Handler(Looper.getMainLooper())
    @Volatile private var connection: HttpURLConnection? = null
    private var initialized = false

    @Synchronized fun initialize(context: Context) {
        if (initialized) return
        initialized = true
        val app = context.applicationContext
        val manager = app.getSystemService(ConnectivityManager::class.java)
        // Изменение любой физической сети сбрасывает устаревшее измерение.
        manager.registerNetworkCallback(NetworkRequest.Builder()
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .removeCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN).build(),
            object : ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: Network) = changed()
                override fun onLost(network: Network) = changed()
                private fun changed() {
                    invalidate(app)
                    handler.postDelayed({ if (FamilyVpnService.running) refresh(app) }, 500)
                }
            })
    }

    @Synchronized fun invalidate(context: Context) {
        generation.incrementAndGet()
        connection?.disconnect()
        connection = null
        milliseconds = null
        state = if (FamilyVpnService.running) "UNAVAILABLE" else "OFF"
        publish(context)
    }

    @Synchronized fun refresh(context: Context) {
        if (!FamilyVpnService.running) { invalidate(context); return }
        if (state == "BUSY") return
        val app = context.applicationContext
        val manager = app.getSystemService(ConnectivityManager::class.java)
        val vpn = manager.allNetworks.firstOrNull {
            manager.getNetworkCapabilities(it)?.hasTransport(NetworkCapabilities.TRANSPORT_VPN) == true
        }
        if (vpn == null) { invalidate(app); return }
        val ticket = generation.incrementAndGet()
        state = "BUSY"
        milliseconds = null
        publish(app)
        // Общий срок включает DNS, TLS и чтение ответа; просроченный результат игнорируется.
        handler.postDelayed({
            synchronized(this) {
                if (ticket == generation.get() && state == "BUSY") invalidate(app)
            }
        }, 10_000)
        worker.execute {
            val result = runCatching {
                val started = SystemClock.elapsedRealtime()
                val next = vpn.openConnection(URL("https://www.gstatic.com/generate_204")) as HttpURLConnection
                synchronized(this) {
                    if (ticket != generation.get()) { next.disconnect(); return@execute }
                    connection = next
                }
                try {
                    next.connectTimeout = 5_000
                    next.readTimeout = 5_000
                    next.useCaches = false
                    next.instanceFollowRedirects = false
                    next.setRequestProperty("Connection", "close")
                    check(next.responseCode == 204)
                    SystemClock.elapsedRealtime() - started
                } finally { next.disconnect() }
            }
            synchronized(this) {
                if (ticket != generation.get()) return@execute
                connection = null
                milliseconds = result.getOrNull()
                state = if (result.isSuccess) "READY" else "UNAVAILABLE"
                publish(app)
            }
        }
    }

    private fun publish(context: Context) = context.sendBroadcast(
        Intent(ACTION_CHANGED).setPackage(context.packageName),
    )
}

package com.familyvpn.poc

import android.content.Context
import io.nekohasekai.libbox.Libbox
import io.nekohasekai.libbox.SetupOptions
import java.io.File

internal object SingBoxRuntime {
    private var ready = false

    @Synchronized
    fun ensureSetup(context: Context) {
        if (ready) return
        val base = File(context.filesDir, "libbox").apply { mkdirs() }
        val work = File(base, "work").apply { mkdirs() }
        val temp = File(context.cacheDir, "libbox").apply { mkdirs() }
        Libbox.setup(SetupOptions().apply {
            basePath = base.absolutePath
            workingPath = work.absolutePath
            tempPath = temp.absolutePath
            appVersion = BuildConfig.VERSION_NAME
            appMarketingVersion = BuildConfig.VERSION_NAME
            crashReportSource = "android-poc"
            logMaxLines = 50L
        })
        ready = true
    }
}

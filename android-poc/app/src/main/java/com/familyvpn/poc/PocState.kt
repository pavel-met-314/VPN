package com.familyvpn.poc

import android.content.Context
import android.content.Intent

internal object PocState {
    const val ACTION_CHANGED = "com.familyvpn.poc.STATE_CHANGED"
    private const val PREFS = "poc_state"
    private const val KEY_STATE = "state"
    private const val KEY_ERROR = "error"

    fun set(context: Context, state: String, error: String = "") {
        PocDiagnostics.record(context, state, if (error.isBlank()) "OK" else error)
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_STATE, state)
            .putString(KEY_ERROR, error)
            .apply()
        context.sendBroadcast(Intent(ACTION_CHANGED).setPackage(context.packageName))
    }

    fun get(context: Context): Pair<String, String> {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        return Pair(
            prefs.getString(KEY_STATE, "DISCONNECTED") ?: "DISCONNECTED",
            prefs.getString(KEY_ERROR, "") ?: "",
        )
    }
}

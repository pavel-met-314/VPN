package com.familyvpn.poc

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import org.json.JSONObject
import java.io.File
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

internal data class SavedClient(
    val portalUrl: String,
    val refreshToken: String,
    val profile: JSONObject,
)

internal object SecureClientStore {
    private const val KEY_ALIAS = "family_vpn_client_v1"
    private const val FILE_NAME = "client-state.bin"

    fun load(context: Context): SavedClient? {
        val file = File(context.filesDir, FILE_NAME)
        if (!file.isFile) return null
        val bytes = AtomicFile(file).readFully()
        require(bytes.size > 13) { "Invalid saved profile" }
        val iv = bytes.copyOfRange(0, 12)
        val encrypted = bytes.copyOfRange(12, bytes.size)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, iv))
        val data = JSONObject(cipher.doFinal(encrypted).toString(Charsets.UTF_8))
        return SavedClient(
            portalUrl = data.getString("portal_url"),
            refreshToken = data.getString("refresh_token"),
            profile = data.getJSONObject("profile"),
        )
    }

    fun save(context: Context, value: SavedClient) {
        val data = JSONObject()
            .put("portal_url", value.portalUrl)
            .put("refresh_token", value.refreshToken)
            .put("profile", value.profile)
            .toString().toByteArray(Charsets.UTF_8)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val encrypted = cipher.iv + cipher.doFinal(data)
        val file = AtomicFile(File(context.filesDir, FILE_NAME))
        val stream = file.startWrite()
        try {
            stream.write(encrypted)
            file.finishWrite(stream)
        } catch (error: Exception) {
            file.failWrite(stream)
            throw error
        }
    }

    fun clear(context: Context) {
        AtomicFile(File(context.filesDir, FILE_NAME)).delete()
    }

    @Synchronized
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(
            KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        return generator.generateKey()
    }
}

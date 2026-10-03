package com.familyvpn.poc

import java.io.File
import java.security.MessageDigest

internal object ApkIntegrity {
    fun requireHash(file: File, expected: String) {
        require(expected.matches(Regex("[0-9a-f]{64}")))
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(32768)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                digest.update(buffer, 0, count)
            }
        }
        check(digest.digest().joinToString("") { "%02x".format(it) } == expected)
    }
}

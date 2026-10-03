package com.familyvpn.poc

import org.junit.Assert.*
import org.junit.Test

class ClientPolicyTest {
    private fun metadata(code: Int = 4, name: String = "0.1.0.3") = UpdateMetadata(
        1, "com.familyvpn.android", name, code, 24, "arm64-v8a", "FamilyVPN-$name-arm64.apk", "a".repeat(64),
    )
    private fun rejects(block: () -> Unit) {
        try { block(); fail("Must reject") } catch (_: IllegalArgumentException) { }
    }
    @Test fun onlyStableAndroidReleasesAreAccepted() {
        assertTrue(ReleasePolicy.accepts("android-v0.1.0.3", false, false))
        assertFalse(ReleasePolicy.accepts("android-v0.1.0.3", false, true))
        assertFalse(ReleasePolicy.accepts("android-v0.1.0.3", true, false))
        assertFalse(ReleasePolicy.accepts("server-v1.0.0.0", false, false))
        assertFalse(ReleasePolicy.accepts("android-v0.1.0-alpha.1", false, false))
    }
    @Test fun versionCodeControlsUpdatesAcrossNamingTransition() {
        metadata().validate()
        assertTrue(metadata().isNewer(2))
        assertFalse(metadata(3).isNewer(3))
        assertFalse(metadata(2, "9.9.9.9").isNewer(3))
    }
    @Test fun malformedAndUnrelatedMetadataCannotInstall() {
        rejects { metadata().copy(applicationId = "com.other.app").validate() }
        rejects { metadata().copy(sha256 = "a".repeat(63)).validate() }
        rejects { metadata().copy(apkAsset = "../app.apk").validate() }
        rejects { metadata().copy(abi = "x86_64").validate() }
        rejects { metadata().copy(minSdk = 21).validate() }
        rejects { metadata().copy(schemaVersion = 2).validate() }
        rejects { metadata().copy(versionCode = 0).validate() }
        rejects { metadata(name = "1.2.3").validate() }
    }
    @Test fun redirectsCannotDowngradeHttpsOrLeaveReleaseHosts() {
        ReleasePolicy.requireDownloadUrl("https://release-assets.githubusercontent.com/file?signature=example")
        rejects { ReleasePolicy.requireDownloadUrl("http://github.com/file") }
        rejects { ReleasePolicy.requireDownloadUrl("https://github.com.evil.example/file") }
        rejects { ReleasePolicy.requireDownloadUrl("https://user:password@github.com/file") }
        rejects { ReleasePolicy.requireDownloadUrl("https://github.com:8443/file") }
        ReleasePolicy.requireAssetUrl("https://github.com/pavel-met-314/VPN/releases/download/android-v0.1.0.3/update.json", "android-v0.1.0.3", "update.json")
        rejects { ReleasePolicy.requireAssetUrl("https://github.com/other/VPN/releases/download/android-v0.1.0.3/update.json", "android-v0.1.0.3", "update.json") }
    }
    @Test fun bypassPreservesImportedExclusionsAndRejectsAllowlistConflict() {
        assertEquals(setOf("old.app", "bank.app"), BypassPolicy.merge(emptySet(), setOf("old.app"), setOf("bank.app")))
        assertEquals(emptySet<String>(), BypassPolicy.merge(setOf("browser.app"), emptySet(), emptySet()))
        rejects { BypassPolicy.merge(setOf("browser.app"), emptySet(), setOf("bank.app")) }
        rejects { BypassPolicy.merge(setOf("browser.app"), setOf("old.app"), emptySet()) }
    }
    @Test fun alteredApkBytesFailTheChecksum() {
        val archive = java.io.File.createTempFile("family-apk-integrity-", ".apk")
        try {
            archive.writeText("abc")
            ApkIntegrity.requireHash(archive, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
            archive.appendText("changed")
            var rejected = false
            try { ApkIntegrity.requireHash(archive, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad") }
            catch (_: IllegalStateException) { rejected = true }
            assertTrue(rejected)
        } finally { archive.delete() }
    }
}

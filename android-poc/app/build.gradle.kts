plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.familyvpn.poc"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.familyvpn.android"
        minSdk = 24
        targetSdk = 35
        versionCode = 2
        versionName = "0.1.0-alpha.1"
    }

    buildTypes {
        getByName("debug") {
            applicationIdSuffix = ".debug"
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    packaging {
        jniLibs.useLegacyPackaging = true
    }
}

dependencies {
    implementation(files("libs/libbox.aar"))
}

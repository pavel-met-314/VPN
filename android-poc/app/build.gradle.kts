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
        versionCode = 6
        versionName = "0.1.0.5"
        testInstrumentationRunner = "com.familyvpn.poc.ClientSmokeInstrumentation"
    }

    buildTypes {
        getByName("debug") {
            applicationIdSuffix = ".debug"
        }
    }

    buildFeatures { buildConfig = true }
    bundle { language { enableSplit = false } }

    testOptions { unitTests.isReturnDefaultValues = true }

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
    testImplementation("junit:junit:4.13.2")
}

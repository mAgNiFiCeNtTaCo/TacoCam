import java.util.Properties

plugins {
    id("com.android.application")
}

// The app version is in ../version.properties so the PC build (pc/tools/build_portable.py) can read it too:
// the PC installs the APK on the phone when the phone's copy is older.
val versionProps = Properties().apply { rootProject.file("version.properties").inputStream().use { load(it) } }

// Release signing: a keystore that stays on the developer PC (never in git). TACOCAM_KEYSTORE names a
// .properties file with storeFile, storePassword, keyAlias, keyPassword. Without it the release APK is
// signed with the debug key (fine for tests and CI; an update then needs the same debug key).
val keystoreProps = System.getenv("TACOCAM_KEYSTORE")?.let { path ->
    val f = file(path)
    if (f.exists()) Properties().apply { f.inputStream().use { load(it) } } else null
}

android {
    namespace = "com.tacocam.app"
    compileSdk = 36
    buildToolsVersion = "36.0.0"

    defaultConfig {
        applicationId = "com.tacocam.app"
        minSdk = 30
        targetSdk = 36
        versionCode = versionProps.getProperty("versionCode").toInt()
        versionName = versionProps.getProperty("versionName")
    }

    signingConfigs {
        if (keystoreProps != null) {
            create("release") {
                storeFile = file(keystoreProps.getProperty("storeFile"))
                storePassword = keystoreProps.getProperty("storePassword")
                keyAlias = keystoreProps.getProperty("keyAlias")
                keyPassword = keystoreProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = if (keystoreProps != null) signingConfigs.getByName("release")
                            else signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    testOptions {
        unitTests.isReturnDefaultValues = true    // android.util.Log etc. do nothing in JVM tests
    }
}

dependencies {
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20250517")  // the real org.json on the JVM (Android's copy is only stubs there)
}

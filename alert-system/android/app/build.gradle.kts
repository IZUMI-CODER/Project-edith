plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.google.gms.google-services")
}

android {
    namespace = "com.projectedith.alert"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.projectedith.alert"
        minSdk = 26
        targetSdk = 35
        versionCode = 2
        versionName = "1.1"
        // The sender website, for the direct link (set in gradle.properties).
        buildConfigField("String", "SERVER_URL", "\"${project.findProperty("edith.serverUrl") ?: ""}\"")
    }

    buildFeatures {
        buildConfig = true
    }

    // CI keeps one key in its cache so updates install over the previous APK.
    // Locally (no ci-signing.keystore) the normal debug key is used.
    signingConfigs {
        getByName("debug") {
            val ciKey = rootProject.file("ci-signing.keystore")
            if (ciKey.exists()) {
                storeFile = ciKey
                storePassword = "edithalert"
                keyAlias = "edith"
                keyPassword = "edithalert"
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation(platform("com.google.firebase:firebase-bom:33.7.0"))
    implementation("com.google.firebase:firebase-messaging")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    testImplementation("junit:junit:4.13.2")
}

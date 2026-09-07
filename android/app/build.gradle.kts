import java.net.URI
import java.util.Base64
import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}

// Release signing is loaded from key.properties if present. Never commit a
// keystore or signing passwords to this repository.
val keystorePropertiesFile = rootProject.file("key.properties")
val keystoreProperties = Properties()
val hasSigningConfig = keystorePropertiesFile.exists()
val allowUnsignedRelease = providers.gradleProperty("allowUnsignedRelease")
    .map(String::toBoolean)
    .orElse(false)
    .get()
if (hasSigningConfig) {
    keystoreProperties.load(keystorePropertiesFile.inputStream())
}

val debugBackendBaseUrl = providers.gradleProperty("backendBaseUrl")
    .orElse("http://10.0.2.2:8000/api/v1")
    .get()
val debugSupabaseUrl = providers.gradleProperty("supabaseUrl")
    .orElse("https://your-project.supabase.co")
    .get()
val debugSupabaseAnonKey = providers.gradleProperty("supabaseAnonKey")
    .orElse("your-public-anon-key")
    .get()
val releaseBackendBaseUrl = providers.gradleProperty("releaseBackendBaseUrl").orElse("").get()
val releaseSupabaseUrl = providers.gradleProperty("releaseSupabaseUrl").orElse("").get()
val releaseSupabaseAnonKey = providers.gradleProperty("releaseSupabaseAnonKey").orElse("").get()

fun buildConfigString(value: String): String =
    "\"${value.replace("\\", "\\\\").replace("\"", "\\\"")}\""

fun requireRealHttpsEndpoint(propertyName: String, rawValue: String) {
    val value = rawValue.trim()
    val uri = try {
        URI(value)
    } catch (_: Exception) {
        throw GradleException("$propertyName must be a valid HTTPS URL.")
    }
    val host = uri.host?.lowercase().orEmpty()
    val isPlaceholder = host.isBlank() ||
        host == "localhost" ||
        host == "127.0.0.1" ||
        host == "10.0.2.2" ||
        host == "example.com" ||
        host.endsWith(".example.com") ||
        host.endsWith(".invalid") ||
        host.contains("your-project")
    if (uri.scheme?.lowercase() != "https" || uri.userInfo != null || isPlaceholder) {
        throw GradleException(
            "$propertyName must be a real HTTPS endpoint (no placeholders, localhost, credentials, or emulator hosts).",
        )
    }
}

fun requirePublicSupabaseKey(rawValue: String) {
    val value = rawValue.trim()
    val publishable = value.startsWith("sb_publishable_") && value.length >= 32
    val legacyAnon = if (value.startsWith("eyJ") && value.count { it == '.' } == 2) {
        try {
            val payload = String(Base64.getUrlDecoder().decode(value.split('.')[1]))
            Regex("\"role\"\\s*:\\s*\"anon\"").containsMatchIn(payload)
        } catch (_: Exception) {
            false
        }
    } else {
        false
    }
    if (value.startsWith("sb_secret_") || value.contains("service_role", ignoreCase = true)) {
        throw GradleException(
            "releaseSupabaseAnonKey must be a public anon/publishable key; never embed a secret or service-role key.",
        )
    }
    if (!publishable && !legacyAnon) {
        throw GradleException(
            "releaseSupabaseAnonKey must be a real Supabase public anon JWT or sb_publishable_ key.",
        )
    }
}

android {
    namespace = "com.clearpath.nexus"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.clearpath.nexus"
        minSdk = 26
        targetSdk = 35
        versionCode = 3
        versionName = "6.0.0"

        buildConfigField(
            "String",
            "BACKEND_BASE_URL",
            buildConfigString(debugBackendBaseUrl),
        )
        buildConfigField(
            "String",
            "API_BASE_URL",
            buildConfigString(debugBackendBaseUrl),
        )
        buildConfigField("String", "SUPABASE_URL", buildConfigString(debugSupabaseUrl))
        buildConfigField("String", "SUPABASE_ANON_KEY", buildConfigString(debugSupabaseAnonKey))

        // Build for physical devices (ARM) and emulators (x86 / x86_64).
        ndk {
            abiFilters += listOf("armeabi-v7a", "arm64-v8a", "x86", "x86_64")
        }
    }

    if (hasSigningConfig) {
        signingConfigs {
            create("release") {
                storeFile = file(keystoreProperties.getProperty("storeFile"))
                storePassword = keystoreProperties.getProperty("storePassword")
                keyAlias = keystoreProperties.getProperty("keyAlias")
                keyPassword = keystoreProperties.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        debug {
            isDebuggable = true
            isMinifyEnabled = false
            manifestPlaceholders["usesCleartextTraffic"] = true
            // Installs straight to a USB-connected phone via Android Studio Run.
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-device"
        }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            manifestPlaceholders["usesCleartextTraffic"] = false
            if (hasSigningConfig) {
                signingConfig = signingConfigs.getByName("release")
            }
            buildConfigField(
                "String",
                "BACKEND_BASE_URL",
                buildConfigString(releaseBackendBaseUrl),
            )
            buildConfigField(
                "String",
                "API_BASE_URL",
                buildConfigString(releaseBackendBaseUrl),
            )
            buildConfigField("String", "SUPABASE_URL", buildConfigString(releaseSupabaseUrl))
            buildConfigField("String", "SUPABASE_ANON_KEY", buildConfigString(releaseSupabaseAnonKey))
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

  // One APK that works on any physical device Android Studio detects.
    splits {
        abi {
            isEnable = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

// Keep ordinary Gradle configuration, release compilation, and debug
// verification usable without a release keystore. Any task graph that would
// emit a release APK or bundle still requires legitimate signing or an
// explicit CI-only opt-in to compile an unsigned artifact. The patterns also
// cover future product-flavor tasks such as packageDemoRelease.
val releaseArtifactTaskPatterns = listOf(
    Regex("^(assemble|bundle|package).*Release$"),
    Regex("^(sign|finalize|package).*ReleaseBundle$"),
)

gradle.taskGraph.whenReady {
    val releaseVariantTasks = allTasks.filter { task ->
        task.project == project && task.name.contains("Release")
    }
    if (releaseVariantTasks.isNotEmpty()) {
        requireRealHttpsEndpoint("releaseBackendBaseUrl", releaseBackendBaseUrl)
        requireRealHttpsEndpoint("releaseSupabaseUrl", releaseSupabaseUrl)
        requirePublicSupabaseKey(releaseSupabaseAnonKey)
    }

    val releaseArtifactTasks = allTasks.filter { task ->
        task.project == project && releaseArtifactTaskPatterns.any { it.matches(task.name) }
    }
    if (!hasSigningConfig && !allowUnsignedRelease && releaseArtifactTasks.isNotEmpty()) {
        throw GradleException(
            "Release signing is not configured. Provide android/key.properties " +
                "or pass -PallowUnsignedRelease=true for CI-only verification.",
        )
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.10.01")

    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")

    implementation("org.osmdroid:osmdroid-android:6.1.18")

    // Supabase is the single auth provider across Android and web.
    implementation(platform("io.github.jan-tennert.supabase:bom:3.0.3"))
    implementation("io.github.jan-tennert.supabase:auth-kt")
    implementation("io.github.jan-tennert.supabase:postgrest-kt")

    // Ktor Android Engine
    implementation("io.ktor:ktor-client-android:3.0.1")
    implementation("io.ktor:ktor-client-content-negotiation:3.0.1")
    implementation("io.ktor:ktor-serialization-kotlinx-json:3.0.1")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")

    testImplementation("junit:junit:4.13.2")

    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}

configurations.all {
    resolutionStrategy {
        force("androidx.browser:browser:1.8.0")
    }
}

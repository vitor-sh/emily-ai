import java.util.Properties
plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    id("com.google.gms.google-services")
}
val config=Properties().apply {rootProject.file("local.properties").takeIf{it.exists()}?.inputStream()?.use{load(it)}}
val signing=Properties().apply {rootProject.file(".signing/signing.properties").takeIf{it.exists()}?.inputStream()?.use{load(it)}}
val cloud=config.getProperty("MUSIC_CLOUD_URL") ?: ""
android {
    namespace="com.emily.music"
    compileSdk {version=release(36){minorApiLevel=1}}
    defaultConfig {
        applicationId="com.emily.music"
        minSdk=26;targetSdk=36
        versionCode=rootProject.file("version.properties").readText().trim().toInt();versionName="0.1.$versionCode"
        testInstrumentationRunner="androidx.test.runner.AndroidJUnitRunner"
        buildConfigField("String","MUSIC_CLOUD_URL","\"$cloud\"")
        ndk {abiFilters += listOf("arm64-v8a","armeabi-v7a")}
    }
    signingConfigs {
        create("music") {
            storeFile=rootProject.file(".signing/music.keystore")
            storePassword=signing.getProperty("storePassword")
            keyAlias=signing.getProperty("keyAlias")
            keyPassword=signing.getProperty("keyPassword")
        }
    }
    buildTypes {getByName("release") {signingConfig=signingConfigs.getByName("music");isDebuggable=false}}
    compileOptions {isCoreLibraryDesugaringEnabled=true;sourceCompatibility=JavaVersion.VERSION_11;targetCompatibility=JavaVersion.VERSION_11}
    buildFeatures {compose=true;buildConfig=true}
    packaging {resources.excludes += "/META-INF/{AL2.0,LGPL2.1}";jniLibs.useLegacyPackaging=true}
}
dependencies {
    implementation("androidx.car.app:app:1.7.0")
    implementation("androidx.media:media:1.7.0")
    implementation("androidx.car.app:app-projected:1.7.0")
    androidTestImplementation("androidx.car.app:app-testing:1.7.0") { exclude(group="org.robolectric") }
    coreLibraryDesugaring("com.android.tools:desugar_jdk_libs_nio:2.1.5")
    implementation("com.github.TeamNewPipe:NewPipeExtractor:v0.26.5")
    implementation(platform(libs.androidx.compose.bom))
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation(libs.androidx.compose.material3)
    implementation("androidx.compose.material:material-icons-extended")
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("androidx.media3:media3-exoplayer:1.9.2")
    implementation("androidx.media3:media3-session:1.9.2")
    implementation("androidx.media3:media3-datasource:1.9.2")
    implementation("androidx.webkit:webkit:1.14.0")
    implementation("androidx.work:work-runtime-ktx:2.10.2")
    implementation("androidx.documentfile:documentfile:1.0.1")
    implementation(platform("com.google.firebase:firebase-bom:33.8.0"))
    implementation("com.google.firebase:firebase-auth")
    implementation("androidx.credentials:credentials:1.3.0")
    implementation("androidx.credentials:credentials-play-services-auth:1.3.0")
    implementation("com.google.android.libraries.identity.googleid:googleid:1.1.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-play-services:1.7.3")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")
    implementation("io.github.junkfood02.youtubedl-android:library:0.18.1")
    implementation("io.github.junkfood02.youtubedl-android:ffmpeg:0.18.1")
    testImplementation(libs.junit)
    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    androidTestImplementation(libs.androidx.junit)
    debugImplementation(libs.androidx.compose.ui.test.manifest)
}

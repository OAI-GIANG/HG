plugins {
    id("com.android.application")
}

android {
    namespace = "org.hg.cim.broker"
    compileSdk = 37

    defaultConfig {
        applicationId = "org.hg.cim.broker"
        minSdk = 29
        targetSdk = 36
        versionCode = 1
        versionName = "1.0.0"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    testOptions {
        unitTests.isReturnDefaultValues = false
    }
}

dependencies {
    testImplementation("junit:junit:4.13.2")
}

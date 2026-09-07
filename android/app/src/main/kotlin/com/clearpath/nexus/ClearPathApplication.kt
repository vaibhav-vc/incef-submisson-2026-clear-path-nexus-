package com.clearpath.nexus

import android.app.Application
import org.osmdroid.config.Configuration

class ClearPathApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        Configuration.getInstance().userAgentValue = packageName
    }
}

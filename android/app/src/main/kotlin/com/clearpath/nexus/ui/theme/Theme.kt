package com.clearpath.nexus.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val NexusColorScheme = darkColorScheme(
    primary = AccentSafetyBlue,
    onPrimary = Color(0xFFFFFFFF),
    secondary = SolarRiskAmber,
    background = PrimaryCommandBlue,
    surface = PanelDark,
    onBackground = Color(0xFFFFFFFF),
    onSurface = Color(0xFFFFFFFF),
    error = StatusBlockedRed,
)

@Composable
fun ClearPathNexusTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = NexusColorScheme,
        content = content,
    )
}

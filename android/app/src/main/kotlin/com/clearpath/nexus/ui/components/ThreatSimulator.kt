package com.clearpath.nexus.ui.components

import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.clearpath.nexus.ui.theme.PanelBorder
import com.clearpath.nexus.ui.theme.SolarRiskAmber
import com.clearpath.nexus.ui.theme.StatusBlockedRed
import com.clearpath.nexus.ui.theme.TextMuted

@Composable
fun ThreatSimulator(
    stormSeverity: Float,
    solarKp: Float,
    portCongestion: Float,
    simLoading: Boolean,
    simulatedScore: Int?,
    simAlerts: List<String>,
    onStormChange: (Float) -> Unit,
    onSolarChange: (Float) -> Unit,
    onPortChange: (Float) -> Unit,
    onSimulate: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .border(1.dp, PanelBorder)
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(
            text = "THREAT SIMULATION CENTER",
            color = SolarRiskAmber,
            fontSize = 12.sp,
            fontWeight = FontWeight.Bold,
            letterSpacing = 1.sp,
        )

        SliderRow("Storm Severity", stormSeverity.toInt(), stormSeverity, onStormChange, 0f..100f)
        SliderRow("Solar Kp-Index", solarKp.toInt(), solarKp, onSolarChange, 0f..9f)
        SliderRow("Port Congestion", portCongestion.toInt(), portCongestion, onPortChange, 0f..100f)

        Button(
            onClick = onSimulate,
            enabled = !simLoading,
            modifier = Modifier.fillMaxWidth(),
            colors = ButtonDefaults.buttonColors(containerColor = SolarRiskAmber),
        ) {
            Text(
                text = if (simLoading) "SIMULATING…" else "INJECT THREAT",
                fontFamily = FontFamily.Monospace,
                fontWeight = FontWeight.Bold,
            )
        }

        simulatedScore?.let { score ->
            Text(
                text = "Simulated Score: $score",
                color = SolarRiskAmber,
                fontSize = 14.sp,
                fontFamily = FontFamily.Monospace,
            )
        }

        simAlerts.forEach { alert ->
            Text(
                text = "⚠ $alert",
                color = StatusBlockedRed,
                fontSize = 12.sp,
                fontFamily = FontFamily.Monospace,
            )
        }
    }
}

@Composable
private fun SliderRow(
    label: String,
    displayValue: Int,
    value: Float,
    onChange: (Float) -> Unit,
    range: ClosedFloatingPointRange<Float>,
) {
    Column {
        Text(
            text = "$label ($displayValue)",
            color = TextMuted,
            fontSize = 12.sp,
            fontFamily = FontFamily.Monospace,
        )
        Slider(
            value = value,
            onValueChange = onChange,
            valueRange = range,
            colors = SliderDefaults.colors(
                thumbColor = SolarRiskAmber,
                activeTrackColor = SolarRiskAmber,
            ),
        )
    }
}

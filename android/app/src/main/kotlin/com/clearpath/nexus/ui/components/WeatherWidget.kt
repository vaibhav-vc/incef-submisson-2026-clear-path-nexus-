package com.clearpath.nexus.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

@Composable
fun WeatherWidget(
    label: String,
    iconEmoji: String,
    temperature: Float,
    windSpeed: Float,
    humidity: Int,
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .background(color = Color.Black.copy(alpha = 0.6f), shape = RoundedCornerShape(6.dp))
            .padding(horizontal = 8.dp, vertical = 4.dp)
    ) {
        Text(
            text = iconEmoji,
            style = MaterialTheme.typography.bodyLarge,
            modifier = Modifier.padding(end = 4.dp)
        )
        Column {
            Text(text = label, style = MaterialTheme.typography.bodySmall, color = Color.White)
            Text(
                text = "${"%.1f".format(temperature)}°C • ${windSpeed}m/s • ${humidity}%",
                style = MaterialTheme.typography.bodySmall,
                color = Color.White
            )
        }
    }
}

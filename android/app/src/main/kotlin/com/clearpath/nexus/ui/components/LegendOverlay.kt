package com.clearpath.nexus.ui.components

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.clearpath.nexus.ui.theme.AccentSafetyBlue
import com.clearpath.nexus.ui.theme.PanelBorder
import com.clearpath.nexus.ui.theme.PanelDark
import com.clearpath.nexus.ui.theme.SolarRiskAmber
import com.clearpath.nexus.ui.theme.StatusApprovedGreen
import com.clearpath.nexus.ui.theme.StatusBlockedRed

@Composable
fun LegendOverlay(
    alternateRoutes: List<com.clearpath.nexus.data.model.AlternateRoute>
) {
    // Default state: retracted (collapsed)
    var isExpanded by remember { mutableStateOf(false) }

    Column(
        modifier = Modifier
            .background(PanelDark.copy(alpha = 0.9f), RoundedCornerShape(8.dp))
            .border(1.dp, PanelBorder, RoundedCornerShape(8.dp))
    ) {
        // Header row — always visible, acts as toggle
        Row(
            modifier = Modifier
                .clickable { isExpanded = !isExpanded }
                .padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = "ROUTE LEGEND",
                color = Color.White,
                fontSize = 10.sp,
                fontWeight = FontWeight.Bold,
                fontFamily = FontFamily.Monospace
            )
            Spacer(modifier = Modifier.width(6.dp))
            Icon(
                imageVector = if (isExpanded) Icons.Default.KeyboardArrowUp else Icons.Default.KeyboardArrowDown,
                contentDescription = if (isExpanded) "Collapse" else "Expand",
                tint = AccentSafetyBlue,
                modifier = Modifier.size(16.dp)
            )
        }

        // Expandable content — shows all legend items regardless of route presence
        AnimatedVisibility(
            visible = isExpanded,
            enter = expandVertically(),
            exit = shrinkVertically()
        ) {
            Column(
                modifier = Modifier.padding(start = 12.dp, end = 12.dp, bottom = 10.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                // Selected route indicator
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        modifier = Modifier
                            .size(12.dp, 3.dp)
                            .background(AccentSafetyBlue)
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("Selected Route", color = Color.White, fontSize = 9.sp)
                }
                // High safety
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        modifier = Modifier
                            .size(12.dp, 3.dp)
                            .background(StatusApprovedGreen)
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("High Safety (Score ≥ 80)", color = Color.White, fontSize = 9.sp)
                }
                // Medium safety
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        modifier = Modifier
                            .size(12.dp, 3.dp)
                            .background(SolarRiskAmber)
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("Medium Safety (Score 55-79)", color = Color.White, fontSize = 9.sp)
                }
                // Low safety
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        modifier = Modifier
                            .size(12.dp, 3.dp)
                            .background(StatusBlockedRed)
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("Low Safety (Score < 55)", color = Color.White, fontSize = 9.sp)
                }
            }
        }
    }
}

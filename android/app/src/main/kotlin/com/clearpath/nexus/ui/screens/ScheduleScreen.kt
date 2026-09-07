package com.clearpath.nexus.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.clearpath.nexus.data.api.ApiClient
import com.clearpath.nexus.data.api.RouteEvidenceKitDto
import com.clearpath.nexus.data.api.TrainScheduleDto
import com.clearpath.nexus.ui.theme.AccentSafetyBlue
import com.clearpath.nexus.ui.theme.PanelBorder
import com.clearpath.nexus.ui.theme.PanelDark
import com.clearpath.nexus.ui.theme.StatusApprovedGreen
import com.clearpath.nexus.ui.theme.StatusBlockedRed
import com.clearpath.nexus.ui.theme.TextLight
import com.clearpath.nexus.ui.theme.TextMuted
import kotlinx.coroutines.launch

@Composable
fun ScheduleScreen(modifier: Modifier = Modifier) {
    var schedules by remember { mutableStateOf<List<TrainScheduleDto>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var evidenceKits by remember { mutableStateOf<Map<String, RouteEvidenceKitDto>>(emptyMap()) }
    var inFlightScheduleId by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    fun refresh() {
        scope.launch {
            loading = true
            error = null
            try {
                schedules = ApiClient.getSchedules()
                evidenceKits = buildMap {
                    schedules.mapNotNull { it.generatedRouteId }.distinct().forEach { routeId ->
                        runCatching { ApiClient.getEvidenceKit(routeId) }
                            .getOrNull()
                            ?.let { put(routeId, it) }
                    }
                }
            } catch (e: Exception) {
                error = e.message ?: "Could not load schedules"
            } finally {
                loading = false
            }
        }
    }

    LaunchedEffect(Unit) { refresh() }

    Column(
        modifier = modifier.fillMaxSize().background(PanelDark).padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Column {
                Text("TRAIN SCHEDULER", color = TextLight, fontWeight = FontWeight.Bold, fontSize = 14.sp)
                Text("Owner-scoped backend schedules", color = TextMuted, fontFamily = FontFamily.Monospace, fontSize = 10.sp)
            }
            Button(onClick = { refresh() }, colors = ButtonDefaults.buttonColors(containerColor = AccentSafetyBlue)) {
                Text("Refresh", fontSize = 11.sp)
            }
        }

        if (loading) Text("Loading schedules…", color = TextMuted, fontFamily = FontFamily.Monospace)
        error?.let { Text(it, color = StatusBlockedRed, fontSize = 11.sp, fontFamily = FontFamily.Monospace) }

        LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            items(schedules, key = { it.id }) { schedule ->
                val kit = schedule.generatedRouteId?.let(evidenceKits::get)
                ScheduleCard(
                    schedule = schedule,
                    evidenceKit = kit,
                    dispatching = inFlightScheduleId == schedule.id,
                    anotherDispatchInFlight = inFlightScheduleId != null,
                    onDispatch = {
                        scope.launch {
                            inFlightScheduleId = schedule.id
                            error = null
                            try {
                                val updated = ApiClient.approveThenDispatchSchedule(
                                    scheduleId = schedule.id,
                                    routeId = schedule.generatedRouteId,
                                )
                                schedules = schedules.map { if (it.id == updated.id) updated else it }
                                error = null
                            } catch (e: Exception) {
                                error = e.message ?: "Dispatch failed"
                            } finally {
                                inFlightScheduleId = null
                            }
                        }
                    },
                )
            }
        }
    }
}

@Composable
private fun ScheduleCard(
    schedule: TrainScheduleDto,
    evidenceKit: RouteEvidenceKitDto?,
    dispatching: Boolean,
    anotherDispatchInFlight: Boolean,
    onDispatch: () -> Unit,
) {
    val statusColor = when (schedule.conflictStatus) {
        "CLEAR" -> StatusApprovedGreen
        "BLOCKED" -> StatusBlockedRed
        else -> Color(0xFFF59E0B)
    }
    val evidenceReady = evidenceKit?.decisionState == "READY" && evidenceKit.integrity.verified
    val linkedRouteAvailable = !schedule.generatedRouteId.isNullOrBlank()
    Column(
        modifier = Modifier.fillMaxWidth()
            .background(Color(0xFF111827), RoundedCornerShape(10.dp))
            .border(1.dp, PanelBorder, RoundedCornerShape(10.dp))
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Column {
                Text(schedule.trainCode, color = AccentSafetyBlue, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace)
                Text(schedule.trainName, color = TextLight, fontSize = 12.sp)
            }
            Text(schedule.conflictStatus, color = statusColor, fontWeight = FontWeight.Bold, fontSize = 11.sp, fontFamily = FontFamily.Monospace)
        }
        Text("${schedule.sourceStationCode} → ${schedule.destStationCode}", color = TextLight, fontFamily = FontFamily.Monospace, fontSize = 12.sp)
        Text("DEP ${schedule.scheduledDeparture.replace('T', ' ')}", color = TextMuted, fontFamily = FontFamily.Monospace, fontSize = 10.sp)
        Text("ARR ${schedule.scheduledArrival.replace('T', ' ')}", color = TextMuted, fontFamily = FontFamily.Monospace, fontSize = 10.sp)
        schedule.conflictReason?.let { Text(it, color = statusColor, fontFamily = FontFamily.Monospace, fontSize = 10.sp) }
        Text(
            "EvidenceGate: ${evidenceKit?.decisionState ?: "UNAVAILABLE"} · " +
                "Integrity ${if (evidenceKit?.integrity?.verified == true) "VERIFIED" else "UNAVAILABLE"}",
            color = if (evidenceReady) StatusApprovedGreen else StatusBlockedRed,
            fontFamily = FontFamily.Monospace,
            fontSize = 10.sp,
        )
        if (!linkedRouteAvailable || !evidenceReady) {
            Text(
                if (!linkedRouteAvailable) {
                    "Dispatch disabled: no linked evaluated route."
                } else {
                    "Dispatch disabled: verified READY evidence is required."
                },
                color = StatusBlockedRed,
                fontFamily = FontFamily.Monospace,
                fontSize = 9.sp,
            )
        }
        Button(
            onClick = onDispatch,
            enabled = schedule.conflictStatus != "BLOCKED" &&
                schedule.scheduleStatus !in setOf("DISPATCHED", "CANCELLED") &&
                linkedRouteAvailable &&
                evidenceReady &&
                !anotherDispatchInFlight,
            modifier = Modifier.fillMaxWidth(),
            colors = ButtonDefaults.buttonColors(containerColor = StatusApprovedGreen),
        ) {
            Text(
                when {
                    schedule.scheduleStatus == "DISPATCHED" -> "DISPATCHED"
                    schedule.conflictStatus == "BLOCKED" -> "DISPATCH BLOCKED"
                    dispatching -> "APPROVING & DISPATCHING…"
                    !linkedRouteAvailable -> "NO LINKED ROUTE"
                    !evidenceReady -> "EVIDENCE NOT READY"
                    else -> "APPROVE EVIDENCE & DISPATCH"
                },
                fontSize = 11.sp,
                fontWeight = FontWeight.Bold,
            )
        }
    }
}

package com.clearpath.nexus.ui.components

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.foundation.BorderStroke
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.clearpath.nexus.data.model.LoadProfile
import com.clearpath.nexus.ui.theme.AccentSafetyBlue
import com.clearpath.nexus.ui.theme.PanelBorder
import com.clearpath.nexus.ui.theme.PanelDark
import com.clearpath.nexus.ui.theme.PrimaryCommandBlue
import com.clearpath.nexus.ui.theme.SolarRiskAmber
import com.clearpath.nexus.ui.theme.StatusApprovedGreen
import com.clearpath.nexus.ui.theme.StatusBlockedRed
import com.clearpath.nexus.ui.theme.TelemetryCanvasDark
import com.clearpath.nexus.ui.theme.TextLight
import com.clearpath.nexus.ui.theme.TextMuted

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LoadProfilesPanel(
    loadProfiles: List<LoadProfile>,
    selectedProfileId: String?,
    onProfileSelect: (String) -> Unit,
    onProfileSave: (name: String, height: Double, width: Double, weight: Double, compartments: Int, purpose: String, notes: String) -> Unit,
    onProfileDelete: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    var showCreateDialog by remember { mutableStateOf(false) }
    var profileName by remember { mutableStateOf("") }
    var profileHeight by remember { mutableStateOf("") }
    var profileWidth by remember { mutableStateOf("") }
    var profileWeight by remember { mutableStateOf("") }
    var profileCompartments by remember { mutableStateOf("1") }
    var profilePurpose by remember { mutableStateOf("") }
    var profileNotes by remember { mutableStateOf("") }
    var dialogError by remember { mutableStateOf<String?>(null) }

    val selectedProfile = loadProfiles.find { it.id == selectedProfileId }

    Column(
        modifier = modifier.background(TelemetryCanvasDark),
    ) {
        // ── Header ──────────────────────────────────────────────────────────
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .background(
                    Brush.verticalGradient(
                        colors = listOf(PrimaryCommandBlue.copy(alpha = 0.9f), TelemetryCanvasDark)
                    )
                )
                .padding(horizontal = 20.dp, vertical = 18.dp)
        ) {
            Column {
                Text(
                    text = "CARGO LOAD PROFILES",
                    color = Color.White,
                    fontSize = 14.sp,
                    fontWeight = FontWeight.Black,
                    letterSpacing = 2.sp,
                    fontFamily = FontFamily.Monospace
                )
                Text(
                    text = "${loadProfiles.size} profile${if (loadProfiles.size != 1) "s" else ""} saved  •  ${if (selectedProfile != null) "Active: ${selectedProfile.name}" else "None selected"}",
                    color = TextMuted,
                    fontSize = 11.sp,
                    fontFamily = FontFamily.Monospace,
                    modifier = Modifier.padding(top = 4.dp)
                )
            }
        }

        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
            contentPadding = PaddingValues(vertical = 16.dp)
        ) {
            // ── Active Profile Detail Card ───────────────────────────────────
            if (selectedProfile != null) {
                item {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(14.dp))
                            .background(
                                Brush.linearGradient(
                                    colors = listOf(
                                        AccentSafetyBlue.copy(alpha = 0.25f),
                                        PrimaryCommandBlue.copy(alpha = 0.15f)
                                    )
                                )
                            )
                            .border(1.dp, AccentSafetyBlue.copy(alpha = 0.6f), RoundedCornerShape(14.dp))
                            .padding(16.dp)
                    ) {
                        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(8.dp)
                            ) {
                                Icon(
                                    Icons.Default.CheckCircle,
                                    contentDescription = null,
                                    tint = StatusApprovedGreen,
                                    modifier = Modifier.size(16.dp)
                                )
                                Text(
                                    "ACTIVE PROFILE",
                                    color = StatusApprovedGreen,
                                    fontSize = 10.sp,
                                    fontWeight = FontWeight.Bold,
                                    letterSpacing = 1.5.sp,
                                    fontFamily = FontFamily.Monospace,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis
                                )
                            }
                            Text(
                                text = selectedProfile.name,
                                color = Color.White,
                                fontSize = 18.sp,
                                fontWeight = FontWeight.Bold,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis
                            )
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(12.dp)
                            ) {
                                ActiveSpecCard("HEIGHT", "${selectedProfile.height} m", AccentSafetyBlue, Modifier.weight(1f))
                                ActiveSpecCard("WIDTH", "${selectedProfile.width} m", SolarRiskAmber, Modifier.weight(1f))
                                ActiveSpecCard("WEIGHT", "${selectedProfile.weight} T", StatusApprovedGreen, Modifier.weight(1f))
                            }
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(12.dp)
                            ) {
                                ActiveSpecCard("COMPARTMENTS", "${selectedProfile.compartments}", AccentSafetyBlue.copy(alpha = 0.7f), Modifier.weight(1f))
                                if (selectedProfile.compartmentPurpose.isNotBlank()) {
                                    ActiveSpecCard("PURPOSE", selectedProfile.compartmentPurpose, TextMuted, Modifier.weight(2f))
                                }
                            }
                            if (selectedProfile.notes.isNotBlank()) {
                                Text(
                                    text = "📋  ${selectedProfile.notes}",
                                    color = TextMuted,
                                    fontSize = 11.sp,
                                    fontFamily = FontFamily.Monospace,
                                    maxLines = 2,
                                    overflow = TextOverflow.Ellipsis,
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .background(PanelDark.copy(alpha = 0.4f), RoundedCornerShape(6.dp))
                                        .padding(horizontal = 10.dp, vertical = 6.dp)
                                )
                            }
                        }
                    }
                }

                item {
                    Spacer(Modifier.height(4.dp))
                    Text(
                        "ALL PROFILES",
                        color = TextMuted,
                        fontSize = 10.sp,
                        fontWeight = FontWeight.Bold,
                        letterSpacing = 1.5.sp,
                        fontFamily = FontFamily.Monospace,
                        modifier = Modifier.padding(bottom = 4.dp),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }
            }

            // ── Profile List ──────────────────────────────────────────────────
            items(loadProfiles) { profile ->
                val isSelected = profile.id == selectedProfileId
                val borderColor by animateColorAsState(
                    targetValue = if (isSelected) AccentSafetyBlue else PanelBorder,
                    animationSpec = tween(200),
                    label = "border"
                )

                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(12.dp))
                        .background(
                            if (isSelected) PrimaryCommandBlue.copy(alpha = 0.3f)
                            else PanelDark.copy(alpha = 0.7f)
                        )
                        .border(
                            width = if (isSelected) 2.dp else 1.dp,
                            color = borderColor,
                            shape = RoundedCornerShape(12.dp)
                        )
                        .clickable { onProfileSelect(profile.id) }
                        .padding(14.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    Box(
                        modifier = Modifier
                            .size(10.dp, 42.dp)
                            .clip(RoundedCornerShape(4.dp))
                            .background(if (isSelected) AccentSafetyBlue else PanelBorder)
                    )

                    Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text(
                                text = profile.name,
                                color = if (isSelected) Color.White else TextLight,
                                fontWeight = FontWeight.Bold,
                                fontSize = 14.sp,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.weight(1f, fill = false)
                            )
                            if (isSelected) {
                                Text(
                                    text = "ACTIVE",
                                    color = AccentSafetyBlue,
                                    fontSize = 8.sp,
                                    fontWeight = FontWeight.Black,
                                    letterSpacing = 1.sp,
                                    fontFamily = FontFamily.Monospace,
                                    maxLines = 1,
                                    modifier = Modifier
                                        .background(AccentSafetyBlue.copy(alpha = 0.15f), RoundedCornerShape(4.dp))
                                        .padding(horizontal = 5.dp, vertical = 2.dp)
                                )
                            }
                        }
                        Text(
                            text = "${profile.height}m H  ×  ${profile.width}m W  ·  ${profile.weight}T  ·  ${profile.compartments} comp.",
                            color = TextMuted,
                            fontSize = 11.sp,
                            fontFamily = FontFamily.Monospace,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis
                        )
                        if (profile.compartmentPurpose.isNotBlank()) {
                            Text(
                                text = profile.compartmentPurpose,
                                color = SolarRiskAmber.copy(alpha = 0.8f),
                                fontSize = 10.sp,
                                fontFamily = FontFamily.Monospace,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis
                            )
                        }
                    }

                    if (profile.id != "lp-std") {
                        IconButton(
                            onClick = { onProfileDelete(profile.id) },
                            modifier = Modifier.size(32.dp)
                        ) {
                            Icon(
                                Icons.Default.Delete,
                                contentDescription = "Delete profile",
                                tint = StatusBlockedRed.copy(alpha = 0.7f),
                                modifier = Modifier.size(18.dp)
                            )
                        }
                    }
                }
            }

            // ── Add New Profile Button ─────────────────────────────────────
            item {
                Spacer(Modifier.height(4.dp))
                Button(
                    onClick = {
                        profileName = ""; profileHeight = ""; profileWidth = ""
                        profileWeight = ""; profileCompartments = "1"
                        profilePurpose = ""; profileNotes = ""; dialogError = null
                        showCreateDialog = true
                    },
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(52.dp),
                    shape = RoundedCornerShape(12.dp),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = AccentSafetyBlue.copy(alpha = 0.15f)
                    ),
                    border = BorderStroke(1.dp, AccentSafetyBlue.copy(alpha = 0.5f))
                ) {
                    Icon(Icons.Default.Add, contentDescription = null, tint = AccentSafetyBlue, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(8.dp))
                    Text(
                        "Create New Load Profile",
                        color = AccentSafetyBlue,
                        fontFamily = FontFamily.Monospace,
                        fontWeight = FontWeight.Bold,
                        fontSize = 13.sp
                    )
                }
            }
        }
    }

    // ── Create Profile Dialog ──────────────────────────────────────────────
    if (showCreateDialog) {
        AlertDialog(
            onDismissRequest = { showCreateDialog = false },
            title = {
                Text("New Load Profile", color = Color.White, fontWeight = FontWeight.Bold, fontSize = 16.sp)
            },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    lpField("Profile Name", profileName, { profileName = it })
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        lpField("Height (m)", profileHeight, { profileHeight = it }, Modifier.weight(1f))
                        lpField("Width (m)", profileWidth, { profileWidth = it }, Modifier.weight(1f))
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        lpField("Weight (T)", profileWeight, { profileWeight = it }, Modifier.weight(1f))
                        lpField("Compartments", profileCompartments, { profileCompartments = it }, Modifier.weight(1f))
                    }
                    lpField("Purpose (e.g. Hazmat)", profilePurpose, { profilePurpose = it })
                    lpField("Notes (optional)", profileNotes, { profileNotes = it })
                    dialogError?.let {
                        Text(it, color = StatusBlockedRed, fontSize = 11.sp, fontFamily = FontFamily.Monospace)
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    val hVal = profileHeight.toDoubleOrNull()
                    val wVal = profileWidth.toDoubleOrNull()
                    val wtVal = profileWeight.toDoubleOrNull()
                    val cVal = profileCompartments.toIntOrNull()
                    if (profileName.isBlank() || hVal == null || wVal == null || wtVal == null || cVal == null || hVal <= 0 || wVal <= 0 || wtVal <= 0 || cVal <= 0) {
                        dialogError = "All fields required and must be positive"
                    } else {
                        onProfileSave(profileName, hVal, wVal, wtVal, cVal, profilePurpose, profileNotes)
                        showCreateDialog = false
                    }
                }) { Text("Save Profile", color = AccentSafetyBlue, fontWeight = FontWeight.Bold) }
            },
            dismissButton = {
                TextButton(onClick = { showCreateDialog = false }) { Text("Cancel", color = TextLight) }
            },
            containerColor = PanelDark,
            textContentColor = Color.White
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun lpField(label: String, value: String, onChange: (String) -> Unit, modifier: Modifier = Modifier.fillMaxWidth()) {
    OutlinedTextField(
        value = value,
        onValueChange = onChange,
        label = { Text(label, fontSize = 11.sp) },
        singleLine = true,
        modifier = modifier,
        colors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = AccentSafetyBlue,
            unfocusedBorderColor = PanelBorder,
            focusedContainerColor = PanelDark,
            unfocusedContainerColor = PanelDark,
            focusedTextColor = Color.White,
            unfocusedTextColor = Color.White,
            focusedLabelColor = TextMuted,
            unfocusedLabelColor = TextMuted,
        )
    )
}

@Composable
private fun ActiveSpecCard(label: String, value: String, accent: Color, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier
            .background(PanelDark.copy(alpha = 0.5f), RoundedCornerShape(8.dp))
            .border(1.dp, accent.copy(alpha = 0.3f), RoundedCornerShape(8.dp))
            .padding(horizontal = 8.dp, vertical = 8.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            text = label,
            color = TextMuted,
            fontSize = 9.sp,
            fontFamily = FontFamily.Monospace,
            letterSpacing = 1.sp,
            maxLines = 1,
            overflow = androidx.compose.ui.text.style.TextOverflow.Clip
        )
        Spacer(Modifier.height(4.dp))
        Text(
            text = value,
            color = accent,
            fontSize = 14.sp,
            fontWeight = FontWeight.Bold,
            fontFamily = FontFamily.Monospace,
            maxLines = 1,
            overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis
        )
    }
}

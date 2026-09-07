package com.clearpath.nexus.ui.screens

import android.graphics.Paint
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Speed
import androidx.compose.material.icons.filled.Timer
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.runtime.setValue
import androidx.compose.runtime.mutableStateOf
import com.clearpath.nexus.data.model.AlternateRoute
import com.clearpath.nexus.data.api.LoadingWindowDto
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
import com.clearpath.nexus.viewmodel.RouteSelectionViewModel
import org.osmdroid.tileprovider.tilesource.TileSourceFactory
import org.osmdroid.util.BoundingBox
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.MapView
import org.osmdroid.views.overlay.Marker
import org.osmdroid.views.overlay.Polyline
import androidx.activity.compose.BackHandler
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver

// Route colors for up to 4 routes
private val ROUTE_COLORS = listOf(
    Color(0xFF3182CE), // Blue
    Color(0xFFE53E3E), // Red
    Color(0xFF38A169), // Green
    Color(0xFFDD6B20), // Orange
)

private val ROUTE_COLORS_MUTED = listOf(
    Color(0xFF3182CE).copy(alpha = 0.3f),
    Color(0xFFE53E3E).copy(alpha = 0.3f),
    Color(0xFF38A169).copy(alpha = 0.3f),
    Color(0xFFDD6B20).copy(alpha = 0.3f),
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RouteSelectionScreen(
    height: Double,
    width: Double,
    weight: Double,
    sourceCode: String,
    destCode: String,
    trainHours: Double,
    portId: String,
    vesselId: String,
    stops: List<String> = emptyList(),
    loadingWindow: LoadingWindowDto? = null,
    onRouteConfirmed: (AlternateRoute, List<AlternateRoute>) -> Unit,
    onBack: () -> Unit,
    routeViewModel: RouteSelectionViewModel = viewModel(),
) {
    val state by routeViewModel.uiState.collectAsState()

    BackHandler {
        onBack()
    }

    LaunchedEffect(sourceCode, destCode, stops, portId, vesselId, loadingWindow) {
        if (state.routes.isEmpty()) {
            routeViewModel.loadRoutes(
                height, width, weight, sourceCode, destCode, trainHours,
                portId, vesselId, stops, loadingWindow,
            )
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(
                            Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back",
                            tint = Color.White,
                        )
                    }
                },
                title = {
                    Column {
                        Text(
                            text = "Evidence Review",
                            fontWeight = FontWeight.Bold,
                            fontSize = 18.sp,
                        )
                        Text(
                            text = "${(listOf(sourceCode) + stops + destCode).joinToString(" → ")}  •  backend-evaluated corridor",
                            fontSize = 10.sp,
                            fontFamily = FontFamily.Monospace,
                            color = TextLight,
                        )
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = PrimaryCommandBlue,
                    titleContentColor = Color.White,
                ),
            )
        },
        bottomBar = {
            val selected = state.routes.find { it.id == state.selectedRouteId }
            if (selected != null) {
                val totalEstimatedHours = selected.estimatedHours
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(
                            Brush.verticalGradient(
                                colors = listOf(
                                    Color.Transparent,
                                    PanelDark.copy(alpha = 0.95f),
                                    PanelDark,
                                ),
                            ),
                        )
                        .padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    // Estimated time + reliability summary row
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceEvenly,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Text(
                                text = totalEstimatedHours?.let { "${"%.1f".format(it)}h" } ?: "—",
                                color = Color.White,
                                fontWeight = FontWeight.Bold,
                                fontSize = 18.sp,
                                fontFamily = FontFamily.Monospace,
                            )
                            Text(
                                text = "Est. Total Time",
                                color = TextMuted,
                                fontSize = 9.sp,
                                fontFamily = FontFamily.Monospace,
                            )
                        }
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Text(
                                text = "${selected.reliabilityScore}",
                                color = when {
                                    selected.reliabilityScore >= 80 -> StatusApprovedGreen
                                    selected.reliabilityScore >= 55 -> SolarRiskAmber
                                    else -> StatusBlockedRed
                                },
                                fontWeight = FontWeight.Bold,
                                fontSize = 18.sp,
                                fontFamily = FontFamily.Monospace,
                            )
                            Text(
                                text = "Reliability",
                                color = TextMuted,
                                fontSize = 9.sp,
                                fontFamily = FontFamily.Monospace,
                            )
                        }
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Text(
                                text = "${selected.stationCodes.size}",
                                color = Color.White,
                                fontWeight = FontWeight.Bold,
                                fontSize = 18.sp,
                                fontFamily = FontFamily.Monospace,
                            )
                            Text(
                                text = "Stations",
                                color = TextMuted,
                                fontSize = 9.sp,
                                fontFamily = FontFamily.Monospace,
                            )
                        }
                    }

                    Button(
                        onClick = { onRouteConfirmed(selected, state.routes) },
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(52.dp),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = AccentSafetyBlue,
                        ),
                        shape = RoundedCornerShape(14.dp),
                    ) {
                        Icon(
                            Icons.Default.CheckCircle,
                            contentDescription = null,
                            modifier = Modifier.size(20.dp),
                        )
                        Spacer(Modifier.width(8.dp))
                        Text(
                            text = "Confirm: ${selected.label}",
                            fontFamily = FontFamily.Monospace,
                            fontWeight = FontWeight.Bold,
                            fontSize = 14.sp,
                        )
                    }
                }
            }
        },
        containerColor = TelemetryCanvasDark,
    ) { padding ->
        if (state.isLoading) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding),
                contentAlignment = Alignment.Center,
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    CircularProgressIndicator(color = AccentSafetyBlue)
                    Spacer(Modifier.height(16.dp))
                    Text(
                        text = "Analyzing corridors…",
                        color = TextMuted,
                        fontFamily = FontFamily.Monospace,
                        fontSize = 12.sp,
                    )
                }
            }
        } else if (state.routes.isEmpty()) {
            Box(
                modifier = Modifier.fillMaxSize().padding(padding).padding(24.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = state.weatherError ?: "Live route evidence unavailable.",
                    color = StatusBlockedRed,
                    fontFamily = FontFamily.Monospace,
                )
            }
        } else {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding),
            ) {
                // Backend-owned route evidence review card.
                LazyRow(
                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp),
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    items(state.routes) { route ->
                        val index = state.routes.indexOf(route)
                        RouteCard(
                            route = route,
                            routeColor = ROUTE_COLORS.getOrElse(index) { AccentSafetyBlue },
                            isSelected = route.id == state.selectedRouteId,
                            isLoadingWeather = state.isLoadingWeather,
                            onClick = { routeViewModel.onRouteSelected(route.id) },
                        )
                    }
                }

                // Map for the evaluated journey; the client does not invent alternates.
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(horizontal = 8.dp)
                        .padding(bottom = 4.dp)
                        .clip(RoundedCornerShape(16.dp))
                ) {
                    RouteComparisonMap(
                        routes = state.routes,
                        selectedRouteId = state.selectedRouteId,
                        modifier = Modifier.fillMaxSize(),
                    )

                    // Top Left: Weather Widgets
                    val selectedRoute = state.routes.find { it.id == state.selectedRouteId }
                    if (selectedRoute != null) {
                        WeatherWidgetsOverlay(
                            condition = selectedRoute.weatherCondition,
                            modifier = Modifier
                                .align(Alignment.TopStart)
                                .padding(12.dp)
                        )
                    }

                    // Top Right: Legend Overlay
                    MapLegendOverlay(
                        modifier = Modifier
                            .align(Alignment.TopEnd)
                            .padding(12.dp)
                    )
                }
            }
        }
    }
}

// ── Route Card ──────────────────────────────────────────────────────────────

@Composable
private fun RouteCard(
    route: AlternateRoute,
    routeColor: Color,
    isSelected: Boolean,
    isLoadingWeather: Boolean,
    onClick: () -> Unit,
) {
    val borderColor by animateColorAsState(
        targetValue = if (isSelected) routeColor else PanelBorder,
        animationSpec = tween(250),
        label = "borderColor",
    )
    val elevation by animateDpAsState(
        targetValue = if (isSelected) 8.dp else 2.dp,
        animationSpec = tween(250),
        label = "elevation",
    )

    Card(
        modifier = Modifier
            .width(220.dp)
            .clickable(onClick = onClick)
            .border(
                width = if (isSelected) 2.dp else 1.dp,
                color = borderColor,
                shape = RoundedCornerShape(14.dp),
            ),
        colors = CardDefaults.cardColors(
            containerColor = if (isSelected)
                PanelDark.copy(alpha = 0.95f)
            else
                PanelDark.copy(alpha = 0.7f),
        ),
        shape = RoundedCornerShape(14.dp),
        elevation = CardDefaults.cardElevation(defaultElevation = elevation),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            // Header — route color bar + label
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    modifier = Modifier
                        .size(12.dp)
                        .clip(CircleShape)
                        .background(routeColor),
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    text = route.label,
                    color = Color.White,
                    fontWeight = FontWeight.Bold,
                    fontSize = 13.sp,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }

            Spacer(Modifier.height(10.dp))

            // Status chip
            val statusColor = when (route.status) {
                "APPROVED" -> StatusApprovedGreen
                "HARD_BLOCKED" -> StatusBlockedRed
                else -> TextMuted
            }
            Text(
                text = route.status,
                color = statusColor,
                fontSize = 10.sp,
                fontWeight = FontWeight.Bold,
                fontFamily = FontFamily.Monospace,
                modifier = Modifier
                    .background(statusColor.copy(alpha = 0.15f), RoundedCornerShape(4.dp))
                    .padding(horizontal = 6.dp, vertical = 2.dp),
            )
            Text(
                text = "${route.decisionState} · ${route.decisionSource}",
                color = when (route.decisionState) {
                    "READY" -> StatusApprovedGreen
                    "HARD_BLOCKED" -> StatusBlockedRed
                    else -> SolarRiskAmber
                },
                fontSize = 8.sp,
                fontFamily = FontFamily.Monospace,
            )

            Spacer(Modifier.height(10.dp))

            // Scores row
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                // Reliability score
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(
                        Icons.Default.Speed,
                        contentDescription = null,
                        tint = AccentSafetyBlue,
                        modifier = Modifier.size(16.dp),
                    )
                    Text(
                        text = "${route.reliabilityScore}",
                        color = Color.White,
                        fontWeight = FontWeight.Bold,
                        fontSize = 20.sp,
                        fontFamily = FontFamily.Monospace,
                    )
                    Text(
                        text = "Reliability",
                        color = TextMuted,
                        fontSize = 8.sp,
                        fontFamily = FontFamily.Monospace,
                    )
                }

                // Weather score
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    if (isLoadingWeather) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(16.dp),
                            color = AccentSafetyBlue,
                            strokeWidth = 2.dp,
                        )
                    } else {
                        Text(
                            text = route.weatherCondition?.iconEmoji ?: "🌡️",
                            fontSize = 16.sp,
                        )
                    }
                    Text(
                        text = route.weatherScore?.toString() ?: "—",
                        color = weatherScoreColor(route.weatherScore),
                        fontWeight = FontWeight.Bold,
                        fontSize = 20.sp,
                        fontFamily = FontFamily.Monospace,
                    )
                    Text(
                        text = "Weather",
                        color = TextMuted,
                        fontSize = 8.sp,
                        fontFamily = FontFamily.Monospace,
                    )
                }

                // ETA
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(
                        Icons.Default.Timer,
                        contentDescription = null,
                        tint = SolarRiskAmber,
                        modifier = Modifier.size(16.dp),
                    )
                    Text(
                        text = route.estimatedHours?.let { "${"%.1f".format(it)}h" } ?: "Unavailable",
                        color = Color.White,
                        fontWeight = FontWeight.Bold,
                        fontSize = 18.sp,
                        fontFamily = FontFamily.Monospace,
                    )
                    Text(
                        text = "ETA",
                        color = TextMuted,
                        fontSize = 8.sp,
                        fontFamily = FontFamily.Monospace,
                    )
                }
            }

            // Weather description
            if (!isLoadingWeather && route.weatherCondition != null) {
                Spacer(Modifier.height(8.dp))
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(
                            PrimaryCommandBlue.copy(alpha = 0.4f),
                            RoundedCornerShape(6.dp),
                        )
                        .padding(horizontal = 8.dp, vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = route.weatherCondition.iconEmoji,
                        fontSize = 14.sp,
                    )
                    Spacer(Modifier.width(6.dp))
                    Column {
                        Text(
                            text = route.weatherCondition.conditionLabel,
                            color = Color.White,
                            fontSize = 10.sp,
                            fontWeight = FontWeight.SemiBold,
                        )
                        Text(
                            text = "${"%.1f".format(route.weatherCondition.temp)}°C  •  ${route.weatherCondition.windSpeed}m/s  •  ${route.weatherCondition.humidity}%",
                            color = TextMuted,
                            fontSize = 8.sp,
                            fontFamily = FontFamily.Monospace,
                        )
                    }
                }
            }

            // Waypoints
            Spacer(Modifier.height(6.dp))
            Row(
                modifier = Modifier.horizontalScroll(rememberScrollState()),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                route.stationCodes.forEachIndexed { i, code ->
                    Text(
                        text = code,
                        color = TextLight,
                        fontSize = 9.sp,
                        fontFamily = FontFamily.Monospace,
                        fontWeight = FontWeight.Bold,
                    )
                    if (i < route.stationCodes.lastIndex) {
                        Text(
                            text = " → ",
                            color = TextMuted,
                            fontSize = 8.sp,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun weatherScoreColor(score: Int?): Color = when {
    score == null -> TextMuted
    score >= 80 -> StatusApprovedGreen
    score >= 55 -> SolarRiskAmber
    else -> StatusBlockedRed
}

// ── Route Comparison Map ────────────────────────────────────────────────────

@Composable
private fun RouteComparisonMap(
    routes: List<AlternateRoute>,
    selectedRouteId: String?,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val mapView = remember {
        MapView(context).apply {
            setTileSource(TileSourceFactory.MAPNIK)
            setMultiTouchControls(true)
            controller.setZoom(6.0)
            controller.setCenter(GeoPoint(20.0, 76.0))
        }
    }

    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner, mapView) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_RESUME -> mapView.onResume()
                Lifecycle.Event.ON_PAUSE -> mapView.onPause()
                Lifecycle.Event.ON_DESTROY -> mapView.onDetach()
                else -> {}
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
        }
    }

    DisposableEffect(routes, selectedRouteId) {
        mapView.overlays.clear()

        // Draw all route polylines — muted for non-selected, bright for selected
        routes.forEachIndexed { index, route ->
            val isSelected = route.id == selectedRouteId
            val color = if (isSelected) {
                AccentSafetyBlue.toArgb()
            } else {
                when (route.decisionState) {
                    "READY" -> StatusApprovedGreen.copy(alpha = 0.6f).toArgb()
                    "HARD_BLOCKED" -> StatusBlockedRed.copy(alpha = 0.6f).toArgb()
                    else -> SolarRiskAmber.copy(alpha = 0.6f).toArgb()
                }
            }

            val allPoints = route.segments.flatMap { seg ->
                seg.coordinates.map { GeoPoint(it[0], it[1]) }
            }

            if (allPoints.isNotEmpty()) {
                val polyline = Polyline().apply {
                    setPoints(allPoints)
                    outlinePaint.color = color
                    outlinePaint.strokeWidth = if (isSelected) 12f else 6f
                    outlinePaint.strokeCap = Paint.Cap.ROUND
                    outlinePaint.isAntiAlias = true
                }
                mapView.overlays.add(polyline)
            }
        }

        // Station markers for all routes
        val stationSet = mutableSetOf<String>()
        routes.forEach { route ->
            route.segments.forEach { seg ->
                seg.coordinates.firstOrNull()?.let { coord ->
                    val key = "${coord[0]},${coord[1]}"
                    if (key !in stationSet) {
                        stationSet.add(key)
                        val marker = Marker(mapView).apply {
                            position = GeoPoint(coord[0], coord[1])
                            setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
                            title = route.stationCodes.firstOrNull() ?: ""
                        }
                        mapView.overlays.add(marker)
                    }
                }
                seg.coordinates.lastOrNull()?.let { coord ->
                    val key = "${coord[0]},${coord[1]}"
                    if (key !in stationSet) {
                        stationSet.add(key)
                        val marker = Marker(mapView).apply {
                            position = GeoPoint(coord[0], coord[1])
                            setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
                        }
                        mapView.overlays.add(marker)
                    }
                }
            }
        }

        // Weather condition markers at each route's midpoint
        routes.forEachIndexed { index, route ->
            val weather = route.weatherCondition ?: return@forEachIndexed
            val lat = route.midpoint.getOrNull(0) ?: return@forEachIndexed
            val lon = route.midpoint.getOrNull(1) ?: return@forEachIndexed

            val marker = Marker(mapView).apply {
                position = GeoPoint(lat, lon)
                setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
                title = "${weather.iconEmoji} ${weather.conditionLabel}"
                snippet = "${"%.1f".format(weather.temp)}°C  •  ${weather.windSpeed}m/s  •  ${weather.humidity}% humidity"
            }
            mapView.overlays.add(marker)
        }

        // Zoom to fit all routes
        val allMapPoints = routes.flatMap { route ->
            route.segments.flatMap { seg ->
                seg.coordinates.map { GeoPoint(it[0], it[1]) }
            }
        }
        if (allMapPoints.isNotEmpty()) {
            val lats = allMapPoints.map { it.latitude }
            val lons = allMapPoints.map { it.longitude }
            val bbox = BoundingBox(
                lats.maxOrNull()!! + 0.2,
                lons.maxOrNull()!! + 0.2,
                lats.minOrNull()!! - 0.2,
                lons.minOrNull()!! - 0.2,
            )
            mapView.post { mapView.zoomToBoundingBox(bbox, true, 60) }
        }

        mapView.invalidate()
        onDispose { }
    }

    AndroidView(
        factory = { mapView },
        modifier = modifier.fillMaxSize(),
        update = { },
    )
}

@Composable
fun MapLegendOverlay(modifier: Modifier = Modifier) {
    var isExpanded by remember { mutableStateOf(false) }

    Column(
        modifier = modifier
            .background(PanelDark.copy(alpha = 0.9f), RoundedCornerShape(8.dp))
            .border(1.dp, PanelBorder, RoundedCornerShape(8.dp))
    ) {
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

        AnimatedVisibility(
            visible = isExpanded,
            enter = expandVertically(),
            exit = shrinkVertically()
        ) {
            Column(
                modifier = Modifier.padding(start = 12.dp, end = 12.dp, bottom = 10.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(modifier = Modifier.size(12.dp, 3.dp).background(AccentSafetyBlue))
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("Selected Route", color = Color.White, fontSize = 9.sp)
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(modifier = Modifier.size(12.dp, 3.dp).background(StatusApprovedGreen))
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("Evidence READY", color = Color.White, fontSize = 9.sp)
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(modifier = Modifier.size(12.dp, 3.dp).background(SolarRiskAmber))
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("Evidence HOLD / UNAVAILABLE", color = Color.White, fontSize = 9.sp)
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(modifier = Modifier.size(12.dp, 3.dp).background(StatusBlockedRed))
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("HARD_BLOCKED", color = Color.White, fontSize = 9.sp)
                }
            }
        }
    }
}

@Composable
fun WeatherWidgetsOverlay(
    condition: com.clearpath.nexus.data.model.WeatherCondition?,
    modifier: Modifier = Modifier
) {
    if (condition == null) return
    Row(
        modifier = modifier
            .background(PanelDark.copy(alpha = 0.9f), RoundedCornerShape(8.dp))
            .border(1.dp, PanelBorder, RoundedCornerShape(8.dp))
            .padding(8.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        WeatherWidgetField("TEMP", "${"%.1f".format(condition.temp)}°C", condition.iconEmoji)
        WeatherWidgetField("WIND", "${condition.windSpeed}m/s", "🌬️")
        WeatherWidgetField("HUMIDITY", "${condition.humidity}%", "💧")
        WeatherWidgetField("STATUS", condition.conditionLabel, "")
    }
}

@Composable
private fun WeatherWidgetField(label: String, value: String, icon: String) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = Modifier.padding(horizontal = 2.dp)
    ) {
        Text(text = label, color = TextMuted, fontSize = 8.sp, fontFamily = FontFamily.Monospace)
        Spacer(modifier = Modifier.height(2.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (icon.isNotEmpty()) {
                Text(text = icon, fontSize = 10.sp)
                Spacer(modifier = Modifier.width(4.dp))
            }
            Text(text = value, color = Color.White, fontSize = 10.sp, fontWeight = FontWeight.Bold)
        }
    }
}

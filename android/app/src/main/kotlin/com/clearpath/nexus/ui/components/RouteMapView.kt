package com.clearpath.nexus.ui.components

import android.graphics.Paint
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import com.clearpath.nexus.data.model.AlternateRoute
import com.clearpath.nexus.data.model.EnvironmentalZone
import com.clearpath.nexus.data.model.SegmentPath
import com.clearpath.nexus.data.model.Station
import com.clearpath.nexus.ui.theme.AccentSafetyBlue
import com.clearpath.nexus.ui.theme.SolarRiskAmber
import com.clearpath.nexus.ui.theme.StatusApprovedGreen
import com.clearpath.nexus.ui.theme.StatusBlockedRed
import org.osmdroid.tileprovider.tilesource.TileSourceFactory
import org.osmdroid.util.BoundingBox
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.MapView
import org.osmdroid.views.overlay.Marker
import org.osmdroid.views.overlay.Polygon
import org.osmdroid.views.overlay.Polyline
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver

@Composable
fun RouteMapView(
    segments: List<SegmentPath>,
    alternateRoutes: List<AlternateRoute> = emptyList(),
    selectedRouteId: String? = null,
    stations: List<Station>,
    environmentalZones: List<EnvironmentalZone>,
    estimatedTotalHours: Float? = null,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val mapView = remember {
        MapView(context).apply {
            setTileSource(TileSourceFactory.MAPNIK)
            setMultiTouchControls(true)
            controller.setZoom(5.5)
            controller.setCenter(GeoPoint(21.1458, 79.0882))
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

    DisposableEffect(segments, alternateRoutes, selectedRouteId, stations, environmentalZones) {
        mapView.overlays.clear()

        // 1. Draw environmental zones
        environmentalZones.forEach { zone ->
            val polygon = Polygon().apply {
                points = zone.coordinates.map { GeoPoint(it[0], it[1]) }
                fillPaint.color = when (zone.type) {
                    "storm" -> android.graphics.Color.argb(64, 229, 62, 62)
                    else -> android.graphics.Color.argb(64, 221, 107, 32)
                }
                outlinePaint.color = when (zone.type) {
                    "storm" -> StatusBlockedRed.toArgb()
                    else -> SolarRiskAmber.toArgb()
                }
                outlinePaint.strokeWidth = 4f
            }
            mapView.overlays.add(polygon)
        }

        // 2. Draw route polylines
        if (alternateRoutes.isNotEmpty()) {
            alternateRoutes.filter { it.id != selectedRouteId }.forEach { route ->
                val color = when {
                    route.reliabilityScore >= 80 -> StatusApprovedGreen.copy(alpha = 0.6f).toArgb()
                    route.reliabilityScore >= 55 -> SolarRiskAmber.copy(alpha = 0.6f).toArgb()
                    else -> StatusBlockedRed.copy(alpha = 0.6f).toArgb()
                }
                val allPoints = route.segments.flatMap { seg ->
                    seg.coordinates.map { GeoPoint(it[0], it[1]) }
                }
                if (allPoints.isNotEmpty()) {
                    val polyline = Polyline().apply {
                        setPoints(allPoints)
                        outlinePaint.color = color
                        outlinePaint.strokeWidth = 6f
                        outlinePaint.strokeCap = Paint.Cap.ROUND
                        outlinePaint.isAntiAlias = true
                    }
                    mapView.overlays.add(polyline)
                }
            }

            // Draw selected route on top in bright Blue
            alternateRoutes.find { it.id == selectedRouteId }?.let { route ->
                val allPoints = route.segments.flatMap { seg ->
                    seg.coordinates.map { GeoPoint(it[0], it[1]) }
                }
                if (allPoints.isNotEmpty()) {
                    val polyline = Polyline().apply {
                        setPoints(allPoints)
                        outlinePaint.color = AccentSafetyBlue.toArgb()
                        outlinePaint.strokeWidth = 12f
                        outlinePaint.strokeCap = Paint.Cap.ROUND
                        outlinePaint.isAntiAlias = true
                    }
                    mapView.overlays.add(polyline)
                }
            }
        } else {
            // Fallback: draw confirmed segments list (single route)
            segments.forEach { segment ->
                val color = when (segment.status) {
                    "HARD_BLOCKED" -> StatusBlockedRed.toArgb()
                    "APPROVED" -> StatusApprovedGreen.toArgb()
                    else -> AccentSafetyBlue.toArgb()
                }
                val polyline = Polyline().apply {
                    setPoints(segment.coordinates.map { GeoPoint(it[0], it[1]) })
                    outlinePaint.color = color
                    outlinePaint.strokeWidth = 10f
                    outlinePaint.strokeCap = Paint.Cap.ROUND
                    outlinePaint.isAntiAlias = true
                }
                mapView.overlays.add(polyline)
            }
        }

        // 3. Draw station markers
        val stationSet = mutableSetOf<String>()
        if (alternateRoutes.isNotEmpty()) {
            alternateRoutes.forEach { route ->
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
        } else {
            stations.forEach { station ->
                val marker = Marker(mapView).apply {
                    position = GeoPoint(station.lat, station.lon)
                    title = "${station.code} — ${station.name}"
                    setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
                }
                mapView.overlays.add(marker)
            }
        }

        // 4. Draw weather condition markers at route midpoints
        if (alternateRoutes.isNotEmpty()) {
            alternateRoutes.forEach { route ->
                val weather = route.weatherCondition ?: return@forEach
                val lat = route.midpoint.getOrNull(0) ?: return@forEach
                val lon = route.midpoint.getOrNull(1) ?: return@forEach
                val marker = Marker(mapView).apply {
                    position = GeoPoint(lat, lon)
                    setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
                    title = "${weather.iconEmoji} ${weather.conditionLabel}"
                    snippet = "${"%.1f".format(weather.temp)}°C  •  ${weather.windSpeed}m/s  •  ${weather.humidity}% humidity"
                }
                mapView.overlays.add(marker)
            }
        }

        // 5. Auto zoom to fit all routes
        val allPoints = if (alternateRoutes.isNotEmpty()) {
            alternateRoutes.flatMap { r -> r.segments.flatMap { s -> s.coordinates.map { GeoPoint(it[0], it[1]) } } }
        } else {
            segments.flatMap { s -> s.coordinates.map { GeoPoint(it[0], it[1]) } }
        }

        if (allPoints.isNotEmpty()) {
            val lats = allPoints.map { it.latitude }
            val lons = allPoints.map { it.longitude }
            val bbox = BoundingBox(
                lats.maxOrNull()!! + 0.2,
                lons.maxOrNull()!! + 0.2,
                lats.minOrNull()!! - 0.2,
                lons.minOrNull()!! - 0.2,
            )
            mapView.post { mapView.zoomToBoundingBox(bbox, true, 80) }
        }

        mapView.invalidate()
        onDispose { }
    }

    // UI overlay container
    Box(modifier = modifier) {
        AndroidView(
            factory = { mapView },
            modifier = Modifier.fillMaxSize(),
        )

        // Weather widgets overlay (top-right)
        AnimatedVisibility(
            visible = alternateRoutes.isNotEmpty(),
            enter = fadeIn() + slideInVertically(initialOffsetY = { -it }),
            exit = fadeOut() + slideOutVertically(targetOffsetY = { -it }),
            modifier = Modifier.align(Alignment.TopEnd)
        ) {
            Column(
                modifier = Modifier
                    .padding(8.dp)
                    .graphicsLayer(),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                alternateRoutes.forEach { route ->
                    route.weatherCondition?.let { wc ->
                        WeatherWidget(
                            label = wc.conditionLabel,
                            iconEmoji = wc.iconEmoji,
                            temperature = wc.temp.toFloat(),
                            windSpeed = wc.windSpeed.toFloat(),
                            humidity = wc.humidity,
                        )
                    }
                }
            }
        }

        // Bottom overlay: buttons, estimated time, legend
        AnimatedVisibility(
            visible = alternateRoutes.isNotEmpty() || segments.isNotEmpty(),
            enter = fadeIn() + slideInVertically(initialOffsetY = { it }),
            exit = fadeOut() + slideOutVertically(targetOffsetY = { it }),
            modifier = Modifier.align(Alignment.BottomCenter)
        ) {
            Column(
                modifier = Modifier
                    .padding(bottom = 16.dp, start = 8.dp, end = 8.dp)
                    .graphicsLayer(),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                // Legend
                LegendOverlay(alternateRoutes = alternateRoutes)

                // Estimated total time
                estimatedTotalHours?.let { total ->
                    Text(
                        text = "Est. total time: ${"%.1f".format(total)} hrs",
                        color = Color.White,
                    )
                }

            }
        }
    }
}

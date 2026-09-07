package com.clearpath.nexus.data.repository

import com.clearpath.nexus.data.api.ApiClient
import com.clearpath.nexus.data.api.CargoDto
import com.clearpath.nexus.data.api.LoadingWindowDto
import com.clearpath.nexus.data.api.RouteEvaluateRequestDto
import com.clearpath.nexus.data.api.RouteEvaluateResponseDto
import com.clearpath.nexus.data.api.ScoreBreakdownDto
import com.clearpath.nexus.data.api.SupabaseClient
import com.clearpath.nexus.data.api.ThreatSimulationRequestDto
import com.clearpath.nexus.data.api.WeatherService
import com.clearpath.nexus.data.model.AlternateRoute
import com.clearpath.nexus.data.model.RouteEvaluateResponse
import com.clearpath.nexus.data.model.ProvenanceSummary
import com.clearpath.nexus.data.model.ScoreBreakdown
import com.clearpath.nexus.data.model.SegmentPath
import com.clearpath.nexus.data.model.Station
import com.clearpath.nexus.data.model.ThreatSimulationResponse
import com.clearpath.nexus.data.model.WeatherCondition

/**
 * Live-backend repository.
 *
 * Features come from the FastAPI backend, which owns the scoring logic.
 * Operational results are never substituted with bundled numbers. Provider or
 * backend failures propagate to the UI as unavailable states.
 *
 * Auth is unchanged: Supabase owns sessions; ApiClient forwards the token.
 */
class NexusRepository {

    /** Result plus where it came from, so the UI never has to guess. */
    data class Sourced<T>(
        val data: T,
        val computedOffline: Boolean,
        val reason: String? = null,
        val sourceLabel: String = "REMOTE_BACKEND",
    )

    suspend fun fetchStations(): Sourced<List<Station>> = Sourced(
        data = ApiClient.getStations().map { Station(it.id, it.name, it.code, it.lat, it.lon) },
        computedOffline = false,
    )

    suspend fun evaluateRoute(
        height: Double,
        width: Double,
        weight: Double,
        sourceCode: String,
        destCode: String,
        trainArrivalHours: Double,
        portId: String,
        vesselId: String,
        stops: List<String> = emptyList(),
        loadingWindow: LoadingWindowDto? = null,
    ): Sourced<RouteEvaluateResponse> {
        val waypoints = listOf(sourceCode) + stops + destCode
        val legs = waypoints.zipWithNext().map { (source, destination) ->
            ApiClient.evaluateRoute(
                RouteEvaluateRequestDto(
                    cargo = CargoDto(height, width, weight),
                    sourceCode = source,
                    destCode = destination,
                    portId = portId,
                    vesselId = vesselId,
                    trainArrivalHours = trainArrivalHours,
                    loadingWindow = loadingWindow,
                )
            ).toDomain()
        }
        return Sourced(data = aggregateRouteLegs(legs), computedOffline = false)
    }

    suspend fun simulateThreat(
        routeIds: List<String>,
        stormSeverity: Double,
        solarKpIndex: Int,
        portCongestion: Double,
    ): Sourced<ThreatSimulationResponse> {
        require(routeIds.isNotEmpty()) { "Run a live route evaluation before simulation" }
        val simulations = routeIds.map { routeId ->
            ApiClient.simulateThreat(
                ThreatSimulationRequestDto(routeId, stormSeverity, solarKpIndex, portCongestion)
            )
        }
        val originalScore = simulations.minOf { it.originalScore }
        val simulatedScore = simulations.minOf { it.simulatedScore }
        return Sourced(
            data = ThreatSimulationResponse(
                originalScore = originalScore,
                simulatedScore = simulatedScore,
                degradationPct = if (originalScore == 0) 0.0
                    else ((originalScore - simulatedScore).coerceAtLeast(0) * 100.0 / originalScore),
                alerts = simulations.flatMap { it.alerts }.distinct(),
            ),
            computedOffline = false,
        )
    }

    suspend fun fetchRouteReview(
        height: Double,
        width: Double,
        weight: Double,
        sourceCode: String,
        destCode: String,
        trainArrivalHours: Double,
        portId: String,
        vesselId: String,
        stops: List<String> = emptyList(),
        loadingWindow: LoadingWindowDto? = null,
    ): Sourced<List<AlternateRoute>> {
        val evaluated = evaluateRoute(
            height = height,
            width = width,
            weight = weight,
            sourceCode = sourceCode,
            destCode = destCode,
            trainArrivalHours = trainArrivalHours,
            portId = portId,
            vesselId = vesselId,
            stops = stops,
            loadingWindow = loadingWindow,
        ).data
        val coords = evaluated.segments.flatMap { it.coordinates }
        val midpoint = if (coords.isEmpty()) emptyList() else listOf(
            coords.map { it[0] }.average(), coords.map { it[1] }.average(),
        )
        val route = AlternateRoute(
            id = evaluated.routeId,
            routeIds = evaluated.routeIds,
            label = (listOf(sourceCode) + stops + destCode).joinToString(" → "),
            segments = evaluated.segments,
            reliabilityScore = evaluated.reliabilityScore,
            weatherScore = evaluated.scoreBreakdown?.weather?.toInt(),
            estimatedHours = evaluated.estimatedHours,
            status = evaluated.status,
            decisionState = evaluated.decisionState,
            stationCodes = listOf(sourceCode) + stops + destCode,
            midpoint = midpoint,
            scoreBreakdown = evaluated.scoreBreakdown,
            blockingSegmentId = evaluated.blockingSegmentId,
            provenanceSummary = evaluated.provenanceSummary,
        )
        return Sourced(data = listOf(route), computedOffline = false)
    }

    suspend fun fetchWeatherForRoute(lat: Double, lon: Double): WeatherCondition? =
        WeatherService.fetchWeather(lat, lon)

    private fun RouteEvaluateResponseDto.toDomain() = RouteEvaluateResponse(
        routeId = routeId,
        routeIds = listOf(routeId),
        status = status,
        decisionState = decisionState,
        reliabilityScore = reliabilityScore,
        blockingSegmentId = blockingSegmentId,
        estimatedHours = estimatedHours,
        scoreBreakdown = scoreBreakdown?.toDomain(),
        segments = segments.map { SegmentPath(it.id, it.status, it.coordinates) },
        environmentalAlerts = environmentalAlerts,
        provenanceSummary = provenanceSummary?.let {
            ProvenanceSummary(
                decisionRecordId = it.decisionRecordId,
                tracedInputs = it.traceability.traced,
                totalInputs = it.traceability.total,
                coveragePct = it.traceability.coveragePct,
                warnings = it.warnings,
            )
        },
        decisionSource = "REMOTE_BACKEND",
    )

    private fun ScoreBreakdownDto.toDomain() =
        ScoreBreakdown(weather = weather, port = port, congestion = congestion, historical = historical)

}

internal fun strictestDecisionState(states: List<String>): String {
    val rank = mapOf("READY" to 0, "HOLD" to 1, "UNAVAILABLE" to 2, "HARD_BLOCKED" to 3)
    if (states.isEmpty() || states.any { it !in rank }) return "UNAVAILABLE"
    return states.maxBy { rank.getValue(it) }
}

internal fun aggregateRouteLegs(legs: List<RouteEvaluateResponse>): RouteEvaluateResponse {
    require(legs.isNotEmpty()) { "A route needs at least one evaluated leg" }
    val final = legs.last()
    val evidence = legs.mapNotNull { it.provenanceSummary }
    val breakdowns = legs.mapNotNull { it.scoreBreakdown }
    val tracedInputs = evidence.sumOf { it.tracedInputs }
    val totalInputs = evidence.sumOf { it.totalInputs }
    return final.copy(
        routeIds = legs.map { it.routeId },
        status = legs.firstOrNull { it.status != "APPROVED" }?.status ?: "APPROVED",
        decisionState = strictestDecisionState(legs.map { it.decisionState }),
        reliabilityScore = legs.minOf { it.reliabilityScore },
        blockingSegmentId = legs.firstNotNullOfOrNull { it.blockingSegmentId },
        estimatedHours = legs.mapNotNull { it.estimatedHours }.takeIf { it.size == legs.size }?.sum(),
        scoreBreakdown = breakdowns.takeIf { it.size == legs.size }?.let { scores ->
            ScoreBreakdown(
                weather = scores.mapNotNull { it.weather }
                    .takeIf { it.size == scores.size }?.minOrNull(),
                port = scores.mapNotNull { it.port }
                    .takeIf { it.size == scores.size }?.minOrNull(),
                congestion = scores.minOf { it.congestion },
                historical = scores.minOf { it.historical },
            )
        },
        segments = legs.flatMap { it.segments }.distinctBy { it.id },
        environmentalAlerts = legs.flatMap { it.environmentalAlerts }.distinct(),
        provenanceSummary = evidence.lastOrNull()?.copy(
            tracedInputs = tracedInputs,
            totalInputs = totalInputs,
            coveragePct = if (totalInputs == 0) 0.0 else tracedInputs * 100.0 / totalInputs,
            warnings = evidence.flatMap { it.warnings }.distinct(),
        ),
    )
}

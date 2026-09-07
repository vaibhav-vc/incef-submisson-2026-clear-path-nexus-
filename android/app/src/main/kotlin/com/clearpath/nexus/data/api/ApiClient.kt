package com.clearpath.nexus.data.api

import com.clearpath.nexus.BuildConfig
import io.github.jan.supabase.auth.auth
import io.ktor.client.HttpClient
import io.ktor.client.call.body
import io.ktor.client.engine.android.Android
import io.ktor.client.plugins.HttpTimeout
import io.ktor.client.plugins.ResponseException
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.client.plugins.defaultRequest
import io.ktor.client.request.get
import io.ktor.client.request.header
import io.ktor.client.request.post
import io.ktor.client.request.setBody
import io.ktor.client.statement.bodyAsText
import io.ktor.http.ContentType
import io.ktor.http.HttpHeaders
import io.ktor.http.contentType
import io.ktor.serialization.kotlinx.json.json
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * Talks to the ClearPath FastAPI backend.
 *
 * Auth stays with Supabase: we lift the access token off the current session
 * and present it as a bearer token. The backend verifies it via JWKS. No
 * credentials are stored or minted here.
 */
object ApiClient {

    /** Set per build type in build.gradle.kts. Emulator host is 10.0.2.2. */
    private val baseUrl: String = BuildConfig.API_BASE_URL.trimEnd('/')

    private val json = Json {
        ignoreUnknownKeys = true   // backend may add fields; don't crash on them
        isLenient = true
        encodeDefaults = true
    }

    private val http = HttpClient(Android) {
        expectSuccess = true
        install(ContentNegotiation) { json(json) }
        install(HttpTimeout) {
            requestTimeoutMillis = 15_000
            connectTimeoutMillis = 8_000
            socketTimeoutMillis = 15_000
        }
        defaultRequest { contentType(ContentType.Application.Json) }
    }

    /** Current Supabase access token, or null when signed out. */
    private suspend fun accessToken(): String? =
        runCatching { SupabaseClient.client.auth.currentSessionOrNull()?.accessToken }.getOrNull()

    private suspend fun requireToken(): String =
        accessToken() ?: throw NotAuthenticatedException()

    suspend fun getStations(): List<StationDto> =
        http.get("$baseUrl/planner/stations") {
            header(HttpHeaders.Authorization, "Bearer ${requireToken()}")
        }.body()

    suspend fun evaluateRoute(request: RouteEvaluateRequestDto): RouteEvaluateResponseDto =
        http.post("$baseUrl/planner/evaluate") {
            header(HttpHeaders.Authorization, "Bearer ${requireToken()}")
            setBody(request)
        }.body()

    suspend fun suggestRoute(request: RouteSuggestRequestDto): RouteSuggestResponseDto =
        http.post("$baseUrl/planner/suggest") {
            header(HttpHeaders.Authorization, "Bearer ${requireToken()}")
            setBody(request)
        }.body()

    suspend fun simulateThreat(request: ThreatSimulationRequestDto): ThreatSimulationResponseDto =
        http.post("$baseUrl/planner/simulate") {
            header(HttpHeaders.Authorization, "Bearer ${requireToken()}")
            setBody(request)
        }.body()

    suspend fun getRouteHistory(): List<RouteHistoryDto> =
        http.get("$baseUrl/planner/routes") {
            header(HttpHeaders.Authorization, "Bearer ${requireToken()}")
        }.body()

    suspend fun approveRoute(routeId: String): RouteApprovalDto =
        http.post("$baseUrl/planner/routes/$routeId/approve") {
            header(HttpHeaders.Authorization, "Bearer ${requireToken()}")
        }.body()

    suspend fun dispatchRoute(routeId: String): RouteDispatchDto =
        http.post("$baseUrl/planner/routes/$routeId/dispatch") {
            header(HttpHeaders.Authorization, "Bearer ${requireToken()}")
        }.body()

    suspend fun dispatchJourney(routeIds: List<String>): JourneyDispatchDto =
        http.post("$baseUrl/planner/routes/dispatch-journey") {
            header(HttpHeaders.Authorization, "Bearer ${requireToken()}")
            setBody(JourneyDispatchRequestDto(routeIds))
        }.body()

    suspend fun approveThenDispatchJourney(routeIds: List<String>): JourneyDispatchDto {
        val uniqueRouteIds = routeIds.distinct()
        if (uniqueRouteIds.isEmpty() || uniqueRouteIds.size != routeIds.size) {
            throw DispatchWorkflowException("Dispatch requires a non-empty journey with unique legs.")
        }

        fun requireHotKit(routeId: String, kit: RouteEvidenceKitDto) {
            val ready = kit.decisionState == "READY" &&
                kit.kitStatus == "HOT" &&
                kit.integrity.verified &&
                kit.integrity.checksumFailures.isEmpty()
            if (!ready) {
                throw DispatchWorkflowException(
                    "Journey dispatch blocked at $routeId: ${kit.decisionState} / ${kit.kitStatus} evidence.",
                )
            }
        }

        try {
            uniqueRouteIds.forEach { routeId -> requireHotKit(routeId, getEvidenceKit(routeId)) }
            uniqueRouteIds.forEach { routeId -> approveRoute(routeId) }
            uniqueRouteIds.forEach { routeId -> requireHotKit(routeId, getEvidenceKit(routeId)) }
        } catch (error: DispatchWorkflowException) {
            throw error
        } catch (error: Exception) {
            throw DispatchWorkflowException(
                "Journey approval failed; no journey dispatch was attempted. ${failureDetail(error)}",
                error,
            )
        }

        return try {
            dispatchJourney(uniqueRouteIds)
        } catch (error: Exception) {
            throw DispatchWorkflowException(
                "Atomic journey dispatch was refused; no leg was dispatched. ${failureDetail(error)}",
                error,
            )
        }
    }

    /**
     * A dispatch can never be attempted unless the backend first binds the
     * current operator and current signed evidence root into an approval
     * receipt. The backend rechecks that receipt during dispatch, closing the
     * evidence-change race between these two calls.
     */
    suspend fun approveThenDispatchRoute(routeId: String): RouteDispatchDto {
        try {
            approveRoute(routeId)
        } catch (error: Exception) {
            throw DispatchWorkflowException(
                "Approval failed; route was not dispatched. ${failureDetail(error)}",
                error,
            )
        }

        return try {
            dispatchRoute(routeId)
        } catch (error: Exception) {
            throw DispatchWorkflowException(
                "Approval was recorded, but dispatch was refused. Refresh evidence and retry. ${failureDetail(error)}",
                error,
            )
        }
    }

    suspend fun getEvidenceKit(routeId: String): RouteEvidenceKitDto =
        http.get("$baseUrl/provenance/routes/$routeId/evidence-kit") {
            header(HttpHeaders.Authorization, "Bearer ${requireToken()}")
        }.body()

    suspend fun getSchedules(): List<TrainScheduleDto> =
        http.get("$baseUrl/planner/schedules") {
            header(HttpHeaders.Authorization, "Bearer ${requireToken()}")
        }.body()

    suspend fun dispatchSchedule(scheduleId: String): TrainScheduleDto =
        http.post("$baseUrl/planner/schedules/$scheduleId/dispatch") {
            header(HttpHeaders.Authorization, "Bearer ${requireToken()}")
        }.body()

    suspend fun approveThenDispatchSchedule(
        scheduleId: String,
        routeId: String?,
    ): TrainScheduleDto {
        val linkedRouteId = routeId?.takeIf { it.isNotBlank() }
            ?: throw DispatchWorkflowException(
                "Dispatch blocked: this schedule has no linked evaluated route.",
            )
        try {
            approveRoute(linkedRouteId)
        } catch (error: Exception) {
            throw DispatchWorkflowException(
                "Approval failed; schedule was not dispatched. ${failureDetail(error)}",
                error,
            )
        }

        return try {
            dispatchSchedule(scheduleId)
        } catch (error: Exception) {
            throw DispatchWorkflowException(
                "Approval was recorded, but schedule dispatch was refused. Refresh evidence and retry. ${failureDetail(error)}",
                error,
            )
        }
    }

    private suspend fun failureDetail(error: Exception): String {
        if (error is NotAuthenticatedException) return error.message.orEmpty()
        val responseError = error as? ResponseException
            ?: return error.message?.takeIf { it.isNotBlank() } ?: "Backend request failed."
        val backendDetail = try {
            val payload = responseError.response.bodyAsText()
            json.parseToJsonElement(payload).jsonObject["detail"]?.jsonPrimitive?.content
        } catch (_: Exception) {
            null
        }
        return buildString {
            append("HTTP ${responseError.response.status.value}")
            if (!backendDetail.isNullOrBlank()) append(": $backendDetail")
        }
    }

    suspend fun portSyncStatus(
        portId: String,
        vesselId: String,
        trainArrivalHours: Double,
    ): PortSyncStatusDto =
        http.get(
            "$baseUrl/port/sync-status" +
                "?port_id=$portId&vessel_id=$vesselId&train_arrival_hours=$trainArrivalHours"
        ) {
            header(HttpHeaders.Authorization, "Bearer ${requireToken()}")
        }.body()
}

/** Thrown when a backend call is attempted with no Supabase session. */
class NotAuthenticatedException : IllegalStateException("No active Supabase session")

class DispatchWorkflowException(
    message: String,
    cause: Throwable? = null,
) : IllegalStateException(message, cause)

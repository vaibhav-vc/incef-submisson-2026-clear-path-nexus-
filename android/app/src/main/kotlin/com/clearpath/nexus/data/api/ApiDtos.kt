package com.clearpath.nexus.data.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Wire format for the FastAPI backend.
 *
 * Kept separate from the domain models in data/model/Models.kt so that a
 * backend field rename cannot ripple into the UI layer. Map at the repository
 * boundary.
 */

@Serializable
data class CargoDto(
    val height: Double,
    val width: Double,
    val weight: Double,
)

@Serializable
data class LoadingWindowDto(
    @SerialName("start_time") val startTime: String,
    @SerialName("end_time") val endTime: String,
    @SerialName("manifest_reference") val manifestReference: String,
    @SerialName("manifest_sha256") val manifestSha256: String,
)

@Serializable
data class RouteEvaluateRequestDto(
    val cargo: CargoDto,
    @SerialName("source_code") val sourceCode: String,
    @SerialName("dest_code") val destCode: String,
    @SerialName("port_id") val portId: String,
    @SerialName("vessel_id") val vesselId: String,
    @SerialName("train_arrival_hours") val trainArrivalHours: Double,
    // Optional: when the operator has the manifest, port alignment is scored.
    @SerialName("loading_window") val loadingWindow: LoadingWindowDto? = null,
)

@Serializable
data class TrainLocationDto(
    val mode: String,
    @SerialName("station_code") val stationCode: String? = null,
    val lat: Double? = null,
    val lon: Double? = null,
)

@Serializable
data class RouteSuggestRequestDto(
    val cargo: CargoDto,
    @SerialName("destination_code") val destinationCode: String,
    val location: TrainLocationDto,
    @SerialName("port_id") val portId: String,
    @SerialName("vessel_id") val vesselId: String,
    @SerialName("train_arrival_hours") val trainArrivalHours: Double,
    @SerialName("loading_window") val loadingWindow: LoadingWindowDto? = null,
)

@Serializable
data class StationDto(
    val id: String,
    val name: String,
    val code: String,
    val lat: Double,
    val lon: Double,
)

@Serializable
data class ScoreBreakdownDto(
    val weather: Double?,
    val port: Double?,
    val congestion: Double,
    val historical: Double,
    @SerialName("port_data_source") val portDataSource: String = "UNAVAILABLE",
    @SerialName("port_counted") val portCounted: Boolean = false,
    @SerialName("applied_weights") val appliedWeights: Map<String, Double> = emptyMap(),
)

@Serializable
data class SegmentPathDto(
    val id: String,
    val status: String,
    val coordinates: List<List<Double>>,
    val phase: String? = null,
    val label: String? = null,
)

@Serializable
data class TraceabilityCountsDto(
    val traced: Int,
    val total: Int,
    @SerialName("coverage_pct") val coveragePct: Double,
)

@Serializable
data class ProvenanceSummaryDto(
    @SerialName("decision_record_id") val decisionRecordId: String,
    val traceability: TraceabilityCountsDto,
    val warnings: List<String> = emptyList(),
)

@Serializable
data class RouteEvaluateResponseDto(
    @SerialName("route_id") val routeId: String,
    val status: String,
    @SerialName("decision_state") val decisionState: String,
    @SerialName("reliability_score") val reliabilityScore: Int,
    @SerialName("blocking_segment_id") val blockingSegmentId: String? = null,
    @SerialName("estimated_hours") val estimatedHours: Double? = null,
    @SerialName("score_breakdown") val scoreBreakdown: ScoreBreakdownDto? = null,
    val segments: List<SegmentPathDto> = emptyList(),
    @SerialName("environmental_alerts") val environmentalAlerts: List<String> = emptyList(),
    @SerialName("provenance_summary") val provenanceSummary: ProvenanceSummaryDto? = null,
)

@Serializable
data class AlternateRouteDto(
    val label: String,
    @SerialName("reliability_score") val reliabilityScore: Int,
    @SerialName("segment_ids") val segmentIds: List<String> = emptyList(),
    @SerialName("estimated_hours") val estimatedHours: Double? = null,
    @SerialName("weather_score") val weatherScore: Double? = null,
)

@Serializable
data class TrainPositionDto(
    val lat: Double,
    val lon: Double,
    val mode: String,
    @SerialName("snapped_track") val snappedTrack: String? = null,
    @SerialName("offset_km") val offsetKm: Double? = null,
    @SerialName("station_code") val stationCode: String? = null,
)

@Serializable
data class RouteSuggestResponseDto(
    @SerialName("route_id") val routeId: String,
    val status: String,
    @SerialName("decision_state") val decisionState: String,
    @SerialName("reliability_score") val reliabilityScore: Int,
    @SerialName("blocking_segment_id") val blockingSegmentId: String? = null,
    @SerialName("estimated_hours") val estimatedHours: Double? = null,
    @SerialName("score_breakdown") val scoreBreakdown: ScoreBreakdownDto? = null,
    val segments: List<SegmentPathDto> = emptyList(),
    @SerialName("environmental_alerts") val environmentalAlerts: List<String> = emptyList(),
    @SerialName("provenance_summary") val provenanceSummary: ProvenanceSummaryDto? = null,
    @SerialName("train_position") val trainPosition: TrainPositionDto? = null,
    @SerialName("remaining_km") val remainingKm: Double = 0.0,
    @SerialName("eta_hours") val etaHours: Double? = null,
    @SerialName("alternate_routes") val alternateRoutes: List<AlternateRouteDto> = emptyList(),
    @SerialName("next_station") val nextStation: String? = null,
)

@Serializable
data class ThreatSimulationRequestDto(
    @SerialName("route_id") val routeId: String,
    @SerialName("storm_severity") val stormSeverity: Double = 0.0,
    @SerialName("solar_kp_index") val solarKpIndex: Int = 0,
    @SerialName("port_congestion") val portCongestion: Double = 0.0,
)

@Serializable
data class ThreatSimulationResponseDto(
    @SerialName("original_score") val originalScore: Int,
    @SerialName("simulated_score") val simulatedScore: Int,
    @SerialName("degradation_pct") val degradationPct: Double,
    val alerts: List<String> = emptyList(),
)

@Serializable
data class PortSyncStatusDto(
    val aligned: Boolean,
    @SerialName("data_source") val dataSource: String,
    @SerialName("data_available") val dataAvailable: Boolean,
    @SerialName("berth_id") val berthId: String? = null,
    @SerialName("vessel_status") val vesselStatus: String? = null,
    @SerialName("sync_score") val syncScore: Double? = null,
    val warning: String? = null,
)

@Serializable
data class RouteHistoryDto(
    val id: String,
    @SerialName("source_station_code") val sourceStationCode: String,
    @SerialName("dest_station_code") val destStationCode: String,
    @SerialName("cargo_height_requested") val cargoHeightRequested: Double,
    @SerialName("cargo_width_requested") val cargoWidthRequested: Double,
    @SerialName("cargo_weight_requested") val cargoWeightRequested: Double,
    val status: String,
    @SerialName("dispatch_status") val dispatchStatus: String,
    @SerialName("reliability_score") val reliabilityScore: Int,
    @SerialName("estimated_hours") val estimatedHours: Double? = null,
    @SerialName("dispatched_at") val dispatchedAt: String? = null,
    @SerialName("created_at") val createdAt: String,
)

@Serializable
data class RouteDispatchDto(
    @SerialName("route_id") val routeId: String,
    @SerialName("dispatch_status") val dispatchStatus: String,
    @SerialName("dispatched_at") val dispatchedAt: String,
)

@Serializable
data class JourneyDispatchRequestDto(
    @SerialName("route_ids") val routeIds: List<String>,
)

@Serializable
data class JourneyDispatchDto(
    @SerialName("dispatch_status") val dispatchStatus: String,
    @SerialName("dispatched_at") val dispatchedAt: String,
    val routes: List<RouteDispatchDto>,
)

@Serializable
data class RouteApprovalDto(
    @SerialName("route_id") val routeId: String,
    @SerialName("approval_status") val approvalStatus: String,
    @SerialName("approved_by_user_id") val approvedByUserId: String,
    @SerialName("approved_by_role") val approvedByRole: String,
    @SerialName("approved_at") val approvedAt: String,
    @SerialName("evidence_root_checksum") val evidenceRootChecksum: String,
)

@Serializable
data class EvidenceKitIntegrityDto(
    val verified: Boolean,
    @SerialName("record_count") val recordCount: Int,
    @SerialName("checksum_failures") val checksumFailures: List<String> = emptyList(),
)

@Serializable
data class RouteEvidenceKitDto(
    @SerialName("generated_at") val generatedAt: String,
    @SerialName("format_version") val formatVersion: String,
    @SerialName("kit_status") val kitStatus: String,
    @SerialName("decision_state") val decisionState: String,
    @SerialName("reason_codes") val reasonCodes: List<String> = emptyList(),
    @SerialName("manifest_checksum") val manifestChecksum: String,
    val integrity: EvidenceKitIntegrityDto,
    val limitations: List<String> = emptyList(),
)

@Serializable
data class TrainScheduleDto(
    val id: String,
    @SerialName("generated_route_id") val generatedRouteId: String? = null,
    @SerialName("train_code") val trainCode: String,
    @SerialName("train_name") val trainName: String,
    @SerialName("source_station_code") val sourceStationCode: String,
    @SerialName("dest_station_code") val destStationCode: String,
    @SerialName("scheduled_departure") val scheduledDeparture: String,
    @SerialName("scheduled_arrival") val scheduledArrival: String,
    @SerialName("berth_window_start") val berthWindowStart: String? = null,
    @SerialName("berth_window_end") val berthWindowEnd: String? = null,
    @SerialName("schedule_status") val scheduleStatus: String,
    @SerialName("conflict_status") val conflictStatus: String,
    @SerialName("conflict_reason") val conflictReason: String? = null,
    @SerialName("is_demo") val isDemo: Boolean = false,
    @SerialName("dispatched_at") val dispatchedAt: String? = null,
    @SerialName("created_at") val createdAt: String,
    @SerialName("updated_at") val updatedAt: String,
)

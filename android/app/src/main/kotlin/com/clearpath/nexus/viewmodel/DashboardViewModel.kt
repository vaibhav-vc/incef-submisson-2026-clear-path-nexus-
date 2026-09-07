package com.clearpath.nexus.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.clearpath.nexus.data.api.ApiClient
import com.clearpath.nexus.data.api.LoadingWindowDto
import com.clearpath.nexus.data.model.EnvironmentalZone
import com.clearpath.nexus.data.model.RouteEvaluateResponse
import com.clearpath.nexus.data.model.LoadProfile
import com.clearpath.nexus.data.model.ScoreBreakdown
import com.clearpath.nexus.data.model.Station
import com.clearpath.nexus.data.repository.NexusRepository
import kotlinx.serialization.encodeToString
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Locale
import java.util.TimeZone

data class DashboardUiState(
    val stations: List<Station> = emptyList(),
    val height: String = "",
    val width: String = "",
    val weight: String = "",
    val sourceCode: String = "",
    val destCode: String = "",
    val trainHours: String = "",
    val portId: String = "",
    val vesselId: String = "",
    val useBerthWindow: Boolean = false,
    val berthStartHours: String = "",
    val berthEndHours: String = "",
    val manifestReference: String = "",
    val manifestSha256: String = "",
    val isLoading: Boolean = false,
    val error: String? = null,
    val result: RouteEvaluateResponse? = null,
    val stormSeverity: Float = 0f,
    val solarKp: Float = 2f,
    val portCongestion: Float = 0f,
    val simLoading: Boolean = false,
    val simulatedScore: Int? = null,
    val simAlerts: List<String> = emptyList(),
    val selectedTab: DashboardTab = DashboardTab.CONFIGURE,
    val confirmedRouteLabel: String? = null,
    val confirmedRouteId: String? = null,
    val alternateRoutes: List<com.clearpath.nexus.data.model.AlternateRoute> = emptyList(),
    val stops: List<String> = emptyList(),
    val environmentalZones: List<EnvironmentalZone> = emptyList(),
    val isSimulationMode: Boolean = false,
    val estimatedTotalHours: Float? = null,
    val loadProfiles: List<LoadProfile> = emptyList(),
    val selectedProfileId: String? = null,
    val evaluatedLoadingWindow: LoadingWindowDto? = null,
    val journeyDispatching: Boolean = false,
    val journeyDispatchedAt: String? = null,
)

enum class DashboardTab {
    CONFIGURE,
    ROUTE_SELECTION,
    MAP,
    TELEMETRY,
    SCHEDULE,
    HISTORY,
    LOADS,
    USER,
}

class DashboardViewModel(
    private val repository: NexusRepository = NexusRepository(),
) : ViewModel() {

    private val _uiState = MutableStateFlow(DashboardUiState())
    val uiState: StateFlow<DashboardUiState> = _uiState.asStateFlow()

    init {
        loadStations()
    }

    fun onHeightChange(value: String) = _uiState.update { it.copy(height = value) }
    fun onWidthChange(value: String) = _uiState.update { it.copy(width = value) }
    fun onWeightChange(value: String) = _uiState.update { it.copy(weight = value) }
    fun onSourceChange(value: String) = _uiState.update { it.copy(sourceCode = value) }
    fun onDestChange(value: String) = _uiState.update { it.copy(destCode = value) }
    fun onTrainHoursChange(value: String) = _uiState.update { it.copy(trainHours = value) }
    fun onPortIdChange(value: String) = _uiState.update { it.copy(portId = value) }
    fun onVesselIdChange(value: String) = _uiState.update { it.copy(vesselId = value) }
    fun onUseBerthWindowChange(value: Boolean) = _uiState.update { it.copy(useBerthWindow = value) }
    fun onBerthStartHoursChange(value: String) = _uiState.update { it.copy(berthStartHours = value) }
    fun onBerthEndHoursChange(value: String) = _uiState.update { it.copy(berthEndHours = value) }
    fun onManifestReferenceChange(value: String) = _uiState.update { it.copy(manifestReference = value) }
    fun onManifestSha256Change(value: String) = _uiState.update { it.copy(manifestSha256 = value) }
    fun onStormChange(value: Float) = _uiState.update { it.copy(stormSeverity = value) }
    fun onSolarChange(value: Float) = _uiState.update { it.copy(solarKp = value) }
    fun onPortChange(value: Float) = _uiState.update { it.copy(portCongestion = value) }
    fun onTabSelected(tab: DashboardTab) = _uiState.update { it.copy(selectedTab = tab) }
    fun onStopsChange(value: List<String>) = _uiState.update { it.copy(stops = value) }

    private fun loadStations() {
        viewModelScope.launch {
            try {
                val stations = repository.fetchStations().data
                _uiState.update {
                    it.copy(
                        stations = stations,
                        sourceCode = it.sourceCode.ifBlank { stations.firstOrNull()?.code.orEmpty() },
                        destCode = it.destCode.ifBlank { stations.getOrNull(1)?.code.orEmpty() },
                        error = null,
                    )
                }
            } catch (e: Exception) {
                _uiState.update { it.copy(error = e.message ?: "Live station data unavailable") }
            }
        }
    }

    fun evaluateRoute() {
        val state = _uiState.value
        val height = state.height.toDoubleOrNull()
        val width = state.width.toDoubleOrNull()
        val weight = state.weight.toDoubleOrNull()
        val trainHours = state.trainHours.toDoubleOrNull()
        val berthStartHours = state.berthStartHours.toDoubleOrNull()
        val berthEndHours = state.berthEndHours.toDoubleOrNull()

        val stationChain = listOf(state.sourceCode) + state.stops + state.destCode
        if (height == null || width == null || weight == null || trainHours == null ||
            height <= 0 || width <= 0 || weight <= 0 || trainHours <= 0 ||
            state.portId.isBlank() || state.vesselId.isBlank() ||
            stationChain.any { it.isBlank() } || stationChain.zipWithNext().any { it.first == it.second } ||
            (state.useBerthWindow && (
                berthStartHours == null || berthEndHours == null || berthEndHours <= berthStartHours ||
                    state.manifestReference.trim().length < 3 ||
                    !state.manifestSha256.trim().matches(Regex("^[A-Fa-f0-9]{64}$"))
                ))
        ) {
            _uiState.update {
                it.copy(error = "Enter valid cargo, stations, arrival/port/vessel data, and manifest reference plus SHA-256 for an operator berth window.")
            }
            return
        }

        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            try {
                val loadingWindow = if (state.useBerthWindow && berthStartHours != null && berthEndHours != null) {
                    LoadingWindowDto(
                        startTime = isoHoursFromNow(berthStartHours),
                        endTime = isoHoursFromNow(berthEndHours),
                        manifestReference = state.manifestReference.trim(),
                        manifestSha256 = state.manifestSha256.trim().lowercase(),
                    )
                } else null

                val result = repository.evaluateRoute(
                    height = height,
                    width = width,
                    weight = weight,
                    sourceCode = state.sourceCode,
                    destCode = state.destCode,
                    trainArrivalHours = trainHours,
                    portId = state.portId.trim(),
                    vesselId = state.vesselId.trim(),
                    stops = state.stops,
                    loadingWindow = loadingWindow,
                ).data

                _uiState.update {
                    it.copy(
                        isLoading = false,
                        result = result,
                        evaluatedLoadingWindow = loadingWindow,
                        journeyDispatchedAt = null,
                        journeyDispatching = false,
                        simulatedScore = null,
                        simAlerts = emptyList(),
                        selectedTab = DashboardTab.ROUTE_SELECTION,
                    )
                }
            } catch (e: IllegalArgumentException) {
                _uiState.update {
                    it.copy(isLoading = false, error = e.message)
                }
            } catch (e: Exception) {
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        error = e.message ?: "Route evaluation failed. Please try again.",
                    )
                }
            }
        }
    }

    fun simulateThreat() {
        val state = _uiState.value
        val routeIds = state.result?.routeIds.orEmpty()
        if (routeIds.isEmpty()) {
            _uiState.update { it.copy(error = "Run a live route evaluation before applying a what-if scenario.") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(simLoading = true) }
            try {
                val response = repository.simulateThreat(
                    routeIds = routeIds,
                    stormSeverity = state.stormSeverity.toDouble(),
                    solarKpIndex = state.solarKp.toInt(),
                    portCongestion = state.portCongestion.toDouble(),
                ).data
                _uiState.update {
                    it.copy(
                        simLoading = false,
                        simulatedScore = response.simulatedScore,
                        simAlerts = response.alerts,
                    )
                }
            } catch (e: Exception) {
                _uiState.update { it.copy(simLoading = false, error = e.message ?: "Simulation unavailable") }
            }
        }
    }

    fun calculateEstimatedTime() {
        val state = _uiState.value
        _uiState.update { it.copy(estimatedTotalHours = state.result?.estimatedHours?.toFloat()) }
    }

    fun onRouteConfirmed(
        route: com.clearpath.nexus.data.model.AlternateRoute,
        allRoutes: List<com.clearpath.nexus.data.model.AlternateRoute>
    ) {
        val state = _uiState.value
        _uiState.update {
            it.copy(
                result = RouteEvaluateResponse(
                    routeId = route.id,
                    routeIds = route.routeIds,
                    status = route.status,
                    decisionState = route.decisionState,
                    reliabilityScore = route.reliabilityScore,
                    blockingSegmentId = route.blockingSegmentId,
                    estimatedHours = route.estimatedHours,
                    scoreBreakdown = route.scoreBreakdown,
                    segments = route.segments,
                    provenanceSummary = route.provenanceSummary,
                    decisionSource = route.decisionSource,
                ),
                confirmedRouteLabel = route.label,
                confirmedRouteId = route.id,
                alternateRoutes = allRoutes,
                journeyDispatchedAt = null,
                journeyDispatching = false,
                selectedTab = DashboardTab.MAP,
            )
        }
        // Update estimated total hours after confirming route
        calculateEstimatedTime()

    }

    fun dispatchCurrentJourney() {
        val state = _uiState.value
        val routeIds = state.result?.routeIds.orEmpty()
        if (state.result?.decisionState != "READY" || state.result.status != "APPROVED" || routeIds.isEmpty()) {
            _uiState.update { it.copy(error = "Dispatch requires a current APPROVED journey with READY evidence.") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(journeyDispatching = true, error = null) }
            try {
                val receipt = ApiClient.approveThenDispatchJourney(routeIds)
                _uiState.update {
                    it.copy(
                        journeyDispatching = false,
                        journeyDispatchedAt = receipt.dispatchedAt,
                    )
                }
            } catch (e: Exception) {
                _uiState.update {
                    it.copy(
                        journeyDispatching = false,
                        error = e.message ?: "Atomic journey dispatch failed closed.",
                    )
                }
            }
        }
    }

    fun onBackFromRouteSelection() {
        _uiState.update { it.copy(selectedTab = DashboardTab.CONFIGURE) }
    }

    fun loadSavedProfiles(context: android.content.Context) {
        val sharedPrefs = context.getSharedPreferences("clearpath_prefs", android.content.Context.MODE_PRIVATE)
        val jsonStr = sharedPrefs.getString("load_profiles", null)
        val list = if (!jsonStr.isNullOrEmpty()) {
            try {
                kotlinx.serialization.json.Json.decodeFromString<List<LoadProfile>>(jsonStr)
            } catch (e: Exception) {
                emptyList()
            }
        } else {
            emptyList()
        }

        // Load saved inputs
        val height = sharedPrefs.getString("input_height", "") ?: ""
        val width = sharedPrefs.getString("input_width", "") ?: ""
        val weight = sharedPrefs.getString("input_weight", "") ?: ""
        val source = sharedPrefs.getString("input_source", _uiState.value.sourceCode) ?: _uiState.value.sourceCode
        val dest = sharedPrefs.getString("input_dest", _uiState.value.destCode) ?: _uiState.value.destCode
        val hours = sharedPrefs.getString("input_hours", "") ?: ""
        val portId = sharedPrefs.getString("input_port_id", "") ?: ""
        val vesselId = sharedPrefs.getString("input_vessel_id", "") ?: ""
        val profileId = sharedPrefs.getString("input_profile_id", null)
        val stopsJson = sharedPrefs.getString("input_stops", null)
        val stops = if (!stopsJson.isNullOrEmpty()) {
            try {
                kotlinx.serialization.json.Json.decodeFromString<List<String>>(stopsJson)
            } catch (e: Exception) {
                emptyList()
            }
        } else {
            emptyList()
        }

        _uiState.update {
            it.copy(
                loadProfiles = list,
                height = height,
                width = width,
                weight = weight,
                sourceCode = source,
                destCode = dest,
                trainHours = hours,
                portId = portId,
                vesselId = vesselId,
                selectedProfileId = profileId,
                stops = stops
            )
        }
    }

    fun saveCurrentInputs(
        context: android.content.Context,
        height: String,
        width: String,
        weight: String,
        source: String,
        dest: String,
        hours: String,
        portId: String,
        vesselId: String,
        stops: List<String>,
        profileId: String?
    ) {
        val sharedPrefs = context.getSharedPreferences("clearpath_prefs", android.content.Context.MODE_PRIVATE)
        try {
            val stopsJson = kotlinx.serialization.json.Json.encodeToString(stops)
            sharedPrefs.edit()
                .putString("input_height", height)
                .putString("input_width", width)
                .putString("input_weight", weight)
                .putString("input_source", source)
                .putString("input_dest", dest)
                .putString("input_hours", hours)
                .putString("input_port_id", portId)
                .putString("input_vessel_id", vesselId)
                .putString("input_stops", stopsJson)
                .putString("input_profile_id", profileId)
                .apply()
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }

    private fun saveProfilesList(context: android.content.Context, list: List<LoadProfile>) {
        val sharedPrefs = context.getSharedPreferences("clearpath_prefs", android.content.Context.MODE_PRIVATE)
        try {
            val jsonStr = kotlinx.serialization.json.Json.encodeToString(list)
            sharedPrefs.edit().putString("load_profiles", jsonStr).apply()
            _uiState.update { it.copy(loadProfiles = list) }
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }

    fun saveLoadProfile(
        context: android.content.Context,
        name: String,
        height: Double,
        width: Double,
        weight: Double,
        compartments: Int,
        purpose: String,
        notes: String
    ) {
        val current = _uiState.value.loadProfiles.toMutableList()
        val newProfile = LoadProfile(
            id = "lp-${System.currentTimeMillis()}",
            name = name,
            height = height,
            width = width,
            weight = weight,
            compartments = compartments,
            compartmentPurpose = purpose,
            notes = notes,
            createdAt = isoNow()
        )
        current.add(newProfile)
        saveProfilesList(context, current)
        selectLoadProfile(newProfile.id)
    }

    fun deleteLoadProfile(context: android.content.Context, id: String) {
        val current = _uiState.value.loadProfiles.filter { it.id != id }
        saveProfilesList(context, current)
        if (_uiState.value.selectedProfileId == id) {
            _uiState.update { it.copy(selectedProfileId = null) }
        }
    }

    fun selectLoadProfile(id: String) {
        val profile = _uiState.value.loadProfiles.find { it.id == id }
        if (profile != null) {
            _uiState.update {
                it.copy(
                    selectedProfileId = id,
                    height = profile.height.toString(),
                    width = profile.width.toString(),
                    weight = profile.weight.toString()
                )
            }
        } else {
            _uiState.update { it.copy(selectedProfileId = null) }
        }
    }
    private fun isoHoursFromNow(hours: Double): String {
        val calendar = Calendar.getInstance(TimeZone.getTimeZone("UTC"))
        calendar.timeInMillis += (hours * 60.0 * 60.0 * 1000.0).toLong()
        val format = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US)
        format.timeZone = TimeZone.getTimeZone("UTC")
        return format.format(calendar.time)
    }

    private fun isoNow(): String {
        val format = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US)
        format.timeZone = TimeZone.getTimeZone("UTC")
        return format.format(Calendar.getInstance(TimeZone.getTimeZone("UTC")).time)
    }

}


package com.clearpath.nexus.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.clearpath.nexus.data.model.AlternateRoute
import com.clearpath.nexus.data.api.LoadingWindowDto
import com.clearpath.nexus.data.repository.NexusRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class RouteSelectionUiState(
    val routes: List<AlternateRoute> = emptyList(),
    val selectedRouteId: String? = null,
    val isLoading: Boolean = true,
    val isLoadingWeather: Boolean = false,
    val weatherError: String? = null,
)

class RouteSelectionViewModel(
    private val repository: NexusRepository = NexusRepository(),
) : ViewModel() {

    private val _uiState = MutableStateFlow(RouteSelectionUiState())
    val uiState: StateFlow<RouteSelectionUiState> = _uiState.asStateFlow()

    fun loadRoutes(
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
    ) {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true) }

            try {
                val routes = repository.fetchRouteReview(
                    height, width, weight, sourceCode, destCode, trainArrivalHours,
                    portId, vesselId, stops, loadingWindow,
                ).data

                // Auto-select the first route
                val firstId = routes.firstOrNull()?.id
                _uiState.update {
                    it.copy(
                        routes = routes,
                        selectedRouteId = firstId,
                        isLoading = false,
                        isLoadingWeather = false,
                        weatherError = null,
                    )
                }
            } catch (e: Exception) {
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        isLoadingWeather = false,
                        weatherError = e.message,
                    )
                }
            }
        }
    }

    fun onRouteSelected(routeId: String) {
        _uiState.update { it.copy(selectedRouteId = routeId) }
    }

    fun getSelectedRoute(): AlternateRoute? {
        val state = _uiState.value
        return state.routes.find { it.id == state.selectedRouteId }
    }
}

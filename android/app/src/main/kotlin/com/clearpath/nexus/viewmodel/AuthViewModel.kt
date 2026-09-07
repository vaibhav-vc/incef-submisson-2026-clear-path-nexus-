package com.clearpath.nexus.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.clearpath.nexus.data.api.SupabaseClient
import io.github.jan.supabase.auth.auth
import io.github.jan.supabase.auth.providers.builtin.Email
import io.github.jan.supabase.auth.status.SessionStatus
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

data class AuthUiState(
    val email: String = "",
    val password: String = "",
    val displayName: String = "",
    val isLogin: Boolean = true,
    val isLoading: Boolean = false,
    val error: String? = null,
    val successMessage: String? = null,
    val isInitialized: Boolean = false,
    val isAuthenticated: Boolean = false,
    val userId: String? = null,
    val userEmail: String? = null
)

class AuthViewModel : ViewModel() {

    private val _uiState = MutableStateFlow(AuthUiState())
    val uiState: StateFlow<AuthUiState> = _uiState.asStateFlow()

    init {
        observeSession()
    }

    private fun observeSession() {
        viewModelScope.launch {
            try {
                SupabaseClient.client.auth.sessionStatus.collect { status ->
                    when (status) {
                        is SessionStatus.Initializing -> {
                            _uiState.update { it.copy(isLoading = true, isInitialized = false) }
                        }
                        is SessionStatus.Authenticated -> {
                            val user = status.session.user
                            _uiState.update {
                                it.copy(
                                    isLoading = false,
                                    isInitialized = true,
                                    isAuthenticated = true,
                                    userId = user?.id,
                                    userEmail = user?.email
                                )
                            }
                        }
                        is SessionStatus.NotAuthenticated -> {
                            _uiState.update {
                                it.copy(
                                    isLoading = false,
                                    isInitialized = true,
                                    isAuthenticated = false,
                                    userId = null,
                                    userEmail = null
                                )
                            }
                        }
                        is SessionStatus.RefreshFailure -> {
                            _uiState.update {
                                it.copy(
                                    isLoading = false,
                                    isInitialized = true,
                                    isAuthenticated = false,
                                    error = "Session refresh failed. Please log in again."
                                )
                            }
                        }
                    }
                }
            } catch (e: Exception) {
                _uiState.update { it.copy(error = e.localizedMessage ?: "Unknown error during session monitoring") }
            }
        }
    }

    fun onEmailChange(value: String) {
        _uiState.update { it.copy(email = value, error = null, successMessage = null) }
    }

    fun onPasswordChange(value: String) {
        _uiState.update { it.copy(password = value, error = null, successMessage = null) }
    }

    fun onDisplayNameChange(value: String) {
        _uiState.update { it.copy(displayName = value, error = null, successMessage = null) }
    }

    fun toggleMode() {
        _uiState.update { it.copy(isLogin = !it.isLogin, error = null, successMessage = null) }
    }

    fun authenticate() {
        val emailValue = _uiState.value.email.trim()
        val passwordValue = _uiState.value.password.trim()
        val isLoginMode = _uiState.value.isLogin

        if (emailValue.isEmpty() || passwordValue.isEmpty()) {
            _uiState.update { it.copy(error = "Email and password cannot be empty") }
            return
        }

        if (!isLoginMode && _uiState.value.displayName.trim().isEmpty()) {
            _uiState.update { it.copy(error = "Display name cannot be empty") }
            return
        }

        _uiState.update { it.copy(isLoading = true, error = null, successMessage = null) }

        viewModelScope.launch {
            try {
                if (isLoginMode) {
                    SupabaseClient.client.auth.signInWith(Email) {
                        email = emailValue
                        password = passwordValue
                    }
                } else {
                    val dName = _uiState.value.displayName.trim()
                    SupabaseClient.client.auth.signUpWith(Email) {
                        email = emailValue
                        password = passwordValue
                        data = buildJsonObject {
                            put("display_name", dName)
                        }
                    }
                    // Sign up succeeded! Show confirmation message and switch to login tab
                    _uiState.update {
                        it.copy(
                            isLoading = false,
                            isLogin = true,
                            successMessage = "Check your email for confirmation",
                            error = null
                        )
                    }
                }
            } catch (e: Exception) {
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        error = e.localizedMessage ?: "Authentication failed"
                    )
                }
            }
        }
    }


    fun signOut() {
        _uiState.update { it.copy(isLoading = true, error = null) }
        viewModelScope.launch {
            try {
                SupabaseClient.client.auth.signOut()
            } catch (e: Exception) {
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        error = e.localizedMessage ?: "Sign out failed"
                    )
                }
            }
        }
    }
}

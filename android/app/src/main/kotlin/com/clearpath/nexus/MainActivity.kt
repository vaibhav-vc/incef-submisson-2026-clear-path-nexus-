package com.clearpath.nexus

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.lifecycle.viewmodel.compose.viewModel
import com.clearpath.nexus.ui.screens.AuthScreen
import com.clearpath.nexus.ui.screens.CommandDashboardScreen
import com.clearpath.nexus.ui.theme.ClearPathNexusTheme
import com.clearpath.nexus.ui.theme.PanelDark
import com.clearpath.nexus.viewmodel.AuthViewModel

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            ClearPathNexusTheme {
                val authViewModel: AuthViewModel = viewModel()
                val authState by authViewModel.uiState.collectAsState()

                if (!authState.isInitialized) {
                    Box(
                        modifier = Modifier
                            .fillMaxSize()
                            .background(PanelDark),
                        contentAlignment = Alignment.Center
                    ) {
                        CircularProgressIndicator(color = Color.White)
                    }
                } else if (authState.isAuthenticated) {
                    CommandDashboardScreen(
                        onSignOut = { authViewModel.signOut() }
                    )
                } else {
                    AuthScreen(viewModel = authViewModel)
                }
            }
        }
    }
}


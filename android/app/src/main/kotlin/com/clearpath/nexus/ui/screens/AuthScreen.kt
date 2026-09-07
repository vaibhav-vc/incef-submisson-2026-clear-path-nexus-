package com.clearpath.nexus.ui.screens

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.ui.draw.clip
import androidx.compose.foundation.Image
import androidx.compose.ui.res.painterResource
import com.clearpath.nexus.R
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Email
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.clearpath.nexus.ui.theme.*
import com.clearpath.nexus.viewmodel.AuthViewModel

@Composable
fun AuthScreen(
    viewModel: AuthViewModel = viewModel(),
) {
    val state by viewModel.uiState.collectAsState()
    var passwordVisible by remember { mutableStateOf(false) }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(PanelDark)
            .padding(24.dp),
        contentAlignment = Alignment.Center
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .border(1.dp, PanelBorder, RoundedCornerShape(12.dp))
                .background(PrimaryCommandBlue.copy(alpha = 0.5f), RoundedCornerShape(12.dp))
                .padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            // Header
            Image(
                painter = painterResource(id = R.drawable.app_logo),
                contentDescription = "ClearPath Nexus Logo",
                modifier = Modifier
                    .size(80.dp)
                    .clip(CircleShape)
                    .border(2.dp, AccentSafetyBlue, CircleShape)
            )
            Spacer(modifier = Modifier.height(12.dp))
            Text(
                text = "CLEARPATH NEXUS",
                fontSize = 24.sp,
                fontWeight = FontWeight.Bold,
                color = Color.White,
                letterSpacing = 2.sp
            )
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = "Railway Intelligence Command Center",
                fontSize = 12.sp,
                fontFamily = FontFamily.Monospace,
                color = TextLight,
                textAlign = TextAlign.Center
            )
            Spacer(modifier = Modifier.height(24.dp))

            // Switch Tab Row
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(44.dp)
                    .border(1.dp, PanelBorder, RoundedCornerShape(6.dp))
                    .background(PanelDark, RoundedCornerShape(6.dp))
                    .padding(2.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxHeight()
                        .background(
                            if (state.isLogin) AccentSafetyBlue else Color.Transparent,
                            RoundedCornerShape(4.dp)
                        )
                        .clickable { if (!state.isLogin) viewModel.toggleMode() },
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = "SIGN IN",
                        fontSize = 13.sp,
                        fontWeight = FontWeight.Bold,
                        color = if (state.isLogin) Color.White else TextMuted
                    )
                }
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxHeight()
                        .background(
                            if (!state.isLogin) AccentSafetyBlue else Color.Transparent,
                            RoundedCornerShape(4.dp)
                        )
                        .clickable { if (state.isLogin) viewModel.toggleMode() },
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = "SIGN UP",
                        fontSize = 13.sp,
                        fontWeight = FontWeight.Bold,
                        color = if (!state.isLogin) Color.White else TextMuted
                    )
                }
            }

            Spacer(modifier = Modifier.height(24.dp))

            // Text Fields
            if (!state.isLogin) {
                OutlinedTextField(
                    value = state.displayName,
                    onValueChange = { viewModel.onDisplayNameChange(it) },
                    label = { Text("Display Name") },
                    leadingIcon = { Icon(Icons.Default.Person, contentDescription = null, tint = TextLight) },
                    modifier = Modifier.fillMaxWidth(),
                    colors = textFieldColors(),
                    singleLine = true
                )
                Spacer(modifier = Modifier.height(16.dp))
            }

            OutlinedTextField(
                value = state.email,
                onValueChange = { viewModel.onEmailChange(it) },
                label = { Text("Email Address") },
                leadingIcon = { Icon(Icons.Default.Email, contentDescription = null, tint = TextLight) },
                modifier = Modifier.fillMaxWidth(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
                colors = textFieldColors(),
                singleLine = true
            )
            Spacer(modifier = Modifier.height(16.dp))

            OutlinedTextField(
                value = state.password,
                onValueChange = { viewModel.onPasswordChange(it) },
                label = { Text("Password") },
                leadingIcon = { Icon(Icons.Default.Lock, contentDescription = null, tint = TextLight) },
                trailingIcon = {
                    val icon = if (passwordVisible) Icons.Default.Visibility else Icons.Default.VisibilityOff
                    IconButton(onClick = { passwordVisible = !passwordVisible }) {
                        Icon(icon, contentDescription = null, tint = TextLight)
                    }
                },
                modifier = Modifier.fillMaxWidth(),
                visualTransformation = if (passwordVisible) VisualTransformation.None else PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                colors = textFieldColors(),
                singleLine = true
            )

            Spacer(modifier = Modifier.height(24.dp))

            // Error Message
            AnimatedVisibility(visible = state.error != null) {
                state.error?.let { err ->
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .border(1.dp, StatusBlockedRed, RoundedCornerShape(4.dp))
                            .background(StatusBlockedRed.copy(alpha = 0.1f))
                            .padding(12.dp)
                    ) {
                        Text(
                            text = err,
                            color = StatusBlockedRed,
                            fontSize = 12.sp,
                            fontFamily = FontFamily.Monospace
                        )
                    }
                }
            }

            // Success Message
            AnimatedVisibility(visible = state.successMessage != null) {
                state.successMessage?.let { msg ->
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .border(1.dp, StatusApprovedGreen, RoundedCornerShape(4.dp))
                            .background(StatusApprovedGreen.copy(alpha = 0.1f))
                            .padding(12.dp)
                    ) {
                        Text(
                            text = msg,
                            color = StatusApprovedGreen,
                            fontSize = 12.sp,
                            fontFamily = FontFamily.Monospace
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(16.dp))

            // Action Button
            Button(
                onClick = { viewModel.authenticate() },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(54.dp),
                shape = RoundedCornerShape(6.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = AccentSafetyBlue,
                    contentColor = Color.White
                ),
                enabled = !state.isLoading
            ) {
                if (state.isLoading) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(24.dp),
                        color = Color.White,
                        strokeWidth = 2.dp
                    )
                } else {
                    Text(
                        text = if (state.isLogin) "INITIALIZE ACCESS" else "CREATE COMMAND ACCOUNT",
                        fontWeight = FontWeight.Bold,
                        fontSize = 13.sp,
                        letterSpacing = 1.sp,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }
            }
        }
    }
}

@Composable
private fun textFieldColors() = OutlinedTextFieldDefaults.colors(
    focusedBorderColor = AccentSafetyBlue,
    unfocusedBorderColor = PanelBorder,
    focusedLabelColor = AccentSafetyBlue,
    unfocusedLabelColor = TextMuted,
    focusedTextColor = Color.White,
    unfocusedTextColor = Color.White,
    cursorColor = AccentSafetyBlue,
    focusedContainerColor = PanelDark,
    unfocusedContainerColor = PanelDark
)

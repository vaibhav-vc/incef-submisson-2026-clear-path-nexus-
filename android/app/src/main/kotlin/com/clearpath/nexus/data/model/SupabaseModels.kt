package com.clearpath.nexus.data.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class ProfileRow(
    val id: String,
    @SerialName("display_name") val displayName: String?,
    @SerialName("created_at") val createdAt: String? = null
)

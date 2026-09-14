import type { CanonicalSourceType } from './status'

export type SpeedSourceType =
  | 'LIVE_PROVIDER'
  | 'AUTHORIZED_FEED'
  | 'PUBLIC_OPEN_DATA'
  | 'CACHED_PROVIDER'
  | 'OPERATOR_INPUT'
  | 'IMPORTED_DOCUMENT'
  | 'REAL_HISTORICAL'
  | 'REPLAYED_SNAPSHOT'

export type SpeedAuthorityLevel = 'AUTHORITATIVE' | 'SUPPLEMENTARY' | 'OPERATOR_DECLARED'

export type SpeedConstraintCategory =
  | 'ROUTE_LIMIT'
  | 'TEMPORARY_RESTRICTION'
  | 'TRACK_GEOMETRY'
  | 'GRADIENT'
  | 'AXLE_LOAD'
  | 'ENVIRONMENT'
  | 'HEADWAY'
  | 'BLOCK_OCCUPANCY'

export interface SpeedSourceEvidence {
  source_key: string
  source_type: SpeedSourceType
  authority_level: SpeedAuthorityLevel
  source_reference: string
  observed_at: string
  fetched_at: string
  valid_until: string
  checksum?: string | null
  provider_version?: string | null
}

export interface SpeedConstraintInput {
  category: SpeedConstraintCategory
  label: string
  limit_kph: number
  evidence: SpeedSourceEvidence
}

export interface BrakePerformanceInput {
  effective_deceleration_mps2: number
  reaction_time_seconds: number
  safety_margin_meters: number
  evidence: SpeedSourceEvidence
}

export interface SpeedRiskAdvisoryRequest {
  route_id?: string | null
  corridor_reference: string
  consist_manifest_checksum: string
  evaluation_at: string
  constraints: SpeedConstraintInput[]
  braking?: BrakePerformanceInput | null
}

export interface SpeedEvidenceSummary {
  category: string
  label: string
  limit_kph?: number | null
  source_key: string
  source_type: SpeedSourceType | string
  authority_level: SpeedAuthorityLevel | string
  source_reference: string
  observed_at: string
  fetched_at: string
  valid_until: string
  freshness: 'CURRENT' | 'EXPIRED' | 'FUTURE' | 'INVALID'
  used_in_decision: boolean
  excluded_reason?: string | null
  checksum?: string | null
}

export interface SpeedRiskAdvisoryResponse {
  status: 'ADVISORY' | 'HOLD' | 'UNAVAILABLE'
  advisory_speed_kph?: number | null
  stopping_distance_meters?: number | null
  limiting_constraint?: string | null
  corridor_reference: string
  evaluation_at: string
  consist_manifest_checksum: string
  evidence: SpeedEvidenceSummary[]
  warnings: string[]
  disclaimer: string
}

// Keep this import-compatible with the rest of the app's source vocabulary.
// It is intentionally not used to widen the request payload: the speed API
// rejects simulated and offline-computed source types at the schema boundary.
export type SpeedCanonicalSourceType = CanonicalSourceType

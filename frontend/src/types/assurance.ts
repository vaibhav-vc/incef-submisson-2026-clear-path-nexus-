export type AssuranceState = 'REVIEWABLE' | 'HOLD' | 'UNAVAILABLE'
export type AssuranceCaseStatus = 'OPEN' | 'ASSESSED' | 'REVIEWED' | 'ARCHIVED'
export type AssuranceMatrixStatus = 'PASS' | 'WARNING' | 'FAIL' | 'MISSING'

export interface AssuranceCaseCreate {
  assigned_reviewer_id?: string | null
  title: string
  purpose: string
  subject_type: string
  subject_key: string
  context: Record<string, unknown>
  required_roles: string[]
  policy_key: string
}

export interface AssuranceCase {
  assigned_reviewer_id?: string | null
  id: string
  user_id: string
  title: string
  purpose: string
  subject_type: string
  subject_key: string
  context: Record<string, unknown>
  required_roles: string[]
  policy_key: string
  policy_version: string
  status: AssuranceCaseStatus
  created_at: string
  updated_at: string
}

export interface AssuranceEvidence {
  id: string
  case_id: string
  source_id: string
  source_key: string
  source_name: string
  source_url?: string | null
  license_name?: string | null
  /** Forward-compatible with the source catalog; older APIs may omit this field. */
  license_url?: string | null
  attribution_text?: string | null
  terms_note?: string | null
  authority_level?: string
  official?: boolean
  source_limitations?: Record<string, unknown>
  evidence_role: string
  required: boolean
  entity_type: string
  entity_key: string
  canonical_source_type: string
  observed_at: string
  fetched_at: string
  valid_until?: string | null
  freshness_state: string
  availability_state: string
  confidence?: number | null
  completeness?: number | null
  value_summary: Record<string, unknown>
  metadata: Record<string, unknown>
  integrity_checksum?: string | null
  created_at: string
}

export interface AssuranceFinding {
  id: string
  code: string
  severity: 'INFO' | 'WARNING' | 'ERROR'
  message: string
  evidence_record_ids: string[]
  details: Record<string, unknown>
  created_at: string
}

export interface AssuranceMatrixItem {
  role: string
  required: boolean
  status: AssuranceMatrixStatus
  record_ids: string[]
  source_keys: string[]
  reason_codes: string[]
}

export interface AssuranceMatrix {
  case_id: string
  snapshot_id: string
  state: AssuranceState
  roles: AssuranceMatrixItem[]
}

export interface AssuranceAssessment {
  id: string
  case_id: string
  sequence_no: number
  decision_state: AssuranceState
  policy_key: string
  policy_version: string
  matrix: AssuranceMatrix
  metrics: Record<string, unknown>
  bundle_checksum: string
  bundle_signature: string
  signing_key_id: string
  signing_algorithm: string
  assessed_at: string
  findings: AssuranceFinding[]
}

export interface AssuranceTimelineEvent {
  occurred_at: string
  event_type: string
  entity_id: string
  summary: string
  details: Record<string, unknown>
}

export interface AssuranceTimeline {
  case_id: string
  events: AssuranceTimelineEvent[]
}

export interface AssuranceReviewReceipt {
  id: string
  case_id: string
  snapshot_id: string
  reviewer_id: string
  reviewer_role: string
  outcome: 'ATTESTED' | 'RETURNED'
  statement: string
  snapshot_checksum: string
  receipt_checksum: string
  receipt_signature: string
  signing_key_id: string
  signing_algorithm: string
  reviewed_at: string
}

export interface AssuranceBundle {
  format_version: 'clearpath.assurance-bundle.v1'
  case: AssuranceCase
  assessment: AssuranceAssessment
  evidence: AssuranceEvidence[]
  review_receipts: AssuranceReviewReceipt[]
  review_receipt_manifests: Record<string, unknown>[]
  sealed_manifest: Record<string, unknown>
  evidence_envelopes: Record<string, unknown>[]
  source_catalog: Record<string, unknown>[]
  lineage: Record<string, unknown>[]
  limitations: string[]
}

export interface AssuranceVerification {
  case_id: string
  snapshot_id: string
  verified: boolean
  bundle_checksum_valid: boolean
  bundle_signature_valid: boolean
  evidence_integrity_valid: boolean
  invalid_evidence_record_ids: string[]
  invalid_review_receipt_ids: string[]
}

export interface AssurancePolicy {
  key: string
  version: string
  title: string
  description: string
  decision_states: string[]
  checks: Array<Record<string, unknown>>
  limitations: string[]
}

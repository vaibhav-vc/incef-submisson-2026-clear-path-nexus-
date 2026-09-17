import type {
  AssuranceAssessment,
  AssuranceBundle,
  AssuranceCase,
  AssuranceCaseCreate,
  AssuranceEvidence,
  AssuranceMatrix,
  AssurancePolicy,
  AssuranceReviewReceipt,
  AssuranceTimeline,
  AssuranceVerification,
} from '../types/assurance'
import { api } from './api'

const assurancePath = '/assurance'

export async function submitAssuranceReview(
  caseId: string,
  snapshotId: string,
  outcome: 'ATTESTED' | 'RETURNED',
  statement: string,
): Promise<AssuranceReviewReceipt> {
  const { data } = await api.post<AssuranceReviewReceipt>(`${assurancePath}/cases/${caseId}/review-receipts`, {
    snapshot_id: snapshotId, outcome, statement,
  })
  return data
}

export async function listAssurancePolicies(signal?: AbortSignal): Promise<AssurancePolicy[]> {
  const { data } = await api.get<AssurancePolicy[]>(`${assurancePath}/policies`, { signal })
  return data
}

export async function listAssuranceCases(signal?: AbortSignal): Promise<AssuranceCase[]> {
  const { data } = await api.get<AssuranceCase[]>(`${assurancePath}/cases`, { signal })
  return data
}

export async function createAssuranceCase(payload: AssuranceCaseCreate): Promise<AssuranceCase> {
  const { data } = await api.post<AssuranceCase>(`${assurancePath}/cases`, payload)
  return data
}

export async function listAssuranceEvidence(
  caseId: string,
  signal?: AbortSignal,
): Promise<AssuranceEvidence[]> {
  const { data } = await api.get<AssuranceEvidence[]>(`${assurancePath}/cases/${caseId}/evidence`, { signal })
  return data
}

export async function getAssuranceMatrix(
  caseId: string,
  signal?: AbortSignal,
): Promise<AssuranceMatrix> {
  const { data } = await api.get<AssuranceMatrix>(`${assurancePath}/cases/${caseId}/matrix`, { signal })
  return data
}

export async function getAssuranceAssessment(
  caseId: string,
  snapshotId: string,
  signal?: AbortSignal,
): Promise<AssuranceAssessment> {
  const { data } = await api.get<AssuranceAssessment>(
    `${assurancePath}/cases/${caseId}/assessments/${snapshotId}`,
    { signal },
  )
  return data
}

export async function getAssuranceTimeline(
  caseId: string,
  signal?: AbortSignal,
): Promise<AssuranceTimeline> {
  const { data } = await api.get<AssuranceTimeline>(`${assurancePath}/cases/${caseId}/timeline`, { signal })
  return data
}

export async function runAssuranceAssessment(caseId: string): Promise<AssuranceAssessment> {
  const { data } = await api.post<AssuranceAssessment>(`${assurancePath}/cases/${caseId}/assessments`)
  return data
}

export async function getAssuranceBundle(caseId: string): Promise<AssuranceBundle> {
  const { data } = await api.get<AssuranceBundle>(`${assurancePath}/cases/${caseId}/bundle`)
  return data
}

export async function verifyAssuranceBundle(
  caseId: string,
  snapshotId: string,
): Promise<AssuranceVerification> {
  const { data } = await api.post<AssuranceVerification>(`${assurancePath}/cases/${caseId}/verify`, {
    snapshot_id: snapshotId,
  })
  return data
}

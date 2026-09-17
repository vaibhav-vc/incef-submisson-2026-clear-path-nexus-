import axios from 'axios'
import type { AppRuntimeMode } from './runtimeMode'
import type {
  AssuranceBundle,
  AssuranceCase,
  AssuranceEvidence,
  AssuranceMatrixItem,
} from '../types/assurance'

export interface PendingMatrixItem {
  role: string
  required: true
  capturedRecordCount: number
  sourceKeys: string[]
}

export function buildPendingMatrix(
  assuranceCase: AssuranceCase,
  evidence: AssuranceEvidence[],
): PendingMatrixItem[] {
  const byRole = new Map<string, { count: number; sources: Set<string> }>()
  for (const record of evidence) {
    const role = record.evidence_role.trim().toUpperCase()
    const current = byRole.get(role) ?? { count: 0, sources: new Set<string>() }
    current.count += 1
    current.sources.add(record.source_key)
    byRole.set(role, current)
  }
  return assuranceCase.required_roles.map((rawRole) => {
    const role = rawRole.trim().toUpperCase()
    const match = byRole.get(role)
    return {
      role,
      required: true,
      capturedRecordCount: match?.count ?? 0,
      sourceKeys: match ? [...match.sources].sort() : [],
    }
  })
}

export function bundleFilename(bundle: AssuranceBundle): string {
  const key = bundle.case.subject_key
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60) || bundle.case.id.slice(0, 8)
  return `evidencegate-${key}-assessment-${bundle.assessment.sequence_no}.json`
}

export function safeExternalUrl(value: unknown): string | null {
  if (typeof value !== 'string' || value.length > 2048) return null
  try {
    const parsed = new URL(value)
    if (parsed.username || parsed.password) return null
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? parsed.href : null
  } catch {
    return null
  }
}

export function evidenceLicenseUrl(evidence: AssuranceEvidence): string | null {
  return safeExternalUrl(evidence.license_url) ?? safeExternalUrl(evidence.metadata.license_url)
}

export function runtimeEvidenceNotice(mode: AppRuntimeMode): { title: string; detail: string } {
  return mode === 'offline-judge'
    ? {
        title: 'Offline judge run · recorded publisher source',
        detail: 'The captured feed is historical research material. User-entered cases are declarations; neither is relabelled as live Indian Railways evidence.',
      }
    : {
        title: 'Online live API session · authenticated stored evidence',
        detail: 'A connected API does not make every record live. Use each record’s source type, observed time, and freshness state to judge recency.',
      }
}

export function describeAssuranceError(error: unknown, fallback: string): string {
  if (!axios.isAxiosError(error)) return fallback
  const detail: unknown = error.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item: unknown) => {
        if (!item || typeof item !== 'object' || !('msg' in item)) return null
        return typeof item.msg === 'string' ? item.msg : null
      })
      .filter((item): item is string => Boolean(item))
    if (messages.length > 0) return messages.join(' ')
  }
  return fallback
}

export function isMissingAssessment(error: unknown): boolean {
  return axios.isAxiosError(error) && error.response?.status === 404
}

export function downloadBundle(bundle: AssuranceBundle): void {
  const url = URL.createObjectURL(new Blob([JSON.stringify(bundle, null, 2)], {
    type: 'application/json;charset=utf-8',
  }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = bundleFilename(bundle)
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export function matrixStatusClasses(status: AssuranceMatrixItem['status']): string {
  if (status === 'PASS') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'
  if (status === 'WARNING') return 'border-amber-500/30 bg-amber-500/10 text-amber-200'
  return 'border-rose-500/30 bg-rose-500/10 text-rose-200'
}

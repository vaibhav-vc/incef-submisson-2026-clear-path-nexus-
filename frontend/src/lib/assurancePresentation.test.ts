import { describe, expect, it } from 'vitest'
import type { AssuranceBundle, AssuranceCase, AssuranceEvidence } from '../types/assurance'
import {
  buildPendingMatrix,
  bundleFilename,
  evidenceLicenseUrl,
  runtimeEvidenceNotice,
  safeExternalUrl,
} from './assurancePresentation'

const assuranceCase: AssuranceCase = {
  id: '11111111-1111-1111-1111-111111111111',
  user_id: 'judge',
  title: 'Evidence review',
  purpose: 'Review captured evidence before a non-vital research decision.',
  subject_type: 'RESEARCH_CASE',
  subject_key: 'Train 12 / Nagpur',
  context: {},
  required_roles: ['manifest', 'weather'],
  policy_key: 'GENERIC_PROVENANCE_V1',
  policy_version: '1.0.0',
  status: 'OPEN',
  created_at: '2026-09-16T00:00:00Z',
  updated_at: '2026-09-16T00:00:00Z',
}

function evidence(overrides: Partial<AssuranceEvidence> = {}): AssuranceEvidence {
  return {
    id: '22222222-2222-2222-2222-222222222222',
    case_id: assuranceCase.id,
    source_id: '33333333-3333-3333-3333-333333333333',
    source_key: 'official_feed',
    source_name: 'Official Feed',
    source_url: 'https://data.example.test/feed',
    license_name: 'Open data terms',
    attribution_text: 'Example attribution',
    evidence_role: 'MANIFEST',
    required: true,
    entity_type: 'MANIFEST',
    entity_key: 'manifest-1',
    canonical_source_type: 'PUBLIC_OPEN_DATA',
    observed_at: '2026-09-16T00:00:00Z',
    fetched_at: '2026-09-16T00:01:00Z',
    freshness_state: 'FRESH',
    availability_state: 'AVAILABLE',
    completeness: 1,
    value_summary: { present: true },
    metadata: {},
    integrity_checksum: 'a'.repeat(64),
    created_at: '2026-09-16T00:01:00Z',
    ...overrides,
  }
}

describe('assurance presentation model', () => {
  it('does not confuse captured evidence with a policy pass', () => {
    const rows = buildPendingMatrix(assuranceCase, [
      evidence(),
      evidence({ id: '44444444-4444-4444-4444-444444444444' }),
    ])

    expect(rows).toEqual([
      {
        role: 'MANIFEST',
        required: true,
        capturedRecordCount: 2,
        sourceKeys: ['official_feed'],
      },
      {
        role: 'WEATHER',
        required: true,
        capturedRecordCount: 0,
        sourceKeys: [],
      },
    ])
  })

  it('creates a filesystem-safe bundle filename from server data', () => {
    const bundle = {
      case: assuranceCase,
      assessment: { sequence_no: 7 },
    } as AssuranceBundle

    expect(bundleFilename(bundle)).toBe('evidencegate-train-12-nagpur-assessment-7.json')
  })

  it('accepts web references but rejects executable or credential-bearing URLs', () => {
    expect(safeExternalUrl('https://data.example.test/licence')).toBe('https://data.example.test/licence')
    expect(safeExternalUrl('javascript:alert(1)')).toBeNull()
    expect(safeExternalUrl('https://user:secret@data.example.test/licence')).toBeNull()
    expect(safeExternalUrl('not a URL')).toBeNull()
  })

  it('uses a supplied licence URL without inventing one', () => {
    expect(evidenceLicenseUrl(evidence({ metadata: { license_url: 'https://data.example.test/terms' } })))
      .toBe('https://data.example.test/terms')
    expect(evidenceLicenseUrl(evidence({ metadata: {} }))).toBeNull()
  })

  it('labels offline evidence as staged and online records as stored', () => {
    expect(runtimeEvidenceNotice('offline-judge').title).toMatch(/staged evidence/i)
    expect(runtimeEvidenceNotice('offline-judge').detail).toMatch(/never relabels.*live/i)
    expect(runtimeEvidenceNotice('online').title).toMatch(/stored evidence/i)
    expect(runtimeEvidenceNotice('online').detail).toMatch(/does not make every record live/i)
  })
})

import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { APP_RUNTIME_MODE, LOCAL_DEMO_MODE } from '../lib/runtimeMode'
import RecordedSourcePanel from './RecordedSourcePanel'
import {
  buildPendingMatrix,
  describeAssuranceError,
  downloadBundle,
  evidenceLicenseUrl,
  isMissingAssessment,
  matrixStatusClasses,
  runtimeEvidenceNotice,
  safeExternalUrl,
} from '../lib/assurancePresentation'
import {
  createAssuranceCase,
  getAssuranceAssessment,
  getAssuranceBundle,
  getAssuranceMatrix,
  getAssuranceTimeline,
  listAssuranceCases,
  listAssuranceEvidence,
  listAssurancePolicies,
  runAssuranceAssessment,
  submitAssuranceReview,
  verifyAssuranceBundle,
} from '../services/assuranceApi'
import type {
  AssuranceAssessment,
  AssuranceCase,
  AssuranceEvidence,
  AssurancePolicy,
  AssuranceTimelineEvent,
  AssuranceVerification,
} from '../types/assurance'

interface CaseFormState {
  reviewerId: string
  contextText: string
  title: string
  purpose: string
  subjectType: string
  subjectKey: string
  requiredRoles: string
}

const EMPTY_CASE_FORM: CaseFormState = {
  reviewerId: '',
  contextText: '',
  title: '',
  purpose: '',
  subjectType: '',
  subjectKey: '',
  requiredRoles: '',
}

const DATE_TIME_FORMATTER = new Intl.DateTimeFormat(undefined, {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  timeZoneName: 'short',
})

function formatTimestamp(value: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return DATE_TIME_FORMATTER.format(parsed)
}

function stateClasses(state: string): string {
  if (['REVIEWABLE', 'PASS', 'VERIFIED', 'FRESH', 'REVIEWED'].includes(state)) {
    return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'
  }
  if (['HOLD', 'WARNING', 'AGING', 'ASSESSED'].includes(state)) {
    return 'border-amber-500/30 bg-amber-500/10 text-amber-200'
  }
  if (state === 'OPEN' || state === 'INFO') return 'border-cyan-500/30 bg-cyan-500/10 text-cyan-200'
  if (state === 'ARCHIVED' || state === 'NOT_APPLICABLE') return 'border-slate-600 bg-slate-800 text-slate-300'
  return 'border-rose-500/30 bg-rose-500/10 text-rose-200'
}

function StatusPill({ value }: { value: string }) {
  return (
    <span className={`inline-flex rounded-full border px-2 py-1 text-[10px] font-bold uppercase tracking-wide ${stateClasses(value)}`}>
      {value.replaceAll('_', ' ')}
    </span>
  )
}

function VerificationCheck({ label, valid }: { label: string; valid: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-slate-800 bg-slate-950/70 px-3 py-2">
      <span className="text-xs text-slate-300">{label}</span>
      <span className={valid ? 'text-xs font-bold text-emerald-300' : 'text-xs font-bold text-rose-300'}>
        {valid ? 'VALID' : 'INVALID'}
      </span>
    </div>
  )
}

function AssuranceMatrixPanel({
  selectedCase,
  evidence,
  assessment,
}: {
  selectedCase: AssuranceCase
  evidence: AssuranceEvidence[]
  assessment: AssuranceAssessment | null
}) {
  const pendingMatrix = useMemo(
    () => buildPendingMatrix(selectedCase, evidence),
    [selectedCase, evidence],
  )

  return (
    <section aria-labelledby="assurance-matrix-title" className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[10px] font-mono uppercase tracking-[0.18em] text-cyan-300">Required evidence roles</p>
          <h3 id="assurance-matrix-title" className="mt-1 text-lg font-bold text-white">Evidence matrix</h3>
        </div>
        {assessment ? <StatusPill value={assessment.decision_state} /> : <StatusPill value="NOT ASSESSED" />}
      </div>
      <p className="mt-2 text-xs leading-relaxed text-slate-400">
        {assessment
          ? `Snapshot ${assessment.sequence_no} was evaluated under ${assessment.policy_key} ${assessment.policy_version}.`
          : 'Captured only means a record is present. No role passes policy until an assessment is run.'}
      </p>
      <div className="mt-4 space-y-2">
        {assessment
          ? assessment.matrix.roles.map((row) => (
              <article key={row.role} className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h4 className="font-mono text-xs font-bold text-slate-100">{row.role}</h4>
                    <p className="mt-1 text-[11px] text-slate-500">
                      {row.record_ids.length} record(s) · {row.source_keys.length > 0 ? row.source_keys.join(', ') : 'no accepted source'}
                    </p>
                  </div>
                  <span className={`rounded-full border px-2 py-1 text-[10px] font-bold ${matrixStatusClasses(row.status)}`}>
                    {row.status}
                  </span>
                </div>
                {row.reason_codes.length > 0 ? (
                  <p className="mt-2 text-[11px] text-slate-400">Reasons: {row.reason_codes.join(', ')}</p>
                ) : null}
              </article>
            ))
          : pendingMatrix.map((row) => (
              <article key={row.role} className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h4 className="font-mono text-xs font-bold text-slate-100">{row.role}</h4>
                    <p className="mt-1 text-[11px] text-slate-500">
                      {row.capturedRecordCount} captured record(s)
                      {row.sourceKeys.length > 0 ? ` · ${row.sourceKeys.join(', ')}` : ''}
                    </p>
                  </div>
                  <span className={`rounded-full border px-2 py-1 text-[10px] font-bold ${row.capturedRecordCount > 0 ? 'border-cyan-500/30 bg-cyan-500/10 text-cyan-200' : 'border-rose-500/30 bg-rose-500/10 text-rose-200'}`}>
                    {row.capturedRecordCount > 0 ? 'CAPTURED · PENDING' : 'MISSING'}
                  </span>
                </div>
              </article>
            ))}
      </div>
    </section>
  )
}

function EvidenceSourcesPanel({ evidence }: { evidence: AssuranceEvidence[] }) {
  return (
    <section aria-labelledby="assurance-sources-title" className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
      <div>
        <p className="text-[10px] font-mono uppercase tracking-[0.18em] text-cyan-300">Attribution and terms</p>
        <h3 id="assurance-sources-title" className="mt-1 text-lg font-bold text-white">Evidence sources</h3>
        <p className="mt-2 text-xs text-slate-400">Source type and timestamps are shown per record. A provider name alone is not proof that a stored record is live.</p>
      </div>
      {evidence.length === 0 ? (
        <div className="mt-4 rounded-xl border border-dashed border-slate-700 p-5 text-sm text-slate-400">
          No evidence is linked to this case. Capture records through an authenticated connector or evidence-ingestion API before assessing.
        </div>
      ) : (
        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          {evidence.map((record) => {
            const sourceUrl = safeExternalUrl(record.source_url)
            const licenseUrl = evidenceLicenseUrl(record)
            return (
              <article key={record.id} className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="font-mono text-[10px] font-bold uppercase tracking-wide text-cyan-300">{record.evidence_role}</p>
                    <h4 className="mt-1 text-sm font-semibold text-white">{record.source_name}</h4>
                    <p className="text-[11px] text-slate-500">{record.source_key} · {record.canonical_source_type.replaceAll('_', ' ')}</p>
                  </div>
                  <StatusPill value={record.freshness_state} />
                </div>
                <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11px]">
                  <dt className="text-slate-500">Observed</dt><dd className="text-right text-slate-300">{formatTimestamp(record.observed_at)}</dd>
                  <dt className="text-slate-500">Fetched</dt><dd className="text-right text-slate-300">{formatTimestamp(record.fetched_at)}</dd>
                  <dt className="text-slate-500">Availability</dt><dd className="text-right text-slate-300">{record.availability_state}</dd>
                  <dt className="text-slate-500">Completeness</dt><dd className="text-right text-slate-300">{record.completeness == null ? 'Not reported' : `${Math.round(record.completeness * 100)}%`}</dd>
                  <dt className="text-slate-500">Licence</dt><dd className="text-right text-slate-300">{record.license_name ?? 'Not declared by source catalog'}</dd>
                  <dt className="text-slate-500">Authority</dt><dd className="text-right text-slate-300">{record.authority_level ?? 'Not supplied'} · {record.official == null ? 'official status unknown' : record.official ? 'official source' : 'non-official source'}</dd>
                </dl>
                {record.attribution_text ? <p className="mt-3 border-l-2 border-cyan-700 pl-3 text-[11px] leading-relaxed text-slate-400">{record.attribution_text}</p> : null}
                {record.terms_note ? <p className="mt-2 text-[11px] text-slate-400">Terms: {record.terms_note}</p> : null}
                {record.source_limitations && Object.keys(record.source_limitations).length > 0 ? (
                  <details className="mt-2 text-[11px] text-slate-400">
                    <summary className="cursor-pointer">Declared source limitations</summary>
                    <pre className="mt-2 whitespace-pre-wrap break-words rounded bg-slate-950 p-2">{JSON.stringify(record.source_limitations, null, 2)}</pre>
                  </details>
                ) : null}
                <div className="mt-3 flex flex-wrap gap-3 text-xs font-semibold">
                  {sourceUrl ? <a href={sourceUrl} target="_blank" rel="noreferrer" className="text-cyan-300 hover:underline">Provider reference ↗</a> : <span className="text-slate-600">No provider URL supplied</span>}
                  {licenseUrl ? <a href={licenseUrl} target="_blank" rel="noreferrer" className="text-cyan-300 hover:underline">Licence terms ↗</a> : <span className="text-slate-600">No licence URL supplied</span>}
                </div>
              </article>
            )
          })}
        </div>
      )}
    </section>
  )
}

function TimelinePanel({ events }: { events: AssuranceTimelineEvent[] }) {
  return (
    <section aria-labelledby="assurance-timeline-title" className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
      <p className="text-[10px] font-mono uppercase tracking-[0.18em] text-cyan-300">Append-only reconstruction</p>
      <h3 id="assurance-timeline-title" className="mt-1 text-lg font-bold text-white">Case timeline</h3>
      {events.length === 0 ? (
        <p className="mt-4 text-sm text-slate-500">No timeline events are available.</p>
      ) : (
        <ol className="mt-4 space-y-3 border-l border-slate-700 pl-4">
          {events.map((event) => (
            <li key={`${event.event_type}-${event.entity_id}-${event.occurred_at}`} className="relative">
              <span aria-hidden="true" className="absolute -left-[1.18rem] top-1.5 h-2 w-2 rounded-full bg-cyan-400" />
              <p className="font-mono text-[10px] uppercase tracking-wide text-cyan-300">{event.event_type.replaceAll('_', ' ')}</p>
              <p className="mt-1 text-xs leading-relaxed text-slate-300">{event.summary}</p>
              <time className="mt-1 block text-[10px] text-slate-500" dateTime={event.occurred_at}>{formatTimestamp(event.occurred_at)}</time>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

export default function AssuranceWorkspace() {
  const runtimeNotice = runtimeEvidenceNotice(APP_RUNTIME_MODE)
  const [cases, setCases] = useState<AssuranceCase[]>([])
  const [policies, setPolicies] = useState<AssurancePolicy[]>([])
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null)
  const [evidence, setEvidence] = useState<AssuranceEvidence[]>([])
  const [events, setEvents] = useState<AssuranceTimelineEvent[]>([])
  const [assessment, setAssessment] = useState<AssuranceAssessment | null>(null)
  const [verification, setVerification] = useState<AssuranceVerification | null>(null)
  const [form, setForm] = useState<CaseFormState>(EMPTY_CASE_FORM)
  const [policyKey, setPolicyKey] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [loadingCases, setLoadingCases] = useState(true)
  const [loadingDetails, setLoadingDetails] = useState(false)
  const [busyAction, setBusyAction] = useState<'create' | 'assess' | 'export' | 'verify' | 'review' | null>(null)
  const [reviewStatement, setReviewStatement] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const selectedCase = useMemo(
    () => cases.find((item) => item.id === selectedCaseId) ?? null,
    [cases, selectedCaseId],
  )

  useEffect(() => {
    const controller = new AbortController()
    async function loadWorkspace() {
      setLoadingCases(true)
      setError(null)
      try {
        const [nextCases, nextPolicies] = await Promise.all([
          listAssuranceCases(controller.signal),
          listAssurancePolicies(controller.signal),
        ])
        if (controller.signal.aborted) return
        setCases(nextCases)
        setPolicies(nextPolicies)
        setPolicyKey((current) => current || nextPolicies[0]?.key || '')
        setSelectedCaseId((current) => current ?? nextCases[0]?.id ?? null)
      } catch (loadError) {
        if (!controller.signal.aborted) {
          setError(describeAssuranceError(loadError, 'Evidence Assurance could not load cases and policies.'))
        }
      } finally {
        if (!controller.signal.aborted) setLoadingCases(false)
      }
    }
    void loadWorkspace()
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (!selectedCaseId) {
      setEvidence([])
      setEvents([])
      setAssessment(null)
      setVerification(null)
      return
    }
    const controller = new AbortController()
    async function loadDetails() {
      setLoadingDetails(true)
      setError(null)
      setNotice(null)
      setEvidence([])
      setEvents([])
      setAssessment(null)
      setVerification(null)
      try {
        const [nextEvidence, timeline, matrixResult] = await Promise.all([
          listAssuranceEvidence(selectedCaseId!, controller.signal),
          getAssuranceTimeline(selectedCaseId!, controller.signal),
          getAssuranceMatrix(selectedCaseId!, controller.signal)
            .then((matrix) => ({ ok: true as const, matrix }))
            .catch((matrixError: unknown) => ({ ok: false as const, error: matrixError })),
        ])
        if (controller.signal.aborted) return
        setEvidence(nextEvidence)
        setEvents(timeline.events)
        if (matrixResult.ok) {
          const nextAssessment = await getAssuranceAssessment(
            selectedCaseId!,
            matrixResult.matrix.snapshot_id,
            controller.signal,
          )
          if (!controller.signal.aborted) setAssessment(nextAssessment)
        } else if (isMissingAssessment(matrixResult.error)) {
          setAssessment(null)
        } else {
          throw matrixResult.error
        }
      } catch (loadError) {
        if (!controller.signal.aborted) {
          setError(describeAssuranceError(loadError, 'The selected assurance case could not be loaded.'))
        }
      } finally {
        if (!controller.signal.aborted) setLoadingDetails(false)
      }
    }
    void loadDetails()
    return () => controller.abort()
  }, [selectedCaseId])

  async function submitCase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    let context: Record<string, unknown>
    try {
      const parsed: unknown = form.contextText.trim() ? JSON.parse(form.contextText) : {}
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) throw new Error('Context must be an object')
      context = parsed as Record<string, unknown>
    } catch {
      setError('Case context must be a valid JSON object, or left empty.')
      return
    }
    const requiredRoles = [...new Set(form.requiredRoles.split(',').map((role) => role.trim().toUpperCase()).filter(Boolean))]
    if (requiredRoles.length === 0) {
      setError('Enter at least one required evidence role.')
      return
    }
    if (!policyKey) {
      setError('Select an assurance policy returned by the backend.')
      return
    }
    setBusyAction('create')
    setError(null)
    setNotice(null)
    try {
      const created = await createAssuranceCase({
        title: form.title.trim(),
        purpose: form.purpose.trim(),
        subject_type: form.subjectType.trim(),
        subject_key: form.subjectKey.trim(),
        context,
        assigned_reviewer_id: form.reviewerId.trim() || null,
        required_roles: requiredRoles,
        policy_key: policyKey,
      })
      setCases((current) => [created, ...current.filter((item) => item.id !== created.id)])
      setForm(EMPTY_CASE_FORM)
      setShowCreate(false)
      setSelectedCaseId(created.id)
      setNotice('Assurance case created. It remains OPEN until evidence is captured and assessed.')
    } catch (createError) {
      setError(describeAssuranceError(createError, 'The assurance case could not be created.'))
    } finally {
      setBusyAction(null)
    }
  }

  async function assessSelectedCase() {
    if (!selectedCase) return
    setBusyAction('assess')
    setError(null)
    setNotice(null)
    setVerification(null)
    try {
      const result = await runAssuranceAssessment(selectedCase.id)
      setAssessment(result)
      setCases((current) => current.map((item) => item.id === selectedCase.id ? { ...item, status: 'ASSESSED' } : item))
      setNotice(`Assessment ${result.sequence_no} completed with state ${result.decision_state}.`)
      try {
        const timeline = await getAssuranceTimeline(selectedCase.id)
        setEvents(timeline.events)
      } catch (timelineError) {
        setError(describeAssuranceError(timelineError, 'The assessment completed, but its timeline could not be refreshed.'))
      }
    } catch (assessmentError) {
      setError(describeAssuranceError(assessmentError, 'The case assessment could not be completed.'))
    } finally {
      setBusyAction(null)
    }
  }

  async function exportSelectedBundle() {
    if (!selectedCase || !assessment) return
    setBusyAction('export')
    setError(null)
    setNotice(null)
    try {
      const bundle = await getAssuranceBundle(selectedCase.id)
      downloadBundle(bundle)
      setNotice(`Exported assessment ${bundle.assessment.sequence_no} with its evidence manifest, checksum, signature, and limitations.`)
    } catch (exportError) {
      setError(describeAssuranceError(exportError, 'The signed assurance bundle could not be exported.'))
    } finally {
      setBusyAction(null)
    }
  }

  async function reviewSelectedCase(outcome: 'ATTESTED' | 'RETURNED') {
    if (!selectedCase || !assessment || reviewStatement.trim().length < 12) return
    setBusyAction('review')
    setError(null)
    setNotice(null)
    try {
      const receipt = await submitAssuranceReview(selectedCase.id, assessment.id, outcome, reviewStatement.trim())
      setCases((current) => current.map((item) => item.id === selectedCase.id ? { ...item, status: receipt.outcome === 'ATTESTED' ? 'REVIEWED' : 'OPEN' } : item))
      setReviewStatement('')
      setVerification(null)
      setNotice(`Independent review recorded: ${receipt.outcome}. Receipt checksum: ${receipt.receipt_checksum}`)
      const timeline = await getAssuranceTimeline(selectedCase.id)
      setEvents(timeline.events)
    } catch (reviewError) {
      setError(describeAssuranceError(reviewError, 'The review could not be recorded. Only the assigned authorized reviewer can review the current assessment.'))
    } finally {
      setBusyAction(null)
    }
  }

  async function verifySelectedBundle() {
    if (!selectedCase || !assessment) return
    setBusyAction('verify')
    setError(null)
    setNotice(null)
    try {
      const result = await verifyAssuranceBundle(selectedCase.id, assessment.id)
      setVerification(result)
      setNotice(result.verified
        ? 'The server recomputed and verified this snapshot seal and linked evidence integrity.'
        : 'Verification failed. Do not rely on or present this bundle as intact.')
    } catch (verifyError) {
      setError(describeAssuranceError(verifyError, 'The assurance bundle could not be verified.'))
    } finally {
      setBusyAction(null)
    }
  }

  return (
    <section className="space-y-5" aria-labelledby="assurance-workspace-title">
      <div className="rounded-2xl border border-cyan-500/20 bg-gradient-to-r from-slate-900 to-cyan-950/30 p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <p className="text-xs font-mono uppercase tracking-[0.2em] text-cyan-300">EvidenceGate v7 / judge workspace</p>
            <h2 id="assurance-workspace-title" className="mt-2 text-2xl font-bold text-white">Evidence Assurance</h2>
            <p className="mt-2 text-sm leading-relaxed text-slate-300">
              Build a route-independent evidence case, inspect provenance and licence metadata, run the policy gate, and export a verifiable review bundle.
            </p>
          </div>
          <span className={`rounded-full border px-3 py-1 text-xs font-bold ${LOCAL_DEMO_MODE ? 'border-amber-400/40 bg-amber-400/10 text-amber-200' : 'border-cyan-400/30 bg-cyan-400/10 text-cyan-200'}`}>
            {LOCAL_DEMO_MODE ? 'OFFLINE · RECORDED' : 'ONLINE · STORED'}
          </span>
        </div>
        <div className={`mt-4 rounded-xl border p-4 ${LOCAL_DEMO_MODE ? 'border-amber-400/30 bg-amber-400/5' : 'border-cyan-400/20 bg-cyan-400/5'}`} role="status">
          <p className="text-sm font-bold text-white">{runtimeNotice.title}</p>
          <p className="mt-1 text-xs leading-relaxed text-slate-300">{runtimeNotice.detail}</p>
        </div>
        <p className="mt-3 rounded-lg border border-rose-400/20 bg-rose-400/5 px-3 py-2 text-xs text-rose-100">
          Non-vital research boundary: REVIEWABLE is evidence admissibility, not movement authority, driver-speed instruction, interlocking control, or dispatch approval.
        </p>
      </div>

      {LOCAL_DEMO_MODE && <RecordedSourcePanel />}

      <div aria-live="polite" className="space-y-2">
        {error ? <p role="alert" className="rounded-xl border border-rose-700 bg-rose-950/30 p-4 text-sm text-rose-200">{error}</p> : null}
        {notice ? <p className="rounded-xl border border-cyan-700 bg-cyan-950/30 p-4 text-sm text-cyan-100">{notice}</p> : null}
      </div>

      <div className="grid gap-5 xl:grid-cols-[19rem_minmax(0,1fr)]">
        <aside className="space-y-4">
          <section className="rounded-2xl border border-slate-800 bg-slate-900 p-4" aria-labelledby="assurance-cases-title">
            <div className="flex items-center justify-between gap-2">
              <h3 id="assurance-cases-title" className="font-bold text-white">Cases</h3>
              <button
                type="button"
                onClick={() => setShowCreate((visible) => !visible)}
                aria-expanded={showCreate}
                className="rounded-lg bg-cyan-500 px-3 py-1.5 text-xs font-bold text-slate-950 hover:bg-cyan-400"
              >
                {showCreate ? 'Close form' : 'New case'}
              </button>
            </div>
            {loadingCases ? <p className="mt-4 text-sm text-slate-500">Loading stored cases…</p> : null}
            {!loadingCases && cases.length === 0 ? (
              <p className="mt-4 rounded-lg border border-dashed border-slate-700 p-3 text-xs leading-relaxed text-slate-400">No assurance cases are stored for this account.</p>
            ) : null}
            <div className="mt-3 space-y-2">
              {cases.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => { setSelectedCaseId(item.id); setReviewStatement('') }}
                  aria-pressed={selectedCaseId === item.id}
                  className={`w-full rounded-xl border p-3 text-left transition ${selectedCaseId === item.id ? 'border-cyan-500/60 bg-cyan-500/10' : 'border-slate-800 bg-slate-950/60 hover:border-slate-700'}`}
                >
                  <span className="block truncate text-sm font-semibold text-slate-100">{item.title}</span>
                  <span className="mt-1 block truncate font-mono text-[10px] text-slate-500">{item.subject_type} / {item.subject_key}</span>
                  <span className="mt-2 block"><StatusPill value={item.status} /></span>
                </button>
              ))}
            </div>
          </section>

          {showCreate ? (
            <form onSubmit={(event) => void submitCase(event)} className="rounded-2xl border border-slate-700 bg-slate-900 p-4" aria-labelledby="create-assurance-case-title">
              <h3 id="create-assurance-case-title" className="font-bold text-white">Create assurance case</h3>
              <p className="mt-1 text-[11px] leading-relaxed text-slate-400">All fields are supplied by you or loaded from the backend. No example is submitted automatically.</p>
              <div className="mt-4 space-y-3">
                <label className="block text-xs text-slate-300">Case title
                  <input required minLength={3} maxLength={200} value={form.title} onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white" />
                </label>
                <label className="block text-xs text-slate-300">Purpose
                  <textarea required minLength={10} maxLength={4000} rows={3} value={form.purpose} onChange={(event) => setForm((current) => ({ ...current, purpose: event.target.value }))} className="mt-1 w-full resize-y rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white" />
                </label>
                <label className="block text-xs text-slate-300">Subject type
                  <input required maxLength={80} value={form.subjectType} onChange={(event) => setForm((current) => ({ ...current, subjectType: event.target.value }))} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white" />
                </label>
                <label className="block text-xs text-slate-300">Subject key
                  <input required maxLength={255} value={form.subjectKey} onChange={(event) => setForm((current) => ({ ...current, subjectKey: event.target.value }))} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white" />
                </label>
                <label className="block text-xs text-slate-300">Required roles <span className="text-slate-500">(comma-separated)</span>
                  <input required value={form.requiredRoles} onChange={(event) => setForm((current) => ({ ...current, requiredRoles: event.target.value }))} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white" />
                </label>
                <label className="block text-xs text-slate-300">Policy
                  <select required value={policyKey} onChange={(event) => setPolicyKey(event.target.value)} disabled={policies.length === 0} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white disabled:opacity-50">
                    {policies.length === 0 ? <option value="">No backend policy available</option> : null}
                    {policies.map((policy) => <option key={policy.key} value={policy.key}>{policy.title} · {policy.version}</option>)}
                  </select>
                </label>
                <label className="block text-xs text-slate-300">Independent reviewer account ID <span className="text-slate-500">(optional)</span>
                  <input maxLength={64} value={form.reviewerId} onChange={(event) => setForm((current) => ({ ...current, reviewerId: event.target.value }))} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white" />
                  <span className="mt-1 block text-[11px] text-slate-500">Attestation requires a different, authorized reviewer. Leaving this empty keeps the case unassigned.</span>
                </label>
                <label className="block text-xs text-slate-300">Case context <span className="text-slate-500">(optional JSON object)</span>
                  <textarea rows={3} value={form.contextText} onChange={(event) => setForm((current) => ({ ...current, contextText: event.target.value }))} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-xs text-white" />
                  <span className="mt-1 block text-[11px] text-slate-500">Capture the service date, corridor or other scope supplied by your source; it is bound into the evidence checksum.</span>
                </label>
              </div>
              <button type="submit" disabled={busyAction !== null || policies.length === 0} className="mt-4 w-full rounded-lg bg-cyan-500 px-3 py-2 text-xs font-bold text-slate-950 disabled:cursor-not-allowed disabled:opacity-50">
                {busyAction === 'create' ? 'Creating…' : 'Create open case'}
              </button>
            </form>
          ) : null}
        </aside>

        <div className="min-w-0 space-y-5">
          {!selectedCase ? (
            <div className="rounded-2xl border border-dashed border-slate-700 bg-slate-900/60 p-10 text-center">
              <h3 className="font-bold text-white">Select or create a case</h3>
              <p className="mt-2 text-sm text-slate-400">The workspace reads cases you own or that explicitly assign you as reviewer.</p>
            </div>
          ) : (
            <>
              <section className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div className="min-w-0">
                    <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-cyan-300">{selectedCase.subject_type} / {selectedCase.subject_key}</p>
                    <h3 className="mt-1 break-words text-xl font-bold text-white">{selectedCase.title}</h3>
                    <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-400">{selectedCase.purpose}</p>
                  </div>
                  <StatusPill value={selectedCase.status} />
                </div>
                <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-3">
                  <div className="rounded-lg bg-slate-950/70 p-3"><dt className="text-slate-500">Policy</dt><dd className="mt-1 font-mono text-slate-200">{selectedCase.policy_key} {selectedCase.policy_version}</dd></div>
                  <div className="rounded-lg bg-slate-950/70 p-3"><dt className="text-slate-500">Required roles</dt><dd className="mt-1 font-bold text-slate-200">{selectedCase.required_roles.length}</dd></div>
                  <div className="rounded-lg bg-slate-950/70 p-3"><dt className="text-slate-500">Updated</dt><dd className="mt-1 text-slate-200">{formatTimestamp(selectedCase.updated_at)}</dd></div>
                </dl>
                <p className="mt-3 break-all text-xs text-slate-400">Independent reviewer: {selectedCase.assigned_reviewer_id ?? 'Unassigned — attestation unavailable'}</p>
                <div className="mt-4 flex flex-wrap gap-2">
                  <button type="button" onClick={() => void assessSelectedCase()} disabled={busyAction !== null || loadingDetails || selectedCase.status === 'ARCHIVED'} className="rounded-lg bg-cyan-500 px-3 py-2 text-xs font-bold text-slate-950 disabled:cursor-not-allowed disabled:opacity-50">
                    {busyAction === 'assess' ? 'Assessing…' : 'Run policy assessment'}
                  </button>
                  <button type="button" onClick={() => void exportSelectedBundle()} disabled={busyAction !== null || !assessment} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-semibold text-slate-200 disabled:cursor-not-allowed disabled:opacity-40">
                    {busyAction === 'export' ? 'Exporting…' : 'Download signed bundle'}
                  </button>
                  <button type="button" onClick={() => void verifySelectedBundle()} disabled={busyAction !== null || !assessment} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-semibold text-slate-200 disabled:cursor-not-allowed disabled:opacity-40">
                    {busyAction === 'verify' ? 'Verifying…' : 'Verify checksum & signature'}
                  </button>
                </div>
              </section>

              {loadingDetails ? <p className="rounded-xl border border-slate-800 bg-slate-900 p-4 text-sm text-slate-400">Loading stored evidence, timeline, and latest assessment…</p> : null}

              {assessment ? (
                <section className="rounded-2xl border border-slate-800 bg-slate-900 p-5" aria-labelledby="assurance-seal-title">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-[10px] font-mono uppercase tracking-[0.18em] text-cyan-300">Immutable assessment seal</p>
                      <h3 id="assurance-seal-title" className="mt-1 text-lg font-bold text-white">Snapshot {assessment.sequence_no}</h3>
                    </div>
                    <StatusPill value={assessment.decision_state} />
                  </div>
                  <dl className="mt-4 space-y-2 text-xs">
                    <div className="grid gap-1 sm:grid-cols-[9rem_1fr]"><dt className="text-slate-500">Assessed</dt><dd className="text-slate-300">{formatTimestamp(assessment.assessed_at)}</dd></div>
                    <div className="grid gap-1 sm:grid-cols-[9rem_1fr]"><dt className="text-slate-500">Algorithm / key</dt><dd className="font-mono text-slate-300">{assessment.signing_algorithm} / {assessment.signing_key_id}</dd></div>
                    <div className="grid gap-1 sm:grid-cols-[9rem_1fr]"><dt className="text-slate-500">Bundle checksum</dt><dd className="break-all font-mono text-[10px] text-slate-300">{assessment.bundle_checksum}</dd></div>
                    <div className="grid gap-1 sm:grid-cols-[9rem_1fr]"><dt className="text-slate-500">Signature</dt><dd className="break-all font-mono text-[10px] text-slate-300">{assessment.bundle_signature}</dd></div>
                  </dl>
                  {assessment.findings.length > 0 ? (
                    <div className="mt-4 space-y-2">
                      <h4 className="text-xs font-bold uppercase tracking-wide text-slate-300">Findings</h4>
                      {assessment.findings.map((finding) => (
                        <div key={finding.id} className="rounded-lg border border-slate-800 bg-slate-950/60 p-3">
                          <div className="flex flex-wrap items-center justify-between gap-2"><span className="font-mono text-[10px] text-slate-400">{finding.code}</span><StatusPill value={finding.severity} /></div>
                          <p className="mt-1 text-xs leading-relaxed text-slate-300">{finding.message}</p>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </section>
              ) : null}

              {assessment && selectedCase.assigned_reviewer_id ? (
                <section className="rounded-2xl border border-slate-800 bg-slate-900 p-5" aria-labelledby="independent-review-title">
                  <h3 id="independent-review-title" className="font-bold text-white">Independent review</h3>
                  <p className="mt-2 text-xs text-slate-400">The assigned reviewer must sign in with an authorized approver role. Each assessment accepts one final review; the creator cannot review their own case.</p>
                  <label className="mt-3 block text-xs text-slate-300">Review statement
                    <textarea minLength={12} maxLength={4000} rows={3} value={reviewStatement} onChange={(event) => setReviewStatement(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white" />
                  </label>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button type="button" onClick={() => void reviewSelectedCase('ATTESTED')} disabled={busyAction !== null || loadingDetails || reviewStatement.trim().length < 12 || selectedCase.status !== 'ASSESSED' || assessment.decision_state !== 'REVIEWABLE'} className="rounded-lg bg-cyan-500 px-3 py-2 text-xs font-bold text-slate-950 disabled:opacity-40">Attest evidence review</button>
                    <button type="button" onClick={() => void reviewSelectedCase('RETURNED')} disabled={busyAction !== null || loadingDetails || reviewStatement.trim().length < 12 || selectedCase.status !== 'ASSESSED'} className="rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-200 disabled:opacity-40">Return for correction</button>
                  </div>
                </section>
              ) : null}

              {verification ? (
                <section className={`rounded-2xl border p-5 ${verification.verified ? 'border-emerald-500/30 bg-emerald-950/20' : 'border-rose-500/40 bg-rose-950/20'}`} aria-labelledby="assurance-verification-title">
                  <div className="flex items-start justify-between gap-3">
                    <div><p className="text-[10px] font-mono uppercase tracking-[0.18em] text-slate-400">Server-side recomputation</p><h3 id="assurance-verification-title" className="mt-1 text-lg font-bold text-white">Bundle verification</h3></div>
                    <StatusPill value={verification.verified ? 'VERIFIED' : 'INVALID'} />
                  </div>
                  <div className="mt-4 grid gap-2 md:grid-cols-3">
                    <VerificationCheck label="Bundle checksum" valid={verification.bundle_checksum_valid} />
                    <VerificationCheck label="Bundle signature" valid={verification.bundle_signature_valid} />
                    <VerificationCheck label="Linked evidence integrity" valid={verification.evidence_integrity_valid} />
                  </div>
                  {verification.invalid_evidence_record_ids.length > 0 ? <p className="mt-3 break-all text-xs text-rose-200">Invalid evidence records: {verification.invalid_evidence_record_ids.join(', ')}</p> : null}
                  {verification.invalid_review_receipt_ids.length > 0 ? <p className="mt-2 break-all text-xs text-rose-200">Invalid review receipts: {verification.invalid_review_receipt_ids.join(', ')}</p> : null}
                </section>
              ) : null}

              <div className="grid gap-5 lg:grid-cols-2">
                <AssuranceMatrixPanel selectedCase={selectedCase} evidence={evidence} assessment={assessment} />
                <TimelinePanel events={events} />
              </div>
              <EvidenceSourcesPanel evidence={evidence} />
            </>
          )}
        </div>
      </div>
    </section>
  )
}

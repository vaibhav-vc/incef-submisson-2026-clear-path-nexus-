import { useCallback, useEffect, useMemo, useState } from 'react'
import { fetchRouteEvidenceKit } from '../services/api'
import type { ProvenanceSummary, RouteEvidence, RouteEvidenceKit } from '../types/route'
import type { EvidenceDecisionState, EvidenceKitStatus } from '../types/status'
import StatusBadge from './status/StatusBadge'

interface JourneyLeg {
  routeId: string
  kit: RouteEvidenceKit | null
  cached: boolean
  error: string | null
}

interface JourneyEvidenceBundle {
  format_version: 'EVIDENCE_JOURNEY_V1'
  journey_manifest: {
    route_ids: string[]
    legs: Array<{
      sequence: number
      route_id: string
      manifest_checksum: string | null
      decision_state: EvidenceDecisionState | 'UNAVAILABLE'
      reason_codes: string[]
    }>
  }
  journey_manifest_checksum: string
  integrity: { verified: boolean; leg_count: number; complete_leg_count: number }
  legs: Array<{ route_id: string; evidence_kit: RouteEvidenceKit | null }>
}

function stableJson(value: unknown): string {
  const sortValue = (item: unknown): unknown => {
    if (Array.isArray(item)) return item.map(sortValue)
    if (item !== null && typeof item === 'object') {
      return Object.fromEntries(
        Object.entries(item as Record<string, unknown>)
          .sort(([left], [right]) => left.localeCompare(right))
          .map(([key, nested]) => [key, sortValue(nested)]),
      )
    }
    return item
  }
  return `${JSON.stringify(sortValue(value), null, 2)}\n`
}

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

function safeFilePart(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]/g, '_')
}

function cacheKey(routeId: string): string {
  return `clearpath:evidence-kit:v1:${safeFilePart(routeId)}`
}

function readCachedKit(routeId: string): RouteEvidenceKit | null {
  try {
    const raw = sessionStorage.getItem(cacheKey(routeId))
    if (!raw) return null
    const parsed = JSON.parse(raw) as RouteEvidenceKit
    return parsed.manifest?.route_id === routeId && parsed.provider_refetch_required === false ? parsed : null
  } catch {
    return null
  }
}

function downloadBundle(bundle: JourneyEvidenceBundle) {
  const checksum = safeFilePart(bundle.journey_manifest_checksum).slice(0, 16) || 'no-checksum'
  const filename = `evidence-journey-${checksum}.json`
  const url = URL.createObjectURL(new Blob([stableJson(bundle)], { type: 'application/json;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

function EvidenceRecords({ evidence }: { evidence: RouteEvidence }) {
  return (
    <div className="space-y-4">
      {evidence.components.map((component) => (
        <article key={component.role} className="rounded-xl border border-slate-800 bg-slate-900 p-4">
          <div className="flex items-center justify-between gap-3">
            <h4 className="font-semibold text-slate-100">{component.label}</h4>
            <StatusBadge value={component.status} />
          </div>
          <p className="mt-1 text-xs text-slate-400">{component.explanation}</p>
          <div className="mt-3 space-y-2">
            {evidence.records.filter((record) => component.record_ids.includes(record.id)).map((record) => (
              <div key={record.id} className="rounded-lg bg-slate-950 p-3 text-xs">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-mono text-cyan-300">{record.entity_type}</span>
                  <span className="flex flex-wrap gap-1">
                    <StatusBadge value={record.canonical_source_type} domain="source" />
                    <StatusBadge value={record.freshness.state} domain="freshness" />
                  </span>
                </div>
                <p className="mt-1 text-slate-400">Source: {record.source?.label ?? 'Stored derived record'}</p>
                {record.excluded_reason ? <p className="mt-1 text-amber-300">Excluded: {record.excluded_reason}</p> : null}
              </div>
            ))}
          </div>
        </article>
      ))}
      {evidence.warnings.map((warning) => <p key={warning} className="rounded-lg border border-amber-800/50 bg-amber-950/20 p-3 text-xs text-amber-200">{warning}</p>)}
    </div>
  )
}

const DECISION_PRIORITY: Record<EvidenceDecisionState, number> = {
  READY: 0,
  HOLD: 1,
  UNAVAILABLE: 2,
  HARD_BLOCKED: 3,
}

export default function DataTrustCard({ routeIds, summary }: { routeIds: string[]; summary: ProvenanceSummary }) {
  const routeKey = JSON.stringify(Array.from(new Set(routeIds.filter(Boolean))))
  const normalizedRouteIds = useMemo(() => JSON.parse(routeKey) as string[], [routeKey])
  const [legs, setLegs] = useState<JourneyLeg[]>([])
  const [bundle, setBundle] = useState<JourneyEvidenceBundle | null>(null)
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [rootError, setRootError] = useState<string | null>(null)

  const loadJourney = useCallback(async () => {
    setLoading(true)
    setRootError(null)
    setBundle(null)

    const loadedLegs = await Promise.all(normalizedRouteIds.map(async (routeId): Promise<JourneyLeg> => {
      try {
        const kit = await fetchRouteEvidenceKit(routeId)
        sessionStorage.setItem(cacheKey(routeId), JSON.stringify(kit))
        return { routeId, kit, cached: false, error: null }
      } catch {
        const cachedKit = readCachedKit(routeId)
        return {
          routeId,
          kit: cachedKit,
          cached: cachedKit !== null,
          error: cachedKit
            ? 'Live retrieval unavailable; using this session’s stored integrity kit.'
            : 'Evidence kit unavailable. This leg must not be treated as ready.',
        }
      }
    }))

    setLegs(loadedLegs)
    const manifest: JourneyEvidenceBundle['journey_manifest'] = {
      route_ids: normalizedRouteIds,
      legs: loadedLegs.map((leg, index) => ({
        sequence: index + 1,
        route_id: leg.routeId,
        manifest_checksum: leg.kit?.manifest_checksum ?? null,
        decision_state: leg.kit?.decision_state ?? 'UNAVAILABLE',
        reason_codes: leg.kit?.reason_codes ?? ['EVIDENCE_KIT_UNAVAILABLE'],
      })),
    }

    try {
      const rootChecksum = await sha256Hex(stableJson(manifest))
      const completeLegCount = loadedLegs.filter((leg) => leg.kit !== null).length
      setBundle({
        format_version: 'EVIDENCE_JOURNEY_V1',
        journey_manifest: manifest,
        journey_manifest_checksum: rootChecksum,
        integrity: {
          verified: completeLegCount === loadedLegs.length && loadedLegs.every((leg) => leg.kit?.integrity.verified),
          leg_count: loadedLegs.length,
          complete_leg_count: completeLegCount,
        },
        legs: loadedLegs.map((leg) => ({ route_id: leg.routeId, evidence_kit: leg.kit })),
      })
    } catch {
      setRootError('The journey root checksum could not be computed. Export is unavailable and the journey is not ready.')
    } finally {
      setLoading(false)
    }
  }, [normalizedRouteIds])

  useEffect(() => {
    void loadJourney()
  }, [loadJourney, routeKey])

  const decisionState = legs.reduce<EvidenceDecisionState>((worst, leg) => {
    const current = leg.kit?.decision_state ?? 'UNAVAILABLE'
    return DECISION_PRIORITY[current] > DECISION_PRIORITY[worst] ? current : worst
  }, 'READY')

  const kitStatus = legs.some((leg) => leg.kit === null)
    ? 'UNAVAILABLE'
    : legs.some((leg) => leg.kit?.kit_status !== 'HOT') ? 'DEGRADED' : 'HOT'
  const typedKitStatus = kitStatus as EvidenceKitStatus
  const traced = legs.reduce((total, leg) => total + (leg.kit?.evidence?.traceability.traceability.traced ?? 0), 0)
  const traceTotal = legs.reduce((total, leg) => total + (leg.kit?.evidence?.traceability.traceability.total ?? 0), 0)
  const traceCoverage = traceTotal > 0 ? Math.round((traced / traceTotal) * 100) : summary.traceability.coverage_pct
  const displayTraced = traceTotal > 0 ? traced : summary.traceability.traced
  const displayTotal = traceTotal > 0 ? traceTotal : summary.traceability.total
  const hasCachedLeg = legs.some((leg) => leg.cached)
  const hasMissingLeg = legs.some((leg) => leg.kit === null)

  return (
    <>
      <div className="rounded-xl border border-cyan-500/30 bg-cyan-950/20 p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-[10px] font-mono uppercase tracking-wider text-cyan-300">Journey evidence bundle</p>
              {!loading ? <StatusBadge value={typedKitStatus} variant="soft" /> : null}
              {!loading ? <StatusBadge value={decisionState} variant="soft" /> : null}
            </div>
            <p className="mt-1 text-sm font-semibold text-white">
              {normalizedRouteIds.length} {normalizedRouteIds.length === 1 ? 'leg' : 'legs'} · {displayTraced} / {displayTotal} decision inputs traced
            </p>
            <p className="text-[11px] text-slate-400">{traceCoverage}% traced from stored evidence</p>
          </div>
          <button type="button" onClick={() => setOpen(true)} className="rounded-lg bg-cyan-500 px-3 py-2 text-xs font-bold text-slate-950">Inspect journey evidence</button>
        </div>
        {loading ? <p className="mt-3 text-[11px] text-cyan-300">Verifying every route leg and computing the journey root…</p> : null}
        {hasCachedLeg ? <p className="mt-3 text-[11px] text-amber-300">At least one leg is shown from this session’s integrity cache because live retrieval is unavailable.</p> : null}
        {hasMissingLeg || rootError ? <p className="mt-3 text-[11px] text-rose-300">{rootError ?? 'One or more evidence kits are unavailable. Journey state is UNAVAILABLE.'}</p> : null}
        {summary.warnings[0] ? <p className="mt-3 text-[11px] text-amber-300">{summary.warnings[0]}</p> : null}
      </div>

      {open ? (
        <div className="fixed inset-0 z-[1000] flex justify-end bg-slate-950/75" onClick={() => setOpen(false)}>
          <section role="dialog" aria-modal="true" aria-labelledby="journey-evidence-title" className="h-full w-full max-w-2xl overflow-y-auto border-l border-slate-700 bg-slate-950 p-5 shadow-2xl" onClick={(event) => event.stopPropagation()}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 id="journey-evidence-title" className="text-xl font-bold text-white">Journey evidence bundle</h2>
                <p className="text-xs text-slate-400">One integrity root covering {normalizedRouteIds.length} stored route {normalizedRouteIds.length === 1 ? 'leg' : 'legs'}.</p>
              </div>
              <button type="button" onClick={() => setOpen(false)} className="text-sm text-slate-400 hover:text-white">Close</button>
            </div>

            {loading ? <p className="mt-6 text-sm text-slate-400">Loading stored evidence and computing the journey root…</p> : null}
            {bundle ? (
              <section className="mt-5 rounded-xl border border-cyan-500/30 bg-cyan-950/20 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Journey state</p>
                    <div className="mt-2 flex flex-wrap gap-2"><StatusBadge value={typedKitStatus} variant="soft" /><StatusBadge value={decisionState} variant="soft" /></div>
                  </div>
                  <button type="button" disabled={Boolean(rootError)} onClick={() => downloadBundle(bundle)} className="rounded-lg bg-cyan-500 px-3 py-2 text-xs font-bold text-slate-950 disabled:cursor-not-allowed disabled:opacity-40">Download deterministic bundle</button>
                </div>
                <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-2">
                  <div><dt className="text-slate-500">Format</dt><dd className="mt-1 font-mono text-slate-200">{bundle.format_version}</dd></div>
                  <div><dt className="text-slate-500">Integrity</dt><dd className={`mt-1 font-semibold ${bundle.integrity.verified ? 'text-emerald-300' : 'text-rose-300'}`}>{bundle.integrity.verified ? 'VERIFIED' : 'INCOMPLETE'} · {bundle.integrity.complete_leg_count}/{bundle.integrity.leg_count} legs</dd></div>
                </dl>
                <div className="mt-3"><p className="text-[10px] uppercase tracking-wider text-slate-500">Journey manifest SHA-256</p><p className="mt-1 break-all font-mono text-[10px] text-cyan-300">{bundle.journey_manifest_checksum}</p></div>
              </section>
            ) : null}
            {rootError ? <p className="mt-4 rounded-xl border border-rose-700 bg-rose-950/30 p-4 text-sm text-rose-200">{rootError}</p> : null}

            <div className="mt-5 space-y-5">
              {legs.map((leg, index) => (
                <section key={leg.routeId} className="rounded-xl border border-slate-700 bg-slate-900/40 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-3">
                    <div><p className="text-[10px] uppercase tracking-wider text-slate-500">Leg {index + 1}</p><h3 className="mt-1 break-all font-mono text-sm text-white">{leg.routeId}</h3></div>
                    <div className="flex gap-2">{leg.cached ? <StatusBadge value="CACHED" variant="soft" /> : null}<StatusBadge value={leg.kit?.decision_state ?? 'UNAVAILABLE'} variant="soft" /></div>
                  </div>
                  {leg.error ? <p className={`mt-4 rounded-lg border p-3 text-xs ${leg.kit ? 'border-amber-800/50 bg-amber-950/20 text-amber-200' : 'border-rose-700/60 bg-rose-950/20 text-rose-200'}`}>{leg.error}</p> : null}
                  {leg.kit ? (
                    <div className="mt-4 space-y-4">
                      <div><p className="text-[10px] uppercase tracking-wider text-slate-500">Leg manifest SHA-256</p><p className="mt-1 break-all font-mono text-[10px] text-cyan-300">{leg.kit.manifest_checksum}</p></div>
                      {leg.kit.evidence ? <EvidenceRecords evidence={leg.kit.evidence} /> : <p className="rounded-lg border border-rose-700/60 bg-rose-950/20 p-3 text-xs text-rose-200">No stored route evidence is present for this leg.</p>}
                      {leg.kit.limitations.length > 0 ? <div className="rounded-xl border border-amber-800/50 bg-amber-950/20 p-4"><h4 className="text-xs font-bold uppercase tracking-wider text-amber-300">Known limitations</h4><ul className="mt-2 list-inside list-disc space-y-1 text-xs text-amber-100">{leg.kit.limitations.map((item) => <li key={item}>{item}</li>)}</ul></div> : null}
                    </div>
                  ) : null}
                </section>
              ))}
            </div>

            <button type="button" onClick={() => void loadJourney()} className="mt-5 rounded-lg border border-cyan-500/50 px-3 py-2 text-xs font-bold text-cyan-200">Re-verify all legs</button>
          </section>
        </div>
      ) : null}
    </>
  )
}

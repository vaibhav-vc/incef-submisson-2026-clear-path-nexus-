import { useCallback, useEffect, useState } from 'react'
import { fetchRouteEvidenceKit, fetchSchedules, synchronizeTrainSchedule, type TrainSyncState } from '../services/api'
import { evidenceKitBlockReason, type RouteEvidenceKit, type TrainSchedule } from '../types/route'
import StatusBadge from './status/StatusBadge'
import TrainSyncPanel from './TrainSyncPanel'

interface Props {
  onBack: () => void
  onHistory: () => void
}

export default function ScheduleBoard({ onBack, onHistory }: Props) {
  const [items, setItems] = useState<TrainSchedule[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [syncStates, setSyncStates] = useState<Record<string, TrainSyncState>>({})
  const [syncing, setSyncing] = useState<string | null>(null)
  const [evidenceKits, setEvidenceKits] = useState<Record<string, RouteEvidenceKit | null>>({})

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const schedules = await fetchSchedules()
      setItems(schedules)
      const routeIds = [...new Set(schedules.flatMap((schedule) => schedule.generated_route_id ? [schedule.generated_route_id] : []))]
      const kits = await Promise.all(routeIds.map(async (routeId) => {
        try {
          return [routeId, await fetchRouteEvidenceKit(routeId)] as const
        } catch {
          return [routeId, null] as const
        }
      }))
      setEvidenceKits(Object.fromEntries(kits))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load schedules')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const synchronize = async (id: string) => {
    setSyncing(id)
    setError(null)
    try {
      const state = await synchronizeTrainSchedule(id)
      setSyncStates((current) => ({ ...current, [id]: state }))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Train synchronization failed')
    } finally {
      setSyncing(null)
    }
  }

  return (
    <div className="min-h-screen bg-[#121a2e] text-white">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-blue-800/60 bg-gradient-to-r from-blue-950 via-blue-900 to-indigo-950 px-6 py-4">
        <div>
          <h1 className="text-xl font-bold">Timetable Impact Research</h1>
          <p className="text-xs font-mono text-blue-300">Non-vital schedule comparison · no movement authority or train dispatch</p>
        </div>
        <div className="flex gap-2">
          <button onClick={onBack} className="rounded border border-slate-600 px-3 py-2 text-xs font-mono hover:bg-slate-800">Route Planner</button>
          <button onClick={onHistory} className="rounded border border-blue-500/50 px-3 py-2 text-xs font-mono text-blue-300 hover:bg-blue-950/50">Evidence History</button>
          <button onClick={() => void load()} className="rounded bg-blue-600 px-3 py-2 text-xs font-mono hover:bg-blue-500">Refresh</button>
        </div>
      </header>

      <main className="mx-auto max-w-7xl p-6">
        {error ? <div className="mb-4 rounded border border-rose-600/40 bg-rose-950/30 p-3 text-sm text-rose-300">{error}</div> : null}
        {loading ? <p className="font-mono text-slate-400">Loading schedules…</p> : null}
        <div className="grid gap-4 md:grid-cols-2">
          {items.map((item) => {
            const evidenceKit = item.generated_route_id ? evidenceKits[item.generated_route_id] : null
            const evidenceBlock = item.generated_route_id
              ? evidenceKitBlockReason(evidenceKit)
              : 'This schedule is not linked to an EvidenceGate route.'
            return (
            <article key={item.id} className="rounded-xl border border-slate-700 bg-slate-900/80 p-5 shadow-xl">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="font-mono text-lg font-bold text-blue-300">{item.train_code}</h2>
                    {item.is_demo ? <span className="rounded bg-slate-700 px-2 py-0.5 text-[9px] font-mono uppercase text-slate-300">Demo</span> : null}
                  </div>
                  <p className="text-sm text-slate-300">{item.train_name}</p>
                  <p className="mt-2 font-mono text-sm">{item.source_station_code} → {item.dest_station_code}</p>
                </div>
                <StatusBadge value={item.conflict_status} domain="conflict" className="px-2.5 py-1 font-mono" />
              </div>

              <div className="mt-4 grid grid-cols-2 gap-3 rounded-lg bg-slate-950/60 p-3 font-mono text-xs">
                <div><span className="block text-slate-500">Departure</span>{new Date(item.scheduled_departure).toLocaleString()}</div>
                <div><span className="block text-slate-500">Arrival</span>{new Date(item.scheduled_arrival).toLocaleString()}</div>
                <div><span className="block text-slate-500">State</span>{item.schedule_status}</div>
                <div><span className="block text-slate-500">Berth window</span>{item.berth_window_start ? 'Operator supplied' : 'Not supplied'}</div>
              </div>

              {item.conflict_reason ? (
                <div className="mt-3 rounded-lg border border-slate-700 bg-slate-950/50 p-3 text-xs font-mono text-slate-300">
                  {item.conflict_reason}
                </div>
              ) : null}

              {syncStates[item.id] ? <TrainSyncPanel state={syncStates[item.id]} /> : null}

              <button type="button" onClick={() => void synchronize(item.id)} disabled={syncing === item.id} className="mt-4 w-full rounded-lg border border-cyan-700 px-4 py-2 text-xs font-semibold text-cyan-300 disabled:opacity-40">
                {syncing === item.id ? 'Synchronizing…' : 'Sync supplementary train status'}
              </button>

              <div className="mt-4 rounded-lg border border-cyan-800/70 bg-cyan-950/20 p-3 text-xs text-cyan-100">
                <p className="font-semibold">Research-only schedule impact</p>
                <p className="mt-1 text-cyan-200/80">
                  {evidenceBlock
                    ? evidenceKit ? `${evidenceKit.decision_state} · ${evidenceKit.kit_status}` : 'Evidence unavailable'
                    : 'Evidence is reviewable. Export it for comparison; authorized railway systems retain control.'}
                </p>
              </div>
            </article>
            )
          })}
        </div>
      </main>
    </div>
  )
}

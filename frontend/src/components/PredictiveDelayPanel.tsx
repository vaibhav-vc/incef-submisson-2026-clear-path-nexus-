import { useEffect, useState } from 'react'
import { api, fetchRouteHistory } from '../services/api'
import type { RouteHistoryItem } from '../types/route'

interface DelayPredictionData {
  status: 'AVAILABLE' | 'UNAVAILABLE'
  source: 'STORED_ROUTE_FEATURES'
  route_id: string
  predicted_delay_minutes: number | null
  confidence_pct: number | null
  risk_level: 'LOW' | 'MODERATE' | 'HIGH' | 'CRITICAL' | null
  primary_bottleneck_segment: string | null
  weather_impact_pct: number | null
  congestion_impact_pct: number | null
  optimal_dispatch_window: string | null
  limitation: string
}

const RISK_STYLE: Record<NonNullable<DelayPredictionData['risk_level']>, string> = {
  LOW: 'border-emerald-700 bg-emerald-950/40 text-emerald-300',
  MODERATE: 'border-amber-700 bg-amber-950/40 text-amber-300',
  HIGH: 'border-orange-700 bg-orange-950/40 text-orange-300',
  CRITICAL: 'border-rose-700 bg-rose-950/40 text-rose-300',
}

export default function PredictiveDelayPanel() {
  const [routes, setRoutes] = useState<RouteHistoryItem[]>([])
  const [routeId, setRouteId] = useState('')
  const [routesLoading, setRoutesLoading] = useState(true)
  const [routeError, setRouteError] = useState<string | null>(null)
  const [data, setData] = useState<DelayPredictionData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchRouteHistory()
      .then(setRoutes)
      .catch(() => setRouteError('Owned route history is unavailable. Prediction is disabled.'))
      .finally(() => setRoutesLoading(false))
  }, [])

  const runPrediction = async () => {
    if (!routeId) {
      setData(null)
      setError('Select a stored route evaluation.')
      return
    }
    setLoading(true)
    setData(null)
    setError(null)
    try {
      const { data: response } = await api.post<DelayPredictionData>('/predictive/delay', { route_id: routeId })
      setData(response)
    } catch (requestError) {
      setError(requestError instanceof Error ? `Prediction unavailable: ${requestError.message}` : 'Prediction unavailable. No estimate has been substituted.')
    } finally {
      setLoading(false)
    }
  }

  const predictionAvailable = data?.status === 'AVAILABLE' && data.predicted_delay_minutes != null

  return (
    <section className="overflow-hidden rounded-2xl border border-slate-800 bg-[#0b1220] text-slate-100 shadow-xl" aria-labelledby="delay-outlook-title">
      <header className="flex flex-col gap-5 border-b border-slate-800 px-5 py-5 md:flex-row md:items-end md:justify-between md:px-7">
        <div className="max-w-2xl">
          <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.2em] text-cyan-400">Stored-evidence advisory</p>
          <h2 id="delay-outlook-title" className="mt-2 text-2xl font-semibold tracking-tight text-white">Corridor delay outlook</h2>
          <p className="mt-2 text-sm leading-6 text-slate-400">The estimate is derived only from an owned, previously evaluated route and its stored decision features.</p>
        </div>
        <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-slate-400">
          <span className={`h-2 w-2 rounded-full ${routeError ? 'bg-rose-500' : routesLoading ? 'bg-slate-500' : 'bg-emerald-400'}`} aria-hidden="true" />
          {routeError ? 'Route source unavailable' : routesLoading ? 'Loading owned routes' : `${routes.length} owned routes loaded`}
        </div>
      </header>

      <div className="grid lg:grid-cols-[minmax(300px,0.7fr)_minmax(0,1.3fr)]">
        <form className="border-b border-slate-800 p-5 lg:border-b-0 lg:border-r lg:p-7" onSubmit={(event) => { event.preventDefault(); void runPrediction() }}>
          <fieldset disabled={routesLoading || Boolean(routeError) || loading} className="space-y-5 disabled:opacity-60">
            <legend className="mb-5 font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Required stored route</legend>
            <label className="block">
              <span className="mb-2 block text-xs font-medium text-slate-300">Route evaluation</span>
              <select required value={routeId} onChange={(event) => { setRouteId(event.target.value); setData(null); setError(null) }} className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-white">
                <option value="">Select an owned route</option>
                {routes.map((route) => <option key={route.id} value={route.id}>{route.source_station_code} → {route.dest_station_code} · {new Date(route.created_at).toLocaleString()}</option>)}
              </select>
            </label>
            <p className="text-xs leading-5 text-slate-500">Cargo, weather, congestion, and segment features are read from the signed route record. The browser cannot replace them.</p>
          </fieldset>

          {routeError ? <p role="alert" className="mt-5 rounded-lg border border-rose-800 bg-rose-950/30 p-3 text-xs text-rose-200">{routeError}</p> : null}
          {error ? <p role="alert" className="mt-5 rounded-lg border border-rose-800 bg-rose-950/30 p-3 text-xs text-rose-200">{error}</p> : null}

          <button type="submit" disabled={!routeId || loading || Boolean(routeError)} className="mt-6 w-full rounded-lg border border-cyan-500 bg-cyan-500 px-4 py-3 text-xs font-bold uppercase tracking-wider text-slate-950 transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:border-slate-700 disabled:bg-slate-800 disabled:text-slate-500">
            {loading ? 'Reading stored evidence…' : 'Calculate delay outlook'}
          </button>
        </form>

        <div className="min-h-[390px] p-5 md:p-7" aria-live="polite">
          {data && predictionAvailable ? (
            <div className="flex h-full flex-col">
              <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-800 pb-6">
                <div>
                  <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500">Estimated corridor delay · {data.source}</p>
                  <p className="mt-2 text-5xl font-semibold tracking-[-0.06em] text-white">+{data.predicted_delay_minutes}<span className="ml-2 text-lg font-medium tracking-normal text-slate-500">min</span></p>
                </div>
                {data.risk_level ? <span className={`rounded-full border px-3 py-1 font-mono text-[10px] font-bold ${RISK_STYLE[data.risk_level]}`}>{data.risk_level} RISK</span> : null}
              </div>

              <dl className="grid gap-px overflow-hidden border-b border-slate-800 bg-slate-800 sm:grid-cols-3">
                <Metric label="Calibrated confidence" value={data.confidence_pct == null ? 'Unavailable' : `${data.confidence_pct}%`} />
                <Metric label="Weather contribution" value={data.weather_impact_pct == null ? 'Unavailable' : `${data.weather_impact_pct}%`} />
                <Metric label="Congestion contribution" value={data.congestion_impact_pct == null ? 'Unavailable' : `${data.congestion_impact_pct}%`} />
              </dl>

              <div className="grid flex-1 gap-6 pt-6 sm:grid-cols-2">
                <div><p className="text-[10px] uppercase tracking-wider text-slate-500">Primary bottleneck</p><p className="mt-2 text-sm font-semibold leading-6 text-slate-200">{data.primary_bottleneck_segment ?? 'Unavailable'}</p></div>
                <div><p className="text-[10px] uppercase tracking-wider text-slate-500">Official dispatch window</p><p className="mt-2 text-sm font-semibold leading-6 text-cyan-300">{data.optimal_dispatch_window ?? 'Unavailable'}</p></div>
              </div>
              <p className="mt-6 border-l-2 border-slate-700 pl-3 text-[11px] leading-5 text-slate-500">{data.limitation}</p>
            </div>
          ) : data ? (
            <div className="rounded-xl border border-rose-800 bg-rose-950/30 p-6">
              <p className="font-mono text-[10px] font-bold uppercase tracking-wider text-rose-300">Prediction unavailable</p>
              <p className="mt-3 text-sm leading-6 text-slate-300">{data.limitation}</p>
              <p className="mt-3 font-mono text-[10px] text-slate-500">Source: {data.source} · No estimate substituted</p>
            </div>
          ) : (
            <div className="flex h-full min-h-[330px] flex-col justify-between rounded-xl border border-dashed border-slate-700 p-6">
              <div><p className="font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500">No estimate requested</p><h3 className="mt-3 max-w-md text-2xl font-medium tracking-tight text-slate-200">Select an owned route to analyze its stored evidence.</h3></div>
              <p className="max-w-lg text-sm leading-6 text-slate-500">No corridor, cargo, weather, congestion, or prediction value is prefilled in the browser.</p>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="bg-[#0b1220] px-4 py-5 first:pl-0"><dt className="text-[10px] uppercase tracking-wider text-slate-500">{label}</dt><dd className="mt-1 text-lg font-semibold text-slate-200">{value}</dd></div>
}

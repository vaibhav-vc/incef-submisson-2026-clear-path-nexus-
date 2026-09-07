import { useEffect, useMemo, useState } from 'react'
import { api, fetchStations } from '../services/api'
import type { Station } from '../types/route'

interface DustRiskData {
  status: 'AVAILABLE' | 'UNAVAILABLE'
  source: string
  location: string
  lat: number
  lon: number
  observed_at: string | null
  fetched_at: string
  dust_risk_index: number | null
  airborne_particulate_pm10: number | null
  visibility_km: number | null
  warning_level: 'SAFE' | 'ADVISORY' | 'SEVERE' | 'HAZARD' | null
  recommended_speed_limit_kmh: number | null
  operational_limitation: string
}

export default function DustStormRadarPanel() {
  const [stations, setStations] = useState<Station[]>([])
  const [stationId, setStationId] = useState('')
  const [location, setLocation] = useState('')
  const [lat, setLat] = useState('')
  const [lon, setLon] = useState('')
  const [directoryError, setDirectoryError] = useState<string | null>(null)
  const [data, setData] = useState<DustRiskData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchStations()
      .then(setStations)
      .catch(() => setDirectoryError('Live station directory is unavailable. Enter a named location and coordinates manually.'))
  }, [])

  const selectedStation = useMemo(
    () => stations.find((station) => station.id === stationId) ?? null,
    [stationId, stations],
  )

  const selectStation = (nextId: string) => {
    setStationId(nextId)
    const station = stations.find((item) => item.id === nextId)
    setLocation(station ? `${station.code} — ${station.name}` : '')
    setLat(station ? String(station.lat) : '')
    setLon(station ? String(station.lon) : '')
    setData(null)
    setError(null)
  }

  const requestObservation = async () => {
    const latitude = Number(lat)
    const longitude = Number(lon)
    if (!location.trim() || !Number.isFinite(latitude) || latitude < -90 || latitude > 90 || !Number.isFinite(longitude) || longitude < -180 || longitude > 180) {
      setData(null)
      setError('Provide a location name and valid latitude/longitude coordinates.')
      return
    }
    setLoading(true)
    setData(null)
    setError(null)
    try {
      const { data: response } = await api.get<DustRiskData>('/predictive/dust-risk', {
        params: { lat: latitude, lon: longitude, location: location.trim() },
      })
      setData(response)
    } catch (requestError) {
      setError(requestError instanceof Error ? `Dust observation unavailable: ${requestError.message}` : 'Dust observation unavailable. No values were substituted.')
    } finally {
      setLoading(false)
    }
  }

  const available = data?.status === 'AVAILABLE'

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900 p-6 text-slate-100 shadow-xl" aria-labelledby="dust-observation-title">
      <div className="mb-6 flex flex-col justify-between gap-4 md:flex-row md:items-start">
        <div>
          <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.18em] text-amber-400">Provider observation</p>
          <h2 id="dust-observation-title" className="mt-2 text-xl font-bold text-slate-100">Airborne particulate and dust conditions</h2>
          <p className="mt-1 text-xs leading-5 text-slate-400">Measurements are displayed only when returned by the configured air-quality provider.</p>
        </div>
        {data ? <span className={`rounded-full border px-3 py-1 font-mono text-[10px] font-bold ${available ? 'border-emerald-700 text-emerald-300' : 'border-rose-700 text-rose-300'}`}>{data.status} · {data.source}</span> : null}
      </div>

      <form className="grid gap-3 rounded-xl border border-slate-800 bg-slate-950/60 p-4 lg:grid-cols-[1.2fr_1.2fr_0.7fr_0.7fr_auto] lg:items-end" onSubmit={(event) => { event.preventDefault(); void requestObservation() }}>
        <label className="block">
          <span className="mb-1 block text-[11px] text-slate-400">Live station directory</span>
          <select value={stationId} onChange={(event) => selectStation(event.target.value)} className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white">
            <option value="">Manual location</option>
            {stations.map((station) => <option key={station.id} value={station.id}>{station.code} · {station.name}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-[11px] text-slate-400">Location name *</span>
          <input required value={location} onChange={(event) => { setLocation(event.target.value); setStationId(''); setData(null) }} className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white" placeholder="Operator-entered location" />
        </label>
        <label className="block">
          <span className="mb-1 block text-[11px] text-slate-400">Latitude *</span>
          <input required type="number" min="-90" max="90" step="any" value={lat} onChange={(event) => { setLat(event.target.value); setStationId(''); setData(null) }} className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white" />
        </label>
        <label className="block">
          <span className="mb-1 block text-[11px] text-slate-400">Longitude *</span>
          <input required type="number" min="-180" max="180" step="any" value={lon} onChange={(event) => { setLon(event.target.value); setStationId(''); setData(null) }} className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white" />
        </label>
        <button type="submit" disabled={loading} className="rounded-lg bg-amber-500 px-4 py-2 text-sm font-bold text-slate-950 disabled:opacity-50">{loading ? 'Requesting…' : 'Request observation'}</button>
      </form>

      {directoryError ? <p className="mt-3 text-xs text-amber-300">{directoryError}</p> : null}
      {error ? <p role="alert" className="mt-4 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs text-rose-300">{error}</p> : null}

      {data ? (
        <div className="mt-5">
          {!available ? (
            <div className="rounded-xl border border-rose-700/50 bg-rose-950/30 p-5">
              <p className="font-mono text-xs font-bold uppercase text-rose-300">Observation unavailable</p>
              <p className="mt-2 text-sm leading-6 text-slate-300">{data.operational_limitation}</p>
              <p className="mt-2 font-mono text-[10px] text-slate-500">Fetched {new Date(data.fetched_at).toLocaleString()} · No measurements or restrictions inferred</p>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
                <Metric label="Dust hazard index" value={data.dust_risk_index == null ? 'Unavailable' : `${data.dust_risk_index} / 100`} />
                <Metric label="Provider PM10" value={data.airborne_particulate_pm10 == null ? 'Unavailable' : `${data.airborne_particulate_pm10} µg/m³`} />
                <Metric label="Provider visibility" value={data.visibility_km == null ? 'Unavailable' : `${data.visibility_km} km`} />
                <Metric label="Official speed restriction" value={data.recommended_speed_limit_kmh == null ? 'Unavailable' : `${data.recommended_speed_limit_kmh} km/h`} />
              </div>
              <div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/60 p-4 text-xs leading-5 text-slate-400">
                <p><span className="text-slate-500">Classification:</span> {data.warning_level ?? 'Unavailable'}</p>
                <p><span className="text-slate-500">Observed:</span> {data.observed_at ? new Date(data.observed_at).toLocaleString() : 'Provider timestamp unavailable'}</p>
                <p className="mt-2 text-amber-200">{data.operational_limitation}</p>
              </div>
            </>
          )}
        </div>
      ) : null}
      {selectedStation ? <span className="sr-only">Selected live station {selectedStation.name}</span> : null}
    </section>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl border border-slate-800 bg-slate-950/80 p-4"><div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</div><div className="text-xl font-bold text-slate-100">{value}</div></div>
}

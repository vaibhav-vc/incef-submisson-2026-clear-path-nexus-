import { useCallback, useEffect, useMemo, useState } from 'react'
import MapViewer from './MapViewer'
import Simulator from './Simulator'
import ScoreGauge from './ScoreGauge'
import MetricBar from './MetricBar'
import LoadProfilePanel from './LoadProfilePanel'
import { approveRoute, dispatchJourney, fetchRouteEvidenceKit, fetchStations, simulateThreat } from '../services/api'
import { suggestRouteThroughWaypoints } from '../services/routePlanner'
import { evidenceKitBlockReason, type LocationMode, type OperatorLoadingWindow, type RouteSuggestResponse, type Station } from '../types/route'
import type { LoadProfile } from '../types/loadProfile'
import TrackIntelPanel from './TrackIntelPanel'
import { useLiveMapConditions } from '../hooks/useLiveMapConditions'
import { conditionsToZones } from '../maps/mapSymbolGuide'
import { findNearestStation } from '../utils/nearestStation'
import DataTrustCard from './DataTrustCard'

export default function CommandDashboard() {
  const [stations, setStations] = useState<Station[]>([])
  const [loadProfile, setLoadProfile] = useState<LoadProfile | null>(null)
  const [locationMode, setLocationMode] = useState<LocationMode>('station')
  const [locationStation, setLocationStation] = useState('')
  const [locationLat, setLocationLat] = useState('')
  const [locationLon, setLocationLon] = useState('')
  const [destinations, setDestinations] = useState<string[]>([])
  const [trainHours, setTrainHours] = useState('')
  const [portId, setPortId] = useState('')
  const [vesselId, setVesselId] = useState('')
  const [berthWindowStart, setBerthWindowStart] = useState('')
  const [berthWindowEnd, setBerthWindowEnd] = useState('')
  const [manifestReference, setManifestReference] = useState('')
  const [manifestSha256, setManifestSha256] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<RouteSuggestResponse | null>(null)
  const [routeApproved, setRouteApproved] = useState(false)
  const [approving, setApproving] = useState(false)
  const [evidenceDecision, setEvidenceDecision] = useState<string>('UNAVAILABLE')
  const [evidenceFailure, setEvidenceFailure] = useState<string | null>('Evidence has not been evaluated.')
  const [dispatching, setDispatching] = useState(false)
  const [dispatchComplete, setDispatchComplete] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [mapReady, setMapReady] = useState(false)

  const [stormSeverity, setStormSeverity] = useState(0)
  const [solarKp, setSolarKp] = useState(2)
  const [portCongestion, setPortCongestion] = useState(0)
  const [simLoading, setSimLoading] = useState(false)
  const [simScore, setSimScore] = useState<number | undefined>()
  const [simAlerts, setSimAlerts] = useState<string[]>([])
  const [simUnavailable, setSimUnavailable] = useState<string | undefined>()

  const stationList = stations

  useEffect(() => {
    fetchStations()
      .then((items) => {
        setStations(items)
        if (items.length > 0) {
          setLocationStation((current) => current || items[0].code)
          setDestinations((current) => current.length > 0 ? current : (items[1] ? [items[1].code] : []))
        }
      })
      .catch(() => {
        setStations([])
        setError('Live station data is unavailable. Routing is disabled until the backend recovers.')
      })
  }, [])

  const originCode = locationMode === 'station' ? locationStation : undefined

  const nearestStation = useMemo(() => {
    if (locationMode === 'station') return null
    const lat = parseFloat(locationLat)
    const lon = parseFloat(locationLon)
    if (Number.isNaN(lat) || Number.isNaN(lon)) return null
    return findNearestStation(stationList, lat, lon)
  }, [locationMode, locationLat, locationLon, stationList])

  const excludeOrigin = originCode ?? nearestStation?.station.code

  useEffect(() => {
    if (!excludeOrigin) return
    setDestinations((prev) => {
      const filtered = prev.filter((c) => c !== excludeOrigin)
      if (filtered.length === prev.length && filtered.length > 0) return prev
      if (filtered.length > 0) return filtered
      const next = stationList.map((s) => s.code).find((c) => c !== excludeOrigin)
      return next ? [next] : prev
    })
  }, [excludeOrigin, stationList])

  useEffect(() => {
    if (result) setMapReady(true)
  }, [result])

  useEffect(() => {
    setResult(null)
    setEvidenceDecision('UNAVAILABLE')
    setEvidenceFailure('Route inputs changed. Run a new evaluation.')
    setRouteApproved(false)
    setApproving(false)
    setDispatching(false)
    setDispatchComplete(false)
    setSimScore(undefined)
    setSimAlerts([])
    setSimUnavailable(undefined)
    setMapReady(false)
  }, [
    destinations,
    locationMode,
    locationStation,
    locationLat,
    locationLon,
    loadProfile?.id,
    portId,
    vesselId,
    berthWindowStart,
    berthWindowEnd,
    manifestReference,
    manifestSha256,
    trainHours,
  ])

  useEffect(() => {
    setSimScore(undefined)
    setSimAlerts([])
    setSimUnavailable(undefined)
  }, [stormSeverity, solarKp, portCongestion])

  const buildLocationInput = useCallback(() => {
    if (locationMode === 'station') {
      return { mode: 'station' as const, station_code: locationStation }
    }
    return {
      mode: locationMode,
      lat: parseFloat(locationLat),
      lon: parseFloat(locationLon),
    }
  }, [locationMode, locationStation, locationLat, locationLon])

  const destConflict =
    !!excludeOrigin && destinations.length > 0 && destinations.every((d) => d === excludeOrigin)

  const refreshEvidenceState = useCallback(async (routeIds: string[]) => {
    try {
      const kits = await Promise.all(routeIds.map(fetchRouteEvidenceKit))
      const blockedIndex = kits.findIndex((kit) => evidenceKitBlockReason(kit) !== null)
      const blockedKit = blockedIndex >= 0 ? kits[blockedIndex] : null
      const failure = blockedKit ? evidenceKitBlockReason(blockedKit) : null
      setEvidenceDecision(blockedKit?.decision_state ?? 'READY')
      setEvidenceFailure(failure)
      return {
        failure,
        blockedRouteId: blockedIndex >= 0 ? routeIds[blockedIndex] : null,
      }
    } catch (e) {
      setEvidenceDecision('UNAVAILABLE')
      setEvidenceFailure('Fresh evidence could not be retrieved from EvidenceGate.')
      throw e
    }
  }, [])

  const handleEvaluate = useCallback(async () => {
    if (!loadProfile) {
      setError('Select or create a load profile first.')
      return
    }
    if (destinations.length === 0) {
      setError('Add at least one destination.')
      return
    }
    if (destConflict) {
      setError('Destination cannot be the same as the current station.')
      return
    }
    const normalizedPortId = portId.trim()
    const normalizedVesselId = vesselId.trim()
    if (!normalizedPortId || !normalizedVesselId) {
      setError('Enter the actual port and vessel identifiers from the operating manifest.')
      return
    }
    const arrivalHours = Number(trainHours)
    if (!Number.isFinite(arrivalHours) || arrivalHours <= 0) {
      setError('Enter a valid train-arrival horizon greater than zero.')
      return
    }
    const normalizedManifestReference = manifestReference.trim()
    const normalizedManifestSha256 = manifestSha256.trim().toLowerCase()
    const windowEvidenceFields = [berthWindowStart.trim(), berthWindowEnd.trim(), normalizedManifestReference, normalizedManifestSha256]
    const hasAnyWindowEvidence = windowEvidenceFields.some(Boolean)
    const hasCompleteWindowEvidence = windowEvidenceFields.every(Boolean)
    if (hasAnyWindowEvidence && !hasCompleteWindowEvidence) {
      setError('Loading-window evidence requires start, end, manifest reference, and manifest SHA-256 together.')
      return
    }
    let loadingWindow: OperatorLoadingWindow | undefined
    if (hasCompleteWindowEvidence) {
      if (normalizedManifestReference.length < 3) {
        setError('Manifest reference must contain at least 3 characters.')
        return
      }
      if (!/^[0-9a-f]{64}$/.test(normalizedManifestSha256)) {
        setError('Manifest SHA-256 must be exactly 64 hexadecimal characters.')
        return
      }
      const start = new Date(berthWindowStart)
      const end = new Date(berthWindowEnd)
      if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime())) {
        setError('Enter a valid berth loading window.')
        return
      }
      if (end <= start) {
        setError('Berth loading-window end must be after its start.')
        return
      }
      loadingWindow = {
        start_time: start.toISOString(),
        end_time: end.toISOString(),
        manifest_reference: normalizedManifestReference,
        manifest_sha256: normalizedManifestSha256,
      }
    }
    if (locationMode !== 'station') {
      const lat = Number(locationLat)
      const lon = Number(locationLon)
      if (!Number.isFinite(lat) || !Number.isFinite(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
        setError('Capture GPS or enter valid latitude/longitude coordinates.')
        return
      }
    }

    setLoading(true)
    setError(null)
    setEvidenceDecision('UNAVAILABLE')
    setEvidenceFailure('Evidence verification is in progress.')
    setDispatchComplete(false)
    try {
      const data = await suggestRouteThroughWaypoints({
        cargo: {
          height: loadProfile.height,
          width: loadProfile.width,
          weight: loadProfile.weight,
        },
        destinationCodes: destinations,
        location: buildLocationInput(),
        portId: normalizedPortId,
        vesselId: normalizedVesselId,
        trainArrivalHours: arrivalHours,
        loadingWindow,
      })

      setResult(data)
      const routeIds = data.route_ids?.length ? data.route_ids : [data.route_id]
      await refreshEvidenceState(routeIds)
      setRouteApproved(false)
      setApproving(false)
      setSimScore(undefined)
      setSimAlerts([])
      setSimUnavailable(undefined)
      setMapReady(true)

    } catch (e) {
      setError(e instanceof Error ? e.message : 'Route suggestion failed')
    } finally {
      setLoading(false)
    }
  }, [
    loadProfile,
    destinations,
    destConflict,
    buildLocationInput,
    trainHours,
    locationMode,
    locationLat,
    locationLon,
    portId,
    vesselId,
    berthWindowStart,
    berthWindowEnd,
    manifestReference,
    manifestSha256,
    refreshEvidenceState,
  ])

  const handleSimulate = useCallback(async () => {
    if (!result) {
      setError('Run a live route evaluation before applying a what-if scenario.')
      return
    }
    setSimLoading(true)
    setSimScore(undefined)
    setSimAlerts([])
    setSimUnavailable(undefined)
    try {
      const routeIds = result.route_ids?.length ? result.route_ids : [result.route_id]
      const simulations = await Promise.all(routeIds.map((routeId) => simulateThreat({
        route_id: routeId,
        storm_severity: stormSeverity,
        solar_kp_index: solarKp,
        port_congestion: portCongestion,
      })))
      setSimScore(Math.min(...simulations.map((simulation) => simulation.simulated_score)))
      setSimAlerts([...new Set(simulations.flatMap((simulation, index) =>
        simulation.alerts.map((alert) => routeIds.length > 1 ? `Leg ${index + 1}: ${alert}` : alert),
      ))])
    } catch (simulationError) {
      setSimUnavailable(
        simulationError instanceof Error
          ? `Threat simulation could not be retrieved: ${simulationError.message}`
          : 'Threat simulation could not be retrieved. No simulated result is available.',
      )
    } finally {
      setSimLoading(false)
    }
  }, [result, stormSeverity, solarKp, portCongestion])

  const handleApprove = useCallback(async () => {
    if (!result) {
      setError('Suggest a route before approving.')
      return
    }
    const routeIds = result.route_ids?.length ? result.route_ids : [result.route_id]
    setApproving(true)
    setError(null)
    try {
      const current = await refreshEvidenceState(routeIds)
      if (current.failure) {
        throw new Error(`Approval blocked for route ${current.blockedRouteId}: ${current.failure}`)
      }
      await Promise.all(routeIds.map(approveRoute))
      setRouteApproved(true)
    } catch (approvalError) {
      setRouteApproved(false)
      setError(approvalError instanceof Error ? approvalError.message : 'Route approval failed closed.')
    } finally {
      setApproving(false)
    }
  }, [refreshEvidenceState, result])

  const handleDispatch = useCallback(async () => {
    if (!result) return
    const routeIds = result.route_ids?.length ? result.route_ids : [result.route_id]
    setDispatching(true)
    setError(null)
    try {
      const current = await refreshEvidenceState(routeIds)
      if (current.failure) {
        throw new Error(`Dispatch blocked for route ${current.blockedRouteId}: ${current.failure}`)
      }
      await dispatchJourney(routeIds)
      setDispatchComplete(true)
    } catch (dispatchError) {
      setError(dispatchError instanceof Error ? dispatchError.message : 'Dispatch failed closed.')
    } finally {
      setDispatching(false)
    }
  }, [refreshEvidenceState, result])

  const captureBrowserGps = useCallback(() => {
    if (!navigator.geolocation) {
      setError('Geolocation not supported in this browser.')
      return
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocationLat(pos.coords.latitude.toFixed(5))
        setLocationLon(pos.coords.longitude.toFixed(5))
        setLocationMode('live')
        setError(null)
      },
      () => setError('Could not capture GPS location.'),
    )
  }, [])

  const updateDestination = (index: number, code: string) => {
    setDestinations((prev) => prev.map((d, i) => (i === index ? code : d)))
  }

  const addDestination = () => {
    const used = new Set(destinations)
    if (excludeOrigin) used.add(excludeOrigin)
    const next = stationList.map((s) => s.code).find((c) => !used.has(c))
    if (next) setDestinations((prev) => [...prev, next])
  }

  const removeDestination = (index: number) => {
    setDestinations((prev) => (prev.length <= 1 ? prev : prev.filter((_, i) => i !== index)))
  }

  const routeLabel = result
    ? `${result.train_position?.station_code ?? nearestStation?.station.code ?? result.train_position?.snapped_track ?? 'Train'} → ${destinations.join(' → ')}`
    : undefined

  const segments = result?.segments ?? []
  const finalDest = destinations[destinations.length - 1]
  const {
    conditions: mapConditions,
    loading: liveWeatherLoading,
    lastUpdated: liveWeatherUpdated,
    error: liveWeatherError,
  } = useLiveMapConditions(
    segments,
    stationList,
    finalDest,
    mapReady || !!result,
  )
  const environmentalZones = useMemo(() => conditionsToZones(mapConditions), [mapConditions])

  return (
    <div className="h-full overflow-hidden flex flex-col bg-[#0F2D59]">
      <header className="px-6 py-2 bg-gradient-to-r from-blue-950 via-blue-900 to-indigo-950 border-b border-blue-800/60 flex items-center justify-between shrink-0">
        <p className="text-xs text-blue-300 font-mono">Load profiles · live track routing</p>
        <div className="flex items-center gap-3">
          {routeApproved ? (
            <span className="hidden sm:flex items-center gap-2 rounded-full border border-emerald-500/40 bg-emerald-950/40 px-3 py-1">
              <span className="text-[10px] font-mono uppercase text-emerald-300">Route approved</span>
            </span>
          ) : null}
          <span className="hidden sm:flex items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-950/40 px-3 py-1">
            <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
            <span className="text-[10px] font-mono uppercase text-emerald-300">Client-side maps</span>
          </span>
          <span className="px-3 py-1 bg-blue-600 text-white text-xs font-mono rounded-full shadow-lg shadow-blue-900/50">
            v6.0
          </span>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <aside className="w-[400px] shrink-0 glass-panel border-r border-slate-700/50 p-4 overflow-y-auto flex flex-col gap-4">
          <LoadProfilePanel selectedId={loadProfile?.id ?? null} onSelect={setLoadProfile} />

          <hr className="border-slate-700/50" />

          <h2 className="text-sm font-bold text-blue-400 uppercase tracking-wider flex items-center gap-2">
            <span className="inline-block h-2 w-2 rounded-full bg-blue-400" />
            Position & Routing
          </h2>

          {loadProfile ? (
            <div className="rounded-lg border border-blue-500/40 bg-blue-950/20 p-3">
              <span className="text-[9px] font-mono uppercase text-blue-400">Active load profile</span>
              <p className="font-semibold text-white">{loadProfile.name}</p>
              <p className="font-mono text-[11px] text-slate-400">
                {loadProfile.height}m × {loadProfile.width}m · {loadProfile.weight}T · {loadProfile.compartments}{' '}
                compartment{loadProfile.compartments === 1 ? '' : 's'}
              </p>
            </div>
          ) : (
            <p className="rounded-lg border border-dashed border-red-500/40 p-3 text-center text-xs font-mono text-red-300">
              Create or select a load profile above to enable routing.
            </p>
          )}

          <p className="text-xs font-mono text-blue-300/80 -mt-2">Current train location</p>
          <div className="grid grid-cols-3 gap-1">
            {(
              [
                ['station', 'Station'],
                ['coordinates', 'Coords'],
                ['live', 'GPS'],
              ] as const
            ).map(([mode, label]) => (
              <button
                key={mode}
                type="button"
                onClick={() => setLocationMode(mode)}
                className={`rounded-lg border px-2 py-2 text-[10px] font-mono font-semibold transition ${
                  locationMode === mode
                    ? 'border-blue-500 bg-blue-950/40 text-blue-300'
                    : 'border-slate-700 text-slate-500 hover:border-slate-500'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {locationMode === 'station' ? (
            <label className="flex flex-col gap-1">
              <span className="text-xs font-mono text-gray-400">Current station</span>
              <select
                value={locationStation}
                onChange={(e) => setLocationStation(e.target.value)}
                className="w-full px-3 py-2 bg-slate-900/80 border border-slate-700 rounded-lg text-white font-mono focus:outline-none focus:border-blue-500"
              >
                {stationList.map((s) => (
                  <option key={s.code} value={s.code}>
                    {s.code} — {s.name}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-2">
                <label className="flex flex-col gap-1">
                  <span className="text-xs font-mono text-gray-400">Latitude</span>
                  <input
                    type="number"
                    step="0.0001"
                    value={locationLat}
                    onChange={(e) => setLocationLat(e.target.value)}
                    className="w-full px-3 py-2 bg-slate-900/80 border border-slate-700 rounded-lg text-white font-mono"
                  />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-xs font-mono text-gray-400">Longitude</span>
                  <input
                    type="number"
                    step="0.0001"
                    value={locationLon}
                    onChange={(e) => setLocationLon(e.target.value)}
                    className="w-full px-3 py-2 bg-slate-900/80 border border-slate-700 rounded-lg text-white font-mono"
                  />
                </label>
              </div>
              <button
                type="button"
                onClick={captureBrowserGps}
                className="w-full rounded-lg border border-emerald-600/40 bg-emerald-950/20 px-3 py-2 text-xs font-mono text-emerald-300 hover:bg-emerald-950/40"
              >
                Capture browser GPS
              </button>
              {nearestStation ? (
                <div className="rounded-lg border border-blue-500/30 bg-blue-950/20 px-3 py-2">
                  <span className="text-[9px] font-mono uppercase text-blue-400">Nearest railway station</span>
                  <p className="font-mono text-xs text-white">
                    {nearestStation.station.code} — {nearestStation.station.name}
                  </p>
                  <p className="font-mono text-[10px] text-slate-500">{nearestStation.distanceKm} km from fix</p>
                </div>
              ) : null}
            </>
          )}

          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono text-gray-400">Destinations (in order)</span>
              <button
                type="button"
                onClick={addDestination}
                className="text-[10px] font-mono text-blue-400 hover:text-blue-300"
              >
                + Add stop
              </button>
            </div>
            {destinations.map((dest, index) => (
              <div key={`${index}-${dest}`} className="flex gap-2 items-center">
                <span className="w-5 shrink-0 text-center text-[10px] font-mono text-slate-500">{index + 1}</span>
                <select
                  value={dest}
                  onChange={(e) => updateDestination(index, e.target.value)}
                  className={`flex-1 px-3 py-2 bg-slate-900/80 border rounded-lg text-white font-mono text-sm focus:outline-none focus:border-blue-500 ${
                    dest === excludeOrigin ? 'border-red-500' : 'border-slate-700'
                  }`}
                >
                  {stationList
                    .filter((s) => s.code !== excludeOrigin || s.code === dest)
                    .map((s) => (
                      <option key={s.code} value={s.code}>
                        {s.code} — {s.name}
                      </option>
                    ))}
                </select>
                {destinations.length > 1 ? (
                  <button
                    type="button"
                    onClick={() => removeDestination(index)}
                    className="shrink-0 px-2 py-2 text-[10px] font-mono text-red-400 hover:text-red-300"
                  >
                    Remove
                  </button>
                ) : null}
              </div>
            ))}
            {destConflict ? (
              <span className="text-[11px] font-mono text-red-400">Destination cannot match current origin.</span>
            ) : null}
          </div>

          <label className="flex flex-col gap-1">
            <span className="text-xs font-mono text-gray-400">Train Arrival (hours from now)</span>
            <input
              type="number"
              min="0.01"
              step="0.25"
              value={trainHours}
              onChange={(e) => setTrainHours(e.target.value)}
              className="w-full px-3 py-2 bg-slate-900/80 border border-slate-700 rounded-lg text-white font-mono focus:outline-none focus:border-blue-500"
            />
          </label>

          <fieldset className="rounded-lg border border-slate-700/70 bg-slate-950/30 p-3">
            <legend className="px-1 text-[10px] font-mono font-semibold uppercase tracking-wider text-blue-300">
              Port handoff evidence
            </legend>
            <p className="mb-3 text-[10px] font-mono leading-relaxed text-slate-500">
              Use identifiers from the active manifest. No port, vessel, or berth-window value is assumed.
            </p>
            <div className="grid grid-cols-2 gap-2">
              <label className="flex flex-col gap-1">
                <span className="text-xs font-mono text-gray-400">Port ID *</span>
                <input
                  type="text"
                  value={portId}
                  onChange={(e) => setPortId(e.target.value)}
                  autoComplete="off"
                  placeholder="Manifest port ID"
                  className="w-full rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 font-mono text-sm text-white placeholder:text-slate-600 focus:border-blue-500 focus:outline-none"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs font-mono text-gray-400">Vessel ID *</span>
                <input
                  type="text"
                  value={vesselId}
                  onChange={(e) => setVesselId(e.target.value)}
                  autoComplete="off"
                  placeholder="Manifest vessel ID"
                  className="w-full rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 font-mono text-sm text-white placeholder:text-slate-600 focus:border-blue-500 focus:outline-none"
                />
              </label>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <label className="flex flex-col gap-1">
                <span className="text-[11px] font-mono text-gray-400">Loading window start</span>
                <input
                  type="datetime-local"
                  value={berthWindowStart}
                  onChange={(e) => setBerthWindowStart(e.target.value)}
                  className="w-full rounded-lg border border-slate-700 bg-slate-900/80 px-2 py-2 font-mono text-xs text-white focus:border-blue-500 focus:outline-none"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-[11px] font-mono text-gray-400">Loading window end</span>
                <input
                  type="datetime-local"
                  value={berthWindowEnd}
                  onChange={(e) => setBerthWindowEnd(e.target.value)}
                  className="w-full rounded-lg border border-slate-700 bg-slate-900/80 px-2 py-2 font-mono text-xs text-white focus:border-blue-500 focus:outline-none"
                />
              </label>
            </div>
            <div className="mt-3 grid gap-2">
              <label className="flex flex-col gap-1">
                <span className="text-[11px] font-mono text-gray-400">Manifest reference</span>
                <input
                  type="text"
                  value={manifestReference}
                  onChange={(e) => setManifestReference(e.target.value)}
                  autoComplete="off"
                  placeholder="Operator document reference"
                  className="w-full rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 font-mono text-xs text-white placeholder:text-slate-600 focus:border-blue-500 focus:outline-none"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-[11px] font-mono text-gray-400">Manifest SHA-256</span>
                <input
                  type="text"
                  value={manifestSha256}
                  onChange={(e) => setManifestSha256(e.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                  maxLength={64}
                  placeholder="64-character document digest"
                  className="w-full rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 font-mono text-xs text-white placeholder:text-slate-600 focus:border-blue-500 focus:outline-none"
                />
              </label>
            </div>
            <p className="mt-2 text-[10px] font-mono text-slate-500">
              Optional as a group; when supplied, both times, the manifest reference, and its SHA-256 are required and sent with every route leg.
            </p>
          </fieldset>

          <button
            type="button"
            onClick={handleEvaluate}
            disabled={loading || !loadProfile || destConflict || destinations.length === 0}
            className="relative overflow-hidden px-4 py-3 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white font-semibold rounded-lg shadow-lg shadow-blue-900/40 transition disabled:opacity-50"
          >
            {loading ? (
              <span className="animate-shimmer bg-gradient-to-r from-transparent via-white/20 to-transparent bg-clip-text">
                Evaluating Corridor…
              </span>
            ) : (
              'Suggest Remaining Route'
            )}
          </button>

          {error && <p className="text-red-400 text-xs font-mono">{error}</p>}
        </aside>

        <div className="flex w-14 shrink-0 flex-col items-center justify-center gap-3 border-r border-slate-700/50 bg-slate-950/80 px-2 py-4">
          <span className="text-[8px] font-mono font-bold uppercase tracking-widest text-slate-500 [writing-mode:vertical-rl] rotate-180">
            Dispatch
          </span>
          <button
            type="button"
            onClick={() => void handleApprove()}
            disabled={approving || routeApproved || !result || result.status !== 'APPROVED' || evidenceDecision !== 'READY' || evidenceFailure !== null}
            title={evidenceFailure ?? 'Every route leg will be checked again for fresh HOT evidence.'}
            className={`rounded-lg px-2 py-4 text-[10px] font-mono font-bold uppercase leading-tight transition [writing-mode:vertical-rl] rotate-180 ${
              routeApproved
                ? 'bg-emerald-600 text-white shadow-lg shadow-emerald-900/40'
                : 'border border-emerald-600/50 bg-emerald-950/30 text-emerald-300 hover:bg-emerald-950/50 disabled:opacity-40'
            }`}
          >
            {approving ? 'Checking & approving…' : routeApproved ? 'Approved' : evidenceFailure ? 'Evidence blocked' : 'Approve Route'}
          </button>
        </div>

        <main className="flex-1 p-3 bg-[#121a2e] overflow-hidden">
          {/* The map always renders. Before an evaluation it still shows the
              network and its stations; the hint below is an overlay rather
              than a replacement, so the operator is never faced with a blank
              panel where the corridor is expected. */}
          <div className="map-glow relative h-full rounded-xl">
            <MapViewer
              segments={result?.segments ?? []}
              stations={stationList}
              environmentalZones={environmentalZones}
              mapConditions={mapConditions}
              routeLabel={routeLabel}
              trainPosition={result?.train_position}
              liveWeatherUpdated={liveWeatherUpdated}
              liveWeatherLoading={liveWeatherLoading}
              liveWeatherError={liveWeatherError}
            />
            {!(mapReady || result) && (
              <div className="pointer-events-none absolute inset-x-0 bottom-0 z-[500] flex justify-center p-4">
                <div className="pointer-events-auto flex items-center gap-3 rounded-full border border-slate-600/70 bg-slate-900/90 px-4 py-2 shadow-xl backdrop-blur">
                  <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-cyan-400" />
                  <p className="font-mono text-xs text-slate-300">
                    {stationList.length > 0
                      ? `${stationList.length} stations loaded — run an evaluation to plot a corridor`
                      : 'Waiting for station data from the backend'}
                  </p>
                </div>
              </div>
            )}
          </div>
        </main>

        <aside className="w-[400px] shrink-0 glass-panel border-l border-slate-700/50 p-4 overflow-y-auto flex flex-col gap-4">
          <h2 className="text-sm font-bold text-blue-400 uppercase tracking-wider">Telemetry Board</h2>

          <div className="glass-panel rounded-xl p-4 flex flex-col items-center gap-2">
            <span className="text-xs font-mono text-gray-400 uppercase self-start">Route Reliability Index</span>
            <ScoreGauge score={result?.reliability_score ?? null} status={result?.status} />
            {result?.estimated_hours != null && (
              <span className="text-xs font-mono text-gray-400">
                Est. transit: {result.estimated_hours}h
              </span>
            )}
          </div>

          {result?.score_breakdown && (
            <div className="glass-panel rounded-xl p-4 flex flex-col gap-3">
              <span className="text-xs font-mono text-gray-500 uppercase">Score Breakdown</span>
              <MetricBar label="Weather" value={result.score_breakdown.weather} color="#38BDF8" />
              <MetricBar label="Port Sync" value={result.score_breakdown.port} color="#818CF8" />
              <MetricBar label="Congestion" value={result.score_breakdown.congestion} color="#FBBF24" />
              <MetricBar label="Historical" value={result.score_breakdown.historical} color="#34D399" />
            </div>
          )}

          {result?.provenance_summary ? (
            <DataTrustCard routeIds={result.route_ids?.length ? result.route_ids : [result.route_id]} summary={result.provenance_summary} />
          ) : null}

          {result?.environmental_alerts && result.environmental_alerts.length > 0 && (
            <div className="glass-panel rounded-xl p-4 border-red-900/50">
              <span className="text-xs font-mono text-red-400 uppercase">Environmental Alerts</span>
              <ul className="mt-2 space-y-1">
                {result.environmental_alerts.map((a) => (
                  <li key={a} className="text-xs font-mono text-red-300 flex items-start gap-2">
                    <span className="text-red-500 shrink-0">!</span> {a}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <TrackIntelPanel
            trainPosition={result?.train_position}
            remainingKm={result?.remaining_km}
            etaHours={result?.eta_hours}
            nextStation={result?.next_station}
            trackDetails={result?.track_details ?? []}
            alternateRoutes={result?.alternate_routes ?? []}
          />

          <Simulator
            stormSeverity={stormSeverity}
            solarKp={solarKp}
            portCongestion={portCongestion}
            onStormChange={setStormSeverity}
            onSolarChange={setSolarKp}
            onPortChange={setPortCongestion}
            onSimulate={handleSimulate}
            loading={simLoading}
            simulatedScore={simScore}
            alerts={simAlerts}
            unavailable={simUnavailable}
          />

          {routeApproved && !dispatchComplete && (
            <button
              type="button"
              disabled={dispatching || evidenceFailure !== null}
              onClick={() => void handleDispatch()}
              title={evidenceFailure ?? 'Every route leg will be checked again for fresh HOT evidence.'}
              className="px-4 py-3 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-semibold rounded-lg shadow-lg w-full transition"
            >
              {dispatching ? 'Rechecking evidence & dispatching…' : evidenceFailure ? 'Dispatch blocked by evidence' : 'Finalize and Dispatch Route'}
            </button>
          )}
          {dispatchComplete ? <p className="rounded-lg border border-emerald-700 bg-emerald-950/30 p-3 text-sm text-emerald-300">All verified route legs dispatched.</p> : null}
        </aside>
      </div>
    </div>
  )
}

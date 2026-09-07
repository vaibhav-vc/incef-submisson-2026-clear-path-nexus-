import type { AlternateRoute, TrackSegmentDetail, TrainPosition } from '../types/route'

interface Props {
  trainPosition?: TrainPosition
  remainingKm?: number
  etaHours?: number
  nextStation?: string
  trackDetails: TrackSegmentDetail[]
  alternateRoutes: AlternateRoute[]
}

export default function TrackIntelPanel({
  trainPosition,
  remainingKm,
  etaHours,
  nextStation,
  trackDetails,
  alternateRoutes,
}: Props) {
  if (trackDetails.length === 0) return null

  return (
    <div className="glass-panel rounded-xl p-4 flex flex-col gap-3">
      <span className="text-xs font-mono text-blue-400 uppercase tracking-wider">Live Track Intelligence</span>

      {trainPosition ? (
        <div className="rounded-lg border border-blue-500/30 bg-blue-950/20 p-3 flex flex-col gap-1">
          <span className="text-[10px] font-mono text-blue-300 uppercase">Train position</span>
          <span className="font-mono text-sm text-white">
            {trainPosition.lat.toFixed(4)}°N, {trainPosition.lon.toFixed(4)}°E
          </span>
          {trainPosition.snapped_track ? (
            <span className="text-xs font-mono text-slate-400">On track: {trainPosition.snapped_track}</span>
          ) : null}
          {trainPosition.station_code ? (
            <span className="text-xs font-mono text-slate-400">At station: {trainPosition.station_code}</span>
          ) : null}
          <div className="flex flex-wrap gap-2 mt-2">
            {remainingKm != null ? <Chip label="Remaining" value={`${remainingKm} km`} /> : null}
            {etaHours != null ? <Chip label="ETA" value={`${etaHours}h`} /> : null}
            {nextStation ? <Chip label="Next" value={nextStation} /> : null}
          </div>
        </div>
      ) : null}

      {trackDetails.map((track) => (
        <div
          key={track.id}
          className={`rounded-lg border p-3 flex flex-col gap-2 ${
            track.phase === 'CURRENT'
              ? 'border-blue-500/50 bg-blue-950/15'
              : track.clearance_status === 'HARD_BLOCKED'
                ? 'border-red-800/50'
                : 'border-slate-700/50'
          }`}
        >
          <div className="flex items-center justify-between gap-2">
            <span className="font-mono text-sm font-semibold text-white">{track.label}</span>
            <span className="text-[10px] font-mono uppercase text-blue-300">{track.phase}</span>
          </div>
          <div className="grid grid-cols-3 gap-2 text-[11px] font-mono">
            <span className="text-slate-500">Dist: <span className="text-slate-300">{track.distance_km} km</span></span>
            <span className="text-slate-500">H: <span className="text-slate-300">{track.max_height}m</span></span>
            <span className="text-slate-500">W: <span className="text-slate-300">{track.max_width}m</span></span>
            <span className="text-slate-500">Cap: <span className="text-slate-300">{track.max_weight}T</span></span>
            <span className="text-slate-500">Cong: <span className="text-slate-300">×{track.congestion}</span></span>
            <span className="text-slate-500">Delay: <span className="text-slate-300">{track.historical_delay_hours}h</span></span>
          </div>
          {track.progress_pct != null && track.phase === 'CURRENT' ? (
            <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
              <div className="h-full bg-blue-500 rounded-full transition-all" style={{ width: `${track.progress_pct}%` }} />
            </div>
          ) : null}
          {track.advisory ? <p className="text-xs font-mono text-amber-400">→ {track.advisory}</p> : null}
        </div>
      ))}

      {alternateRoutes.length > 1 ? (
        <div className="border-t border-slate-700 pt-2">
          <span className="text-[10px] font-mono text-slate-500 uppercase">Alternate corridors</span>
          {alternateRoutes.slice(1).map((alt) => (
            <div key={alt.label} className="flex justify-between text-xs font-mono mt-1">
              <span className="text-slate-300">{alt.label}</span>
              <span className="text-emerald-400">RI {alt.reliability_score}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function Chip({ label, value }: { label: string; value: string }) {
  return (
    <span className="rounded-md border border-slate-600 bg-slate-900/80 px-2 py-1 text-[10px] font-mono">
      <span className="text-slate-500">{label}: </span>
      <span className="text-white">{value}</span>
    </span>
  )
}

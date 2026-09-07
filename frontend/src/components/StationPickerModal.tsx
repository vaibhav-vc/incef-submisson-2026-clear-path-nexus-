/**
 * StationPickerModal.tsx
 * Modal shown when multiple OSM railway stations are found within 20 km of
 * the user's GPS/coordinate fix. Lets the user choose which one to use as origin.
 */

export interface OsmStation {
  osmId: number
  name: string
  lat: number
  lon: number
  distanceKm: number
  /** Railway operator or network tag if available */
  operator?: string
  /** Station type: main station, halt, etc. */
  stationType?: string
}

interface Props {
  stations: OsmStation[]
  onSelect: (station: OsmStation) => void
  onClose: () => void
}

function distColor(km: number): string {
  if (km < 2) return '#34D399' // very close — green
  if (km < 8) return '#FCD34D' // moderate — yellow
  return '#94A3B8'              // further — grey
}

export default function StationPickerModal({ stations, onSelect, onClose }: Props) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'rgba(0,0,0,0.65)', backdropFilter: 'blur(4px)' }}
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-md mx-4 rounded-2xl border border-slate-700/70 bg-[#0d1b35] shadow-2xl shadow-blue-950/60 p-5 flex flex-col gap-4"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-bold text-white">
              Multiple Railway Stations Found
            </h2>
            <p className="text-[11px] font-mono text-slate-400 mt-0.5">
              {stations.length} station{stations.length !== 1 ? 's' : ''} within 20 km — choose your origin
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 flex h-7 w-7 items-center justify-center rounded-full border border-slate-600 text-slate-400 hover:text-white hover:border-slate-400 transition"
          >
            <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Source badge */}
        <div className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
          <span className="text-[10px] font-mono text-emerald-400 uppercase tracking-wider">
            Live data · OpenStreetMap Overpass API
          </span>
        </div>

        {/* Station list */}
        <div className="flex flex-col gap-2 max-h-72 overflow-y-auto pr-1">
          {stations.map((stn) => (
            <button
              key={stn.osmId}
              type="button"
              onClick={() => onSelect(stn)}
              className="group text-left rounded-xl border border-slate-700/50 bg-slate-900/60 hover:border-blue-500/60 hover:bg-blue-950/30 px-4 py-3 transition"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-white group-hover:text-blue-300 transition truncate">
                    {stn.name || `Station OSM #${stn.osmId}`}
                  </p>
                  {stn.operator && (
                    <p className="text-[10px] font-mono text-slate-500 truncate">{stn.operator}</p>
                  )}
                  <p className="text-[10px] font-mono text-slate-600 mt-0.5">
                    {stn.lat.toFixed(4)}°N, {stn.lon.toFixed(4)}°E
                  </p>
                  {stn.stationType && (
                    <p className="text-[9px] font-mono text-slate-600">{stn.stationType}</p>
                  )}
                </div>
                <div className="shrink-0 flex flex-col items-end gap-1">
                  <span
                    className="text-sm font-bold font-mono"
                    style={{ color: distColor(stn.distanceKm) }}
                  >
                    {stn.distanceKm < 0.1 ? '<0.1' : stn.distanceKm.toFixed(1)} km
                  </span>
                  <span className="text-[9px] font-mono text-slate-600">from fix</span>
                  <span className="mt-1 text-[9px] font-mono text-blue-400 group-hover:text-blue-300 transition">
                    Select →
                  </span>
                </div>
              </div>
            </button>
          ))}
        </div>

        {/* Footer */}
        <p className="text-[9px] font-mono text-slate-600 text-center">
          Stations sourced from OpenStreetMap · railway=station nodes
        </p>
      </div>
    </div>
  )
}

import { MAP_SYMBOL_GUIDE, type MapSymbolEntry } from '../maps/mapSymbolGuide'

interface Props {
  open: boolean
  onClose: () => void
}

const CATEGORY_LABELS: Record<MapSymbolEntry['category'], string> = {
  markers: 'Map markers',
  routes: 'Route lines',
  weather: 'Weather conditions (blue)',
  environmental: 'Environmental alerts (orange)',
  operational: 'Operational status (green)',
  zones: 'Zone overlays',
}

export default function MapSymbolGuidePopup({ open, onClose }: Props) {
  if (!open) return null

  const categories = ['markers', 'routes', 'weather', 'environmental', 'operational', 'zones'] as const

  return (
    <div
      className="absolute inset-0 z-50 flex items-center justify-center bg-black/65 p-4"
      onClick={onClose}
      role="dialog"
      aria-label="Map symbol guide"
    >
      <div
        className="max-h-[82%] w-full max-w-md overflow-hidden rounded-2xl border border-slate-600 bg-slate-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
          <h2 className="text-lg font-bold text-white">Rail route symbol palette</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg px-2 py-1 text-slate-400 hover:bg-slate-800 hover:text-white"
            aria-label="Close"
          >
            ✕
          </button>
        </div>
        <p className="px-4 py-2 text-[11px] font-mono text-slate-500">
          Live markers update from Open-Meteo and NOAA K-index. Click any marker on the map for details.
        </p>
        <div className="max-h-[60vh] overflow-y-auto px-4 pb-4">
          {categories.map((cat) => (
            <section key={cat} className="mb-4">
              <h3 className="mb-2 text-[11px] font-mono font-bold uppercase tracking-wider text-blue-400">
                {CATEGORY_LABELS[cat]}
              </h3>
              <ul className="space-y-3">
                {MAP_SYMBOL_GUIDE.filter((e) => e.category === cat).map((entry) => (
                  <li key={entry.title} className="flex gap-3">
                    <span className="w-8 text-center text-xl" aria-hidden>
                      {entry.icon}
                    </span>
                    <div>
                      <p className="text-sm font-semibold text-white">{entry.title}</p>
                      <p className="text-xs leading-relaxed text-slate-400">{entry.description}</p>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </div>
    </div>
  )
}

import { useState } from 'react'
import { CONDITION_SYMBOLS, CATEGORY_COLORS, type ConditionCategory, type ConditionType } from '../maps/conditionSymbols'
import ConditionIcon from './ConditionIcon'

interface MapLegendProps {
  routeLabel?: string
  conditionCount?: number
  liveWeatherUpdated?: Date | null
  liveWeatherLoading?: boolean
  liveWeatherError?: string | null
  collapsed?: boolean
  onToggle?: () => void
}

const CATEGORY_ORDER: ConditionCategory[] = ['weather', 'environmental', 'operational']

const CATEGORY_LABELS: Record<ConditionCategory, string> = {
  weather: 'Weather',
  environmental: 'Environmental',
  operational: 'Operational',
}

export default function MapLegend({
  routeLabel,
  conditionCount = 0,
  liveWeatherUpdated,
  liveWeatherLoading = false,
  liveWeatherError,
  collapsed = false,
  onToggle,
}: MapLegendProps) {
  const [hovering, setHovering] = useState(false)
  const grouped = CATEGORY_ORDER.map((cat) => ({
    cat,
    items: Object.entries(CONDITION_SYMBOLS).filter(([, s]) => s.category === cat),
  }))

  if (collapsed) {
    return (
      <aside
        className="flex flex-col items-center gap-2 rounded-xl border border-slate-600/50 py-3 px-2"
        style={{
          background: 'rgba(5, 10, 25, 0.92)',
          backdropFilter: 'blur(14px)',
          WebkitBackdropFilter: 'blur(14px)',
          boxShadow: '0 4px 24px -4px rgba(0,0,0,0.6)',
        }}
      >
        {/* Expand button — prominent */}
        <button
          type="button"
          onClick={onToggle}
          onMouseEnter={() => setHovering(true)}
          onMouseLeave={() => setHovering(false)}
          className="group flex h-9 w-9 items-center justify-center rounded-xl border border-blue-500/50 bg-blue-600/20 text-blue-300 hover:bg-blue-500 hover:text-white hover:border-blue-400 transition-all duration-200 shadow-lg shadow-blue-900/40"
          title="Show map legend"
          aria-label="Expand symbol legend"
        >
          <svg
            className={`h-4 w-4 transition-transform duration-300 ${hovering ? 'scale-110' : ''}`}
            viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h10M4 18h7" />
          </svg>
        </button>

        {/* Condition count badge */}
        {conditionCount > 0 && (
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-sky-500 text-[9px] font-bold text-white shadow-md shadow-sky-900/50 animate-pulse">
            {conditionCount > 9 ? '9+' : conditionCount}
          </span>
        )}

        {/* Vertical "LEGEND" text */}
        <span className="text-[7px] font-mono font-bold uppercase tracking-widest text-slate-500 [writing-mode:vertical-rl] rotate-180 mt-1 select-none">
          Legend
        </span>
      </aside>
    )
  }

  return (
    <aside
      className="flex h-full max-h-full flex-col rounded-xl border border-slate-700/60 overflow-hidden"
      style={{
        background: 'rgba(5, 10, 25, 0.92)',
        backdropFilter: 'blur(14px)',
        WebkitBackdropFilter: 'blur(14px)',
        boxShadow: '0 4px 28px -4px rgba(0,0,0,0.7)',
      }}
    >
      {/* ── Header ─────────────────────────────────────────────── */}
      <div className="shrink-0 border-b border-slate-700/40 px-3 py-2.5">
        <div className="flex items-center justify-between gap-2">
          {/* Provider indicator */}
          <div className="flex items-center gap-1.5">
            <span className="relative flex h-2 w-2">
              {!liveWeatherError && liveWeatherUpdated ? <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60" /> : null}
              <span className={`relative inline-flex h-2 w-2 rounded-full ${liveWeatherError ? 'bg-rose-400' : liveWeatherUpdated ? 'bg-emerald-400' : 'bg-amber-400'}`} />
            </span>
            <span className={`text-[9px] font-mono font-bold uppercase tracking-wider ${liveWeatherError ? 'text-rose-300' : liveWeatherUpdated ? 'text-emerald-300' : 'text-amber-300'}`}>
              {liveWeatherError ? 'Provider unavailable' : liveWeatherUpdated ? 'Live provider data' : 'Awaiting provider'}
            </span>
          </div>

          {/* ── HIDE BUTTON — prominent ─────────────────────────── */}
          <button
            type="button"
            onClick={onToggle}
            className="group flex items-center gap-1.5 rounded-lg border border-slate-600/60 bg-slate-800/70 px-2.5 py-1.5 text-[10px] font-mono font-semibold text-slate-300 hover:border-red-500/60 hover:bg-red-950/40 hover:text-red-300 transition-all duration-200 shadow-sm"
            title="Collapse legend for full map view"
            aria-label="Collapse symbol legend"
          >
            <svg
              className="h-3.5 w-3.5 transition-transform duration-200 group-hover:-translate-x-0.5"
              viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
            <span>Hide</span>
            {/* Tooltip hint */}
            <span className="hidden group-hover:inline text-[8px] text-red-400/80 font-mono">full map</span>
          </button>
        </div>

        {/* Update timestamp */}
        <p className="mt-1 text-[9px] font-mono text-slate-500">
          {liveWeatherError
            ? liveWeatherError
            : liveWeatherUpdated
            ? `Updated ${liveWeatherUpdated.toLocaleTimeString()}`
            : liveWeatherLoading ? 'Fetching conditions…' : 'No live observation loaded'}
        </p>

        {/* Corridor label */}
        {routeLabel ? (
          <div className="mt-2 border-t border-slate-700/40 pt-2">
            <span className="text-[8px] font-mono uppercase text-slate-500">Corridor</span>
            <p className="font-mono text-[10px] font-semibold text-white leading-tight">{routeLabel}</p>
          </div>
        ) : null}
      </div>

      {/* ── Symbol palette label ────────────────────────────────── */}
      <p className="shrink-0 px-3 pt-2 pb-1 text-[8px] font-mono font-bold uppercase tracking-wider text-slate-500">
        Symbol palette
      </p>

      {/* ── Scrollable content ─────────────────────────────────── */}
      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
        {/* Route line legend */}
        <div className="mb-3 rounded-lg border border-slate-700/40 bg-slate-900/40 p-2 space-y-1.5">
          <p className="text-[8px] font-mono font-bold uppercase text-slate-500 mb-1.5">Route lines</p>
          <LegendLine color="#38A169" label="Approved segment" />
          <LegendLine color="#E53E3E" label="Blocked segment" />
          <LegendLine color="#63B3ED" label="Current segment" thick />
          <LegendLine color="#64748b" label="Traversed segment" dashed />
        </div>

        {/* Condition symbol categories */}
        {grouped.map(({ cat, items }) => (
          <div key={cat} className="mb-3">
            <div className="mb-1.5 flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: CATEGORY_COLORS[cat].dot }} />
              <span
                className="text-[9px] font-mono font-bold uppercase tracking-wide"
                style={{ color: CATEGORY_COLORS[cat].stroke }}
              >
                {CATEGORY_LABELS[cat]}
              </span>
            </div>
            <ul className="space-y-1">
              {items.map(([type, sym]) => (
                <li key={type} className="flex items-start gap-2">
                  <ConditionIcon type={type as ConditionType} size={16} />
                  <div className="min-w-0 flex-1">
                    <p className="text-[10px] font-semibold text-white leading-tight">{sym.label}</p>
                    <p className="text-[8px] leading-tight text-slate-500">{sym.detail}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {/* ── Footer count ───────────────────────────────────────── */}
      {conditionCount > 0 ? (
        <p className="shrink-0 border-t border-slate-700/40 px-3 py-2 text-[8px] font-mono text-slate-500 flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-sky-400 animate-pulse" />
          {conditionCount} live marker{conditionCount === 1 ? '' : 's'} on map
        </p>
      ) : null}
    </aside>
  )
}

function LegendLine({
  color, label, dashed, thick,
}: {
  color: string; label: string; dashed?: boolean; thick?: boolean
}) {
  return (
    <div className="flex items-center gap-2">
      <span
        className="shrink-0 rounded-full"
        style={{
          width: 20,
          height: thick ? 4 : 2,
          backgroundColor: dashed ? 'transparent' : color,
          backgroundImage: dashed
            ? `repeating-linear-gradient(90deg, ${color} 0, ${color} 4px, transparent 4px, transparent 7px)`
            : undefined,
        }}
      />
      <span className="font-mono text-[9px] text-slate-300">{label}</span>
    </div>
  )
}

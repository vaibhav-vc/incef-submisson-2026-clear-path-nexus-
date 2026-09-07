/**
 * RouteWeatherPanel.tsx
 * Displays live per-point weather readings sourced from Open-Meteo for every
 * sampled point along the active route. Acts as the "smart weather database".
 */
import type { RouteWeatherPoint } from '../hooks/useRouteWeather'

interface Props {
  points: RouteWeatherPoint[]
  loading: boolean
  lastUpdated: Date | null
  error: string | null
  onRefresh: () => void
}

const CONDITION_CONFIG: Record<
  RouteWeatherPoint['condition'],
  { icon: string; color: string; bg: string }
> = {
  clear: { icon: '☀️', color: '#FCD34D', bg: 'rgba(251,191,36,0.08)' },
  cloudy: { icon: '☁️', color: '#94A3B8', bg: 'rgba(148,163,184,0.08)' },
  rain: { icon: '🌧️', color: '#38BDF8', bg: 'rgba(56,189,248,0.08)' },
  storm: { icon: '⛈️', color: '#F87171', bg: 'rgba(248,113,113,0.08)' },
  snow: { icon: '❄️', color: '#BAE6FD', bg: 'rgba(186,230,253,0.08)' },
  fog: { icon: '🌫️', color: '#CBD5E1', bg: 'rgba(203,213,225,0.08)' },
  windy: { icon: '💨', color: '#A78BFA', bg: 'rgba(167,139,250,0.08)' },
}

function windDirLabel(deg: number): string {
  const dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
  return dirs[Math.round(deg / 45) % 8]
}

function visibilityLabel(metres: number): string {
  if (metres >= 10000) return '> 10 km'
  return `${(metres / 1000).toFixed(1)} km`
}

function formatTime(date: Date): string {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export default function RouteWeatherPanel({ points, loading, lastUpdated, error, onRefresh }: Props) {
  if (points.length === 0 && !loading) return null

  return (
    <div className="glass-panel rounded-xl flex flex-col gap-3 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 pt-4">
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-sky-400 animate-pulse" />
          <span className="text-xs font-mono text-sky-400 uppercase tracking-wider">
            Route Weather Database
          </span>
        </div>
        <div className="flex items-center gap-2">
          {lastUpdated && (
            <span className="text-[10px] font-mono text-slate-500">
              {formatTime(lastUpdated)}
            </span>
          )}
          <button
            type="button"
            onClick={onRefresh}
            disabled={loading}
            title="Refresh weather"
            className="flex items-center justify-center h-6 w-6 rounded-md border border-slate-700 text-slate-400 hover:text-sky-300 hover:border-sky-500/50 transition disabled:opacity-40"
          >
            <svg
              className={`h-3 w-3 ${loading ? 'animate-spin' : ''}`}
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2.5}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              />
            </svg>
          </button>
        </div>
      </div>

      {/* Open-Meteo attribution */}
      <p className="px-4 text-[9px] font-mono text-slate-600">
        Live data · Open-Meteo API · auto-refresh every 10 min
      </p>

      {error && (
        <p className="mx-4 rounded-md border border-amber-800/40 bg-amber-950/20 px-3 py-1.5 text-[10px] font-mono text-amber-400">
          ⚠ {error}
        </p>
      )}

      {loading && points.length === 0 && (
        <div className="flex items-center justify-center gap-2 py-6 text-slate-400">
          <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83" />
          </svg>
          <span className="text-xs font-mono">Fetching live weather…</span>
        </div>
      )}

      {/* Weather cards */}
      <div className="flex flex-col gap-2 px-4 pb-4 max-h-[400px] overflow-y-auto">
        {points.map((pt) => {
          const cfg = CONDITION_CONFIG[pt.condition]
          return (
            <div
              key={pt.id}
              className="rounded-xl border border-slate-700/50 p-3 flex flex-col gap-2"
              style={{ background: cfg.bg }}
            >
              {/* Location & condition */}
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-xs font-mono font-semibold text-white truncate">{pt.label}</p>
                  <p className="text-[10px] font-mono text-slate-500">
                    {pt.lat.toFixed(3)}°N, {pt.lon.toFixed(3)}°E
                  </p>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  <span className="text-xl leading-none">{cfg.icon}</span>
                  <div className="text-right">
                    <p className="text-lg font-bold leading-none" style={{ color: cfg.color }}>
                      {pt.temperature}°C
                    </p>
                    <p className="text-[9px] font-mono text-slate-500">
                      feels {pt.feelsLike}°C
                    </p>
                  </div>
                </div>
              </div>

              {/* Condition label */}
              <p className="text-[10px] font-mono" style={{ color: cfg.color }}>
                {pt.weatherLabel}
              </p>

              {/* Metrics grid */}
              <div className="grid grid-cols-3 gap-x-2 gap-y-1 text-[10px] font-mono">
                <WeatherChip label="Humidity" value={`${pt.humidity}%`} />
                <WeatherChip label="Wind" value={`${pt.windSpeed} km/h ${windDirLabel(pt.windDirection)}`} />
                <WeatherChip label="Precip" value={`${pt.precipMm} mm`} />
                <WeatherChip label="Visibility" value={visibilityLabel(pt.visibility)} />
                <WeatherChip label="UV Index" value={`${pt.uvIndex}`} warn={pt.uvIndex >= 8} />
                <WeatherChip label="Code" value={`WMO ${pt.weatherCode}`} />
              </div>

              {/* Alert strips */}
              {pt.windSpeed >= 50 && (
                <p className="rounded bg-red-950/40 border border-red-800/40 px-2 py-1 text-[10px] font-mono text-red-400">
                  ⚠ High wind alert — {pt.windSpeed} km/h
                </p>
              )}
              {pt.condition === 'storm' && (
                <p className="rounded bg-amber-950/40 border border-amber-800/40 px-2 py-1 text-[10px] font-mono text-amber-400">
                  ⚡ Thunderstorm in area — route caution advised
                </p>
              )}
              {pt.visibility < 1000 && (
                <p className="rounded bg-slate-800/60 border border-slate-600/40 px-2 py-1 text-[10px] font-mono text-slate-300">
                  🌫 Low visibility — {visibilityLabel(pt.visibility)}
                </p>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function WeatherChip({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <span className={`flex flex-col gap-0.5 ${warn ? 'text-amber-400' : ''}`}>
      <span className="text-slate-500">{label}</span>
      <span className={warn ? 'text-amber-300 font-bold' : 'text-slate-300'}>{value}</span>
    </span>
  )
}

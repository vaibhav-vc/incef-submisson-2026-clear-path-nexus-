interface ScoreGaugeProps {
  score: number | null
  status?: string
}

function scoreColor(score: number, status?: string) {
  if (status === 'HARD_BLOCKED') return '#E53E3E'
  if (status === 'APPROVED') return '#38A169'
  if (score >= 75) return '#38A169'
  if (score >= 50) return '#DD6B20'
  return '#E53E3E'
}

export default function ScoreGauge({ score, status }: ScoreGaugeProps) {
  const value = score ?? 0
  const pct = Math.min(Math.max(value, 0), 100)
  const radius = 54
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (pct / 100) * circumference
  const color = score !== null ? scoreColor(value, status) : '#64748b'

  return (
    <div className="relative mx-auto flex h-36 w-36 items-center justify-center">
      <svg className="-rotate-90" width="144" height="144" viewBox="0 0 144 144">
        <circle cx="72" cy="72" r={radius} fill="none" stroke="#1e293b" strokeWidth="10" />
        <circle
          cx="72"
          cy="72"
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={score !== null ? offset : circumference}
          className="transition-all duration-700 ease-out"
          style={{ filter: score !== null ? `drop-shadow(0 0 8px ${color}88)` : undefined }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-4xl font-bold font-mono tabular-nums" style={{ color }}>
          {score !== null ? Math.round(score) : '—'}
        </span>
        {status ? (
          <span className="mt-1 text-[10px] font-mono uppercase tracking-wider" style={{ color }}>
            {status.replace('_', ' ')}
          </span>
        ) : (
          <span className="mt-1 text-[10px] font-mono text-slate-500">Awaiting eval</span>
        )}
      </div>
    </div>
  )
}

interface MetricBarProps {
  label: string
  value: number | null
  color?: string
}

export default function MetricBar({ label, value, color = '#63B3ED' }: MetricBarProps) {
  const pct = value == null ? 0 : Math.min(Math.max(value, 0), 100)

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between text-xs font-mono">
        <span className="text-slate-500">{label}</span>
        <span className="tabular-nums text-slate-300">{value == null ? 'Unavailable' : Math.round(value)}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-800">
        <div
          className="h-full rounded-full transition-all duration-700 ease-out"
          style={{
            width: `${pct}%`,
            background: `linear-gradient(90deg, ${color}99, ${color})`,
            boxShadow: `0 0 12px ${color}55`,
          }}
        />
      </div>
    </div>
  )
}

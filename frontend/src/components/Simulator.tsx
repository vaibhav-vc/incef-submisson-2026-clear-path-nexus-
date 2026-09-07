interface SimulatorProps {
  stormSeverity: number
  solarKp: number
  portCongestion: number
  onStormChange: (v: number) => void
  onSolarChange: (v: number) => void
  onPortChange: (v: number) => void
  onSimulate: () => void
  loading: boolean
  simulatedScore?: number
  alerts: string[]
  unavailable?: string
}

export default function Simulator({
  stormSeverity,
  solarKp,
  portCongestion,
  onStormChange,
  onSolarChange,
  onPortChange,
  onSimulate,
  loading,
  simulatedScore,
  alerts,
  unavailable,
}: SimulatorProps) {
  return (
    <div className="p-4 bg-gray-900 border border-gray-800 rounded-lg shadow-lg flex flex-col gap-4">
      <h2 className="text-sm font-bold uppercase tracking-wider text-orange-400">
        Threat Simulation Center
      </h2>

      <label className="flex flex-col gap-1">
        <span className="text-xs font-mono text-gray-400">Storm Severity ({stormSeverity}%)</span>
        <input
          type="range"
          min={0}
          max={100}
          value={stormSeverity}
          onChange={(e) => onStormChange(Number(e.target.value))}
          className="w-full accent-orange-600"
        />
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-xs font-mono text-gray-400">Solar Kp-Index ({solarKp})</span>
        <input
          type="range"
          min={0}
          max={9}
          value={solarKp}
          onChange={(e) => onSolarChange(Number(e.target.value))}
          className="w-full accent-orange-600"
        />
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-xs font-mono text-gray-400">Port Congestion ({portCongestion}%)</span>
        <input
          type="range"
          min={0}
          max={100}
          value={portCongestion}
          onChange={(e) => onPortChange(Number(e.target.value))}
          className="w-full accent-orange-600"
        />
      </label>

      <button
        type="button"
        onClick={onSimulate}
        disabled={loading}
        className="px-4 py-2 bg-orange-600 hover:bg-orange-700 text-white font-mono font-bold rounded shadow-md uppercase tracking-wider transition duration-150 disabled:opacity-50"
      >
        {loading ? 'Simulating…' : 'Inject Threat'}
      </button>

      {simulatedScore !== undefined && (
        <div className="font-mono text-xs text-orange-300">
          Simulated Score: <span className="text-lg font-bold">{simulatedScore}</span>
        </div>
      )}

      {unavailable && (
        <div role="status" className="rounded border border-red-700 bg-red-950/40 p-3 font-mono text-xs text-red-300">
          <strong className="block uppercase tracking-wider">Unavailable</strong>
          <span className="mt-1 block text-red-200">{unavailable}</span>
        </div>
      )}

      {alerts.length > 0 && (
        <ul className="text-xs font-mono text-red-400 space-y-1">
          {alerts.map((a) => (
            <li key={a}>⚠ {a}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

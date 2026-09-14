import { useEffect, useState } from 'react'
import { supabase } from '../services/supabaseClient'
import { withTimeout } from '../lib/sessionLifecycle'
import { APP_RUNTIME_MODE, LOCAL_DEMO_MODE } from '../lib/runtimeMode'

export type ActiveTab =
  | 'command' | 'predictive' | 'dustRadar' | 'history'
  | 'dispatch' | 'schedule' | 'weather' | 'loadProfiles' | 'liveTraffic'
  | 'sourceTrust' | 'compliance'
  | 'liveOps'
  | 'integrated'
  | 'speedAdvisory'

interface HeaderNavbarProps {
  activeTab: ActiveTab
  setActiveTab: (tab: ActiveTab) => void
}

const tabs: Array<[ActiveTab, string]> = [
  ['integrated', '🧭 Nexus v6'], ['liveOps', '🟢 LiveOps'], ['command', '📍 Operations'], ['schedule', '🗓 Scheduler'], ['dispatch', '🚦 Dispatch'],
  ['predictive', '⚡ Predictive ETA'], ['dustRadar', '🌪️ Dust Radar'],
  ['speedAdvisory', '🛡️ Speed Risk'],
  ['history', '📜 Audit'], ['weather', '🌦️ Telemetry'], ['liveTraffic', '🛰️ Live Traffic'],
  ['loadProfiles', '📦 Loads'],
  ['sourceTrust', '🔎 Sources'], ['compliance', '🛡️ Compliance'],
]

export default function HeaderNavbar({ activeTab, setActiveTab }: HeaderNavbarProps) {
  const [email, setEmail] = useState<string>(LOCAL_DEMO_MODE ? 'Judge demo operator' : 'Operator')
  const [signingOut, setSigningOut] = useState(false)
  const [authError, setAuthError] = useState<string | null>(null)

  useEffect(() => {
    if (LOCAL_DEMO_MODE) return
    if (!supabase) return
    let active = true
    void withTimeout(supabase.auth.getUser()).then(({ data }) => {
      if (active) setEmail(data.user?.email ?? 'Operator')
    }).catch(() => {
      if (active) setAuthError('Operator identity could not be refreshed. Check your connection.')
    })
    return () => { active = false }
  }, [])

  async function signOut() {
    if (LOCAL_DEMO_MODE) return
    if (!supabase || signingOut) return
    setSigningOut(true)
    setAuthError(null)
    try {
      const { error } = await withTimeout(supabase.auth.signOut())
      if (error) setAuthError('Sign-out could not be confirmed. Check your connection and retry.')
    } catch {
      setAuthError('Sign-out could not be confirmed. Check your connection and retry.')
    } finally {
      setSigningOut(false)
    }
  }

  return (
    <header className="bg-slate-950/90 border-b border-slate-800/80 backdrop-blur-md sticky top-0 z-40 px-4 py-3">
      <div className="max-w-7xl mx-auto flex flex-col gap-3">
        {LOCAL_DEMO_MODE && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-400/40 bg-amber-400/10 px-3 py-2 text-xs text-amber-100" role="status">
            <span><strong>Offline judge mode</strong> · local backend only · authentication bypassed · seeded demonstration data · no operational authority</span>
            <button
              type="button"
              className="rounded border border-amber-300/40 px-2 py-1 font-semibold hover:bg-amber-300/10"
              onClick={() => void navigator.clipboard?.writeText(window.location.href)}
            >
              Copy device link
            </button>
          </div>
        )}
        {!LOCAL_DEMO_MODE && (
          <div className="flex items-center justify-between gap-2 rounded-lg border border-cyan-400/25 bg-cyan-400/5 px-3 py-1.5 text-[11px] text-cyan-100" role="status">
            <span><strong>Online operator mode</strong> · Supabase-authenticated access · configured EvidenceGate API</span>
            <span className="font-mono uppercase tracking-wide">{APP_RUNTIME_MODE}</span>
          </div>
        )}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-cyan-500 to-blue-600 flex items-center justify-center text-xl">🚆</div>
            <div>
              <h1 className="text-lg font-bold">ClearPath Nexus <span className="text-[10px] text-amber-400">v6.0</span></h1>
              <p className="text-[11px] text-slate-400">Explainable Freight Operations Decision Support</p>
            </div>
          </div>
          <div className="flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-900 px-3 py-1.5">
            <span className="max-w-48 truncate text-xs text-slate-300">👤 {email}</span>
            {!LOCAL_DEMO_MODE && <button onClick={() => void signOut()} disabled={signingOut} className="text-[11px] text-rose-400 hover:underline disabled:opacity-50">{signingOut ? 'Signing out…' : 'Sign Out'}</button>}
          </div>
        </div>
        {authError && <p role="alert" className="text-xs text-amber-300">{authError}</p>}
        <nav className="flex flex-wrap items-center gap-1 bg-slate-900/90 p-1 border border-slate-800 rounded-xl">
          {tabs.map(([id, label]) => (
            <button key={id} onClick={() => setActiveTab(id)} aria-pressed={activeTab === id} className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${activeTab === id ? 'bg-cyan-500 text-slate-950 shadow-md' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'}`}>
              {label}
            </button>
          ))}
        </nav>
      </div>
    </header>
  )
}

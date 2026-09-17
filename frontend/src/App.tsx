import { lazy, Suspense, useState } from 'react'
import AuthGate from './components/AuthGate'
import HeaderNavbar, { type ActiveTab } from './components/HeaderNavbar'
import { LOCAL_DEMO_MODE } from './lib/runtimeMode'

const CommandDashboard = lazy(() => import('./components/DashboardTab'))
const RouteHistoryPanel = lazy(() => import('./components/RouteHistoryPanel'))
const RouteHistory = lazy(() => import('./components/RouteHistory'))
const ScheduleBoard = lazy(() => import('./components/ScheduleBoard'))
const LoadProfilePanel = lazy(() => import('./components/LoadProfilePanel'))
const SourceTrustCenter = lazy(() => import('./components/SourceTrustCenter'))
const ComplianceGuard = lazy(() => import('./components/ComplianceGuard'))
const AssuranceWorkspace = lazy(() => import('./components/AssuranceWorkspace'))

function OperationsApp() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('assurance')
  const [selectedProfileId, setSelectedProfileId] = useState<string | null>(null)

  // The command console manages its own full-height layout, so it renders
  // full-bleed. Every other module keeps the centred, padded reading column.
  const isCommandConsole = activeTab === 'command'

  return (
    <div className="h-screen bg-slate-950 text-slate-100 font-sans flex flex-col overflow-hidden">
      <HeaderNavbar activeTab={activeTab} setActiveTab={setActiveTab} />
      <main
        className={
          isCommandConsole
            ? 'flex-1 min-h-0'
            : 'flex-1 min-h-0 overflow-y-auto max-w-7xl w-full mx-auto p-4 md:p-6 space-y-6'
        }
      >
        <Suspense fallback={<div className="rounded-2xl border border-slate-800 bg-slate-900 p-8 text-sm text-slate-400">Loading evidence-assurance module…</div>}>
        {activeTab === 'command' && <CommandDashboard />}
        {activeTab === 'history' && <RouteHistoryPanel />}
        {activeTab === 'dispatch' && <RouteHistory onBack={() => setActiveTab('command')} onSchedule={() => setActiveTab('schedule')} />}
        {activeTab === 'schedule' && <ScheduleBoard onBack={() => setActiveTab('command')} onHistory={() => setActiveTab('dispatch')} />}
        {activeTab === 'assurance' && <AssuranceWorkspace />}
        {activeTab === 'sourceTrust' && <SourceTrustCenter />}
        {activeTab === 'compliance' && <ComplianceGuard />}
        {activeTab === 'loadProfiles' && (
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
            <h2 className="text-xl font-bold text-slate-100">📦 Cargo Load Profiles</h2>
            <p className="mb-4 mt-1 text-xs text-slate-400">Manage cargo constraints for rapid route evaluations.</p>
            <LoadProfilePanel
              selectedId={selectedProfileId}
              onSelect={(profile) => setSelectedProfileId(profile?.id ?? null)}
              onContinue={() => setActiveTab('command')}
            />
          </div>
        )}
        </Suspense>
      </main>
      <footer className="bg-slate-950 border-t border-slate-900 py-4 px-6 text-center text-xs text-slate-500">
        {LOCAL_DEMO_MODE
          ? 'EvidenceGate v7 research • Offline judge demonstration • Staged evidence • No operational authority'
          : 'EvidenceGate v7 research • Authenticated evidence assurance • No movement authority'}
      </footer>
    </div>
  )
}

export default function App() {
  return <AuthGate><OperationsApp /></AuthGate>
}

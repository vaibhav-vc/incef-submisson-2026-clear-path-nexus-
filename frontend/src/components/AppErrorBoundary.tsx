import { Component, type ReactNode } from 'react'
import './AppErrorBoundary.css'

/** Keep a failed render from looking like a successful or empty operations view. */
export default class AppErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <main className="app-recovery" aria-labelledby="recovery-title">
        <section className="app-recovery__panel" role="alert">
          <p className="app-recovery__eyebrow">EvidenceGate / Workspace interrupted</p>
          <h1 id="recovery-title">The workspace could not be displayed.</h1>
          <p>No decision or release status can be confirmed from this screen. Reload to reconnect and review the latest server records.</p>
          <button type="button" onClick={() => window.location.reload()}>Reload workspace</button>
          <p className="app-recovery__note">Unsaved form inputs may be lost. If an approval or dispatch was in progress, check its recorded status before attempting it again.</p>
        </section>
      </main>
    )
  }
}

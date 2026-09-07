import { useEffect, useId, useState, type ReactNode } from 'react'
import type { Session } from '@supabase/supabase-js'
import { authConfigurationError, isSupabaseConfigured, onAuthStateChange, supabase } from '../services/supabaseClient'
import { watchSession, withTimeout } from '../lib/sessionLifecycle'
import './AuthGate.css'

const EVIDENCE_STATES = [
  { name: 'Hard blocked', tone: 'blocked', description: 'A safety or compliance rule prevents release.' },
  { name: 'Unavailable', tone: 'unavailable', description: 'Required evidence could not be obtained.' },
  { name: 'Hold', tone: 'hold', description: 'Evidence exists but is incomplete, stale, or unverified.' },
  { name: 'Ready', tone: 'ready', description: 'Every required record is current and valid.' },
] as const

function EvidenceGateMark() {
  return (
    <svg className="auth-brand__mark" viewBox="0 0 40 40" aria-hidden="true" focusable="false">
      <path d="M7 8.5h16.5L33 18v13.5H16.5L7 22V8.5Z" />
      <path d="M13 14h10l4 4v7h-9l-5-4v-7Z" />
      <path d="M23 8.5V14M7 22h6M27 25l6 6" />
    </svg>
  )
}

function SessionCheck() {
  return (
    <div className="auth-check" role="status" aria-live="polite">
      <EvidenceGateMark />
      <span className="auth-check__line" aria-hidden="true" />
      <p>Verifying secure session</p>
    </div>
  )
}

function ConfigurationRequired() {
  return (
    <main className="auth-config" aria-labelledby="configuration-title">
      <section className="auth-config__panel">
        <div className="auth-brand" aria-label="EvidenceGate by ClearPath Nexus">
          <EvidenceGateMark />
          <span className="auth-brand__name">EvidenceGate</span>
          <span className="auth-brand__edition">ClearPath Nexus 6.0</span>
        </div>
        <p className="auth-kicker">Configuration required</p>
        <h1 id="configuration-title">Connect trusted services before operating.</h1>
        <p className="auth-config__intro">
          This build has missing or invalid Supabase configuration. EvidenceGate has stopped before sign-in
          instead of substituting demo credentials or fabricated live data.
        </p>
        <p className="auth-config__diagnostic" role="status">{authConfigurationError}</p>
        <div className="auth-config__requirements" aria-label="Required configuration">
          <p><code>VITE_SUPABASE_URL</code><span>Public Supabase project URL</span></p>
          <p><code>VITE_SUPABASE_ANON_KEY</code><span>Public RLS-scoped anonymous key</span></p>
          <p><code>/api/v1</code><span>Reverse proxy to the configured EvidenceGate backend</span></p>
        </div>
        <p className="auth-config__help">
          Configure these values, rebuild the web client, and verify <code>/ready</code> before a live demonstration.
        </p>
      </section>
    </main>
  )
}

export default function AuthGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [checking, setChecking] = useState(true)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const errorId = useId()

  useEffect(() => {
    const client = supabase
    if (!client) {
      setChecking(false)
      return
    }
    return watchSession<Session>({
      read: async () => {
        const { data, error: sessionError } = await client.auth.getSession()
        return { session: data.session, error: sessionError }
      },
      subscribe: onAuthStateChange,
      onSession: (nextSession) => {
        setSession(nextSession)
        if (nextSession) setError(null)
        setChecking(false)
      },
      onError: () => {
        setError('The secure session could not be verified. Check your connection and sign in again.')
        setChecking(false)
      },
    })
  }, [])

  async function handleSignIn(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting) return
    setSubmitting(true)
    setError(null)

    if (!supabase) {
      setError('Live authentication is not configured for this build.')
      setSubmitting(false)
      return
    }

    try {
      const { error: signInError } = await withTimeout(supabase.auth.signInWithPassword({
        email: email.trim(),
        password,
      }))
      if (signInError) setError(signInError.message)
      else setPassword('')
    } catch (signInError) {
      setError(signInError instanceof Error ? signInError.message : 'Sign-in could not complete. Check your connection and retry.')
    } finally {
      setSubmitting(false)
    }
  }

  if (!isSupabaseConfigured || !supabase) return <ConfigurationRequired />
  if (checking) return <SessionCheck />
  if (session) return <>{children}</>

  return (
    <main className="auth-shell">
      <a className="auth-skip-link" href="#operator-sign-in">Skip to sign in</a>

      <section className="auth-story" aria-labelledby="evidencegate-title">
        <div className="auth-brand" aria-label="EvidenceGate by ClearPath Nexus">
          <EvidenceGateMark />
          <span className="auth-brand__name">EvidenceGate</span>
          <span className="auth-brand__edition">ClearPath Nexus 6.0</span>
        </div>

        <div className="auth-hero">
          <p className="auth-kicker">Rail decision assurance</p>
          <h1 id="evidencegate-title">Decide with evidence.<span>Release with confidence.</span></h1>
          <p className="auth-intro">
            Route constraints, source provenance, and dispatch authorization—resolved into one
            auditable decision.
          </p>
        </div>

        <div className="auth-state-panel" aria-labelledby="decision-language-title">
          <div className="auth-state-panel__heading">
            <p id="decision-language-title">Decision language</p>
            <span>Fail-closed by design</span>
          </div>
          <ol className="auth-state-list">
            {EVIDENCE_STATES.map((state, index) => (
              <li className={`auth-state auth-state--${state.tone}`} key={state.name}>
                <span className="auth-state__index" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
                <span className="auth-state__signal" aria-hidden="true" />
                <span className="auth-state__copy"><strong>{state.name}</strong><span>{state.description}</span></span>
              </li>
            ))}
          </ol>
        </div>

        <p className="auth-principle">
          <span aria-hidden="true">↳</span>
          If evidence cannot be verified, EvidenceGate never substitutes certainty.
        </p>
      </section>

      <aside className="auth-access" aria-labelledby="sign-in-title">
        <div className="auth-access__rail" aria-hidden="true"><span /><span /><span /></div>
        <div className="auth-access__content">
          <div className="auth-access__eyebrow">
            <span className="auth-access__indicator" aria-hidden="true" />Secure operator access
          </div>

          <form id="operator-sign-in" className="auth-form" onSubmit={handleSignIn}>
            <div className="auth-form__heading">
              <p className="auth-form__step">01 / Identity</p>
              <h2 id="sign-in-title">Enter operations</h2>
              <p>Use your authorized ClearPath account to continue.</p>
            </div>

            <div className="auth-field">
              <label htmlFor="operator-email">Operator email</label>
              <input
                id="operator-email" name="email" type="email" inputMode="email"
                autoComplete="email" spellCheck={false} placeholder="name@organisation.in"
                value={email} onChange={(event) => setEmail(event.target.value)}
                aria-invalid={Boolean(error)} aria-describedby={error ? errorId : undefined}
                disabled={submitting} required
              />
            </div>

            <div className="auth-field">
              <label htmlFor="operator-password">Password</label>
              <input
                id="operator-password" name="password" type="password"
                autoComplete="current-password" placeholder="Enter your password"
                value={password} onChange={(event) => setPassword(event.target.value)}
                aria-invalid={Boolean(error)} aria-describedby={error ? errorId : undefined}
                disabled={submitting} required
              />
            </div>

            <div className="auth-form__message" aria-live="polite">
              {error ? (
                <p id={errorId} className="auth-form__error" role="alert"><span aria-hidden="true">!</span>{error}</p>
              ) : (
                <p>Your credentials are verified by Supabase.</p>
              )}
            </div>

            <button className="auth-submit" type="submit" disabled={submitting}>
              <span>{submitting ? 'Verifying access…' : 'Continue to EvidenceGate'}</span>
              <svg viewBox="0 0 20 20" aria-hidden="true" focusable="false"><path d="M4 10h11M11 6l4 4-4 4" /></svg>
            </button>
          </form>
        </div>

        <footer className="auth-access__footer">
          <span>Protected decision workspace</span><span>EvidenceGate / 2026</span>
        </footer>
      </aside>
    </main>
  )
}

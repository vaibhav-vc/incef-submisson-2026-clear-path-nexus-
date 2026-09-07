import { useCallback, useEffect, useRef, useState } from 'react'
import type { LoadProfile } from '../types/loadProfile'
import { createLoadProfile, readLoadProfiles, writeLoadProfiles } from '../types/loadProfile'

interface Props {
  selectedId: string | null
  onSelect: (profile: LoadProfile | null) => void
  onContinue?: () => void
}

type View = 'list' | 'create'

const EMPTY_FORM = {
  name: '',
  height: '4.5',
  width: '3.0',
  weight: '120',
  compartments: '1',
  compartmentPurpose: '',
  notes: '',
}

// Scroll-snap helper: brings the focused input into view above the virtual keyboard
function useKeyboardSnapFocus() {
  useEffect(() => {
    const onFocusIn = (e: FocusEvent) => {
      const el = e.target as HTMLElement
      if (!el || !['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)) return
      // Small delay lets the keyboard slide up first
      setTimeout(() => {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }, 120)
    }
    document.addEventListener('focusin', onFocusIn, true)
    return () => document.removeEventListener('focusin', onFocusIn, true)
  }, [])
}

export default function LoadProfilePanel({ selectedId, onSelect, onContinue }: Props) {
  const [profiles, setProfiles] = useState<LoadProfile[]>([])
  const [view, setView] = useState<View>('create')
  const [form, setForm] = useState(EMPTY_FORM)
  const [formError, setFormError] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<LoadProfile | null>(null)
  const [saveAnim, setSaveAnim] = useState(false)
  const firstInputRef = useRef<HTMLInputElement>(null)

  useKeyboardSnapFocus()

  const refresh = useCallback(() => {
    setProfiles(readLoadProfiles())
  }, [])

  useEffect(() => {
    refresh()
    const stored = readLoadProfiles()
    if (stored.length > 0) {
      setView('list')
      if (selectedId && stored.some((p) => p.id === selectedId)) return
      onSelect(stored[0])
    } else {
      setView('create')
      onSelect(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Auto-focus first field when switching to create view
  useEffect(() => {
    if (view === 'create') {
      setTimeout(() => firstInputRef.current?.focus(), 80)
    }
  }, [view])

  const handleSave = () => {
    const height = parseFloat(form.height)
    const width = parseFloat(form.width)
    const weight = parseFloat(form.weight)
    const compartments = parseInt(form.compartments, 10)

    if (!form.name.trim()) {
      setFormError('Profile name is required.')
      firstInputRef.current?.focus()
      return
    }
    if ([height, width, weight].some((n) => Number.isNaN(n) || n <= 0)) {
      setFormError('Height, width, and weight must be positive numbers.')
      return
    }
    if (Number.isNaN(compartments) || compartments < 1) {
      setFormError('Compartment count must be at least 1.')
      return
    }

    const profile = createLoadProfile({
      name: form.name.trim(),
      height,
      width,
      weight,
      compartments,
      compartmentPurpose: form.compartmentPurpose.trim() || undefined,
      notes: form.notes.trim() || undefined,
    })

    const next = [...profiles, profile]
    writeLoadProfiles(next)
    setProfiles(next)
    onSelect(profile)
    setForm(EMPTY_FORM)
    setFormError(null)

    // Save animation pulse before switching views
    setSaveAnim(true)
    setTimeout(() => {
      setSaveAnim(false)
      setView('list')
    }, 400)
  }

  const confirmDelete = () => {
    if (!deleteTarget) return
    const next = profiles.filter((p) => p.id !== deleteTarget.id)
    writeLoadProfiles(next)
    setProfiles(next)
    if (selectedId === deleteTarget.id) {
      onSelect(next[0] ?? null)
      if (next.length === 0) setView('create')
    }
    setDeleteTarget(null)
  }

  return (
    <section className="flex flex-col gap-3">
      {/* ── Section header ─────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-60" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-blue-500" />
          </span>
          <h2 className="text-sm font-bold text-blue-300 uppercase tracking-widest">
            Load Profiles
          </h2>
        </div>
        {view === 'list' ? (
          <button
            type="button"
            onClick={() => {
              setView('create')
              setForm(EMPTY_FORM)
              setFormError(null)
            }}
            className="flex items-center gap-1 text-[10px] font-mono font-semibold text-emerald-400 hover:text-emerald-300 transition-colors group"
          >
            <svg
              className="h-3 w-3 transition-transform group-hover:rotate-90 duration-200"
              viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            New profile
          </button>
        ) : null}
      </div>

      {/* ── CREATE VIEW ────────────────────────────────────────── */}
      {view === 'create' ? (
        <div
          className="rounded-xl border border-blue-500/25 bg-slate-900/60 p-3.5 flex flex-col gap-3 animate-slide-up"
          style={{ boxShadow: '0 4px 24px -8px rgba(59,130,246,0.12)' }}
        >
          <p className="text-[11px] font-mono text-slate-500 leading-relaxed">
            Define cargo dimensions for corridor clearance checks.
          </p>

          {/* Profile name */}
          <label className="flex flex-col gap-1.5">
            <span className="text-[11px] font-mono font-medium text-slate-400 tracking-wide">
              Profile name <span className="text-blue-500">*</span>
            </span>
            <input
              ref={firstInputRef}
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="e.g. Oversize turbine blades"
              className="w-full px-3 py-2.5 bg-slate-900/90 border border-slate-700/80 rounded-lg text-white font-mono text-sm placeholder:text-slate-600"
            />
          </label>

          {/* HWW grid */}
          <div className="grid grid-cols-3 gap-2">
            {(
              [
                ['height', 'Height (m)'],
                ['width', 'Width (m)'],
                ['weight', 'Weight (T)'],
              ] as const
            ).map(([key, label]) => (
              <label key={key} className="flex flex-col gap-1">
                <span className="text-[10px] font-mono text-slate-500">{label}</span>
                <input
                  type="number"
                  step="0.1"
                  value={form[key]}
                  onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                  className="w-full px-2 py-2 bg-slate-900/90 border border-slate-700/80 rounded-lg text-white font-mono text-sm"
                />
              </label>
            ))}
          </div>

          {/* Compartments */}
          <label className="flex flex-col gap-1.5">
            <span className="text-[11px] font-mono text-slate-400">Number of compartments</span>
            <input
              type="number"
              min={1}
              value={form.compartments}
              onChange={(e) => setForm((f) => ({ ...f, compartments: e.target.value }))}
              className="w-full px-3 py-2 bg-slate-900/90 border border-slate-700/80 rounded-lg text-white font-mono text-sm"
            />
          </label>

          {/* Compartment purpose */}
          <label className="flex flex-col gap-1.5">
            <span className="text-[11px] font-mono text-slate-400">
              Why does compartment count matter for this load?
            </span>
            <textarea
              value={form.compartmentPurpose}
              onChange={(e) => setForm((f) => ({ ...f, compartmentPurpose: e.target.value }))}
              placeholder="e.g. Hazmat isolation, weight distribution across wagons…"
              rows={2}
              className="w-full px-3 py-2 bg-slate-900/90 border border-slate-700/80 rounded-lg text-white font-mono text-xs resize-none"
            />
          </label>

          {/* Notes */}
          <label className="flex flex-col gap-1.5">
            <span className="text-[11px] font-mono text-slate-400">Notes (optional)</span>
            <input
              value={form.notes}
              onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
              className="w-full px-3 py-2 bg-slate-900/90 border border-slate-700/80 rounded-lg text-white font-mono text-sm"
            />
          </label>

          {/* Error */}
          {formError ? (
            <div className="flex items-center gap-2 rounded-lg border border-red-700/40 bg-red-950/20 px-3 py-2">
              <svg className="h-3.5 w-3.5 shrink-0 text-red-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
              <p className="text-[11px] font-mono text-red-400">{formError}</p>
            </div>
          ) : null}

          {/* Actions */}
          <div className="flex gap-2 pt-0.5">
            {profiles.length > 0 ? (
              <button
                type="button"
                onClick={() => setView('list')}
                className="flex-1 rounded-lg border border-slate-600/60 bg-slate-800/50 px-3 py-2.5 text-[11px] font-mono text-slate-400 hover:bg-slate-700/50 hover:text-slate-200 transition btn-press"
              >
                Cancel
              </button>
            ) : null}
            <button
              type="button"
              onClick={handleSave}
              className={`flex-1 ripple-btn btn-press relative rounded-lg px-3 py-2.5 text-[11px] font-semibold text-white transition-all duration-200 shadow-lg flex items-center justify-center gap-1.5 ${
                saveAnim
                  ? 'bg-emerald-600 shadow-emerald-900/50 scale-[0.97]'
                  : 'bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 shadow-blue-900/40'
              }`}
            >
              {saveAnim ? (
                <>
                  <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                  Saved!
                </>
              ) : (
                <>
                  <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" />
                  </svg>
                  Save load profile
                </>
              )}
            </button>
          </div>
        </div>
      ) : (
        /* ── LIST VIEW ─────────────────────────────────────────── */
        <ul className="flex flex-col gap-2 stagger-children">
          {profiles.map((p) => {
            const active = p.id === selectedId
            return (
              <li
                key={p.id}
                className={`rounded-xl border p-3 card-lift cursor-pointer transition-colors ${
                  active
                    ? 'border-blue-500/60 bg-blue-950/30 shadow-sm shadow-blue-900/30'
                    : 'border-slate-700/60 bg-slate-900/40 hover:border-slate-500/60'
                }`}
              >
                <button type="button" onClick={() => onSelect(p)} className="w-full text-left">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="font-semibold text-white text-sm truncate">{p.name}</p>
                      <p className="font-mono text-[11px] text-slate-400 mt-0.5">
                        {p.height}m × {p.width}m · {p.weight}T ·{' '}
                        {p.compartments} compartment{p.compartments === 1 ? '' : 's'}
                      </p>
                      {p.compartmentPurpose ? (
                        <p className="mt-1 text-[10px] font-mono text-slate-500 line-clamp-2">
                          {p.compartmentPurpose}
                        </p>
                      ) : null}
                    </div>
                    {active && (
                      <span className="shrink-0 mt-0.5 flex h-5 w-5 items-center justify-center rounded-full bg-blue-600">
                        <svg className="h-3 w-3 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                        </svg>
                      </span>
                    )}
                  </div>
                </button>
                <div className="mt-2 flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setDeleteTarget(p)}
                    className="flex items-center gap-1 text-[10px] font-mono text-red-500/70 hover:text-red-400 transition-colors group"
                  >
                    <svg className="h-3 w-3 group-hover:scale-110 transition-transform" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                    Delete
                  </button>
                </div>
              </li>
            )
          })}
        </ul>
      )}

      {/* ── Continue button ────────────────────────────────────── */}
      {selectedId && view === 'list' && onContinue ? (
        <button
          type="button"
          onClick={onContinue}
          className="ripple-btn btn-press w-full rounded-xl border border-emerald-600/40 bg-gradient-to-r from-emerald-950/40 to-teal-950/30 px-3 py-2.5 text-[11px] font-mono font-semibold text-emerald-300 hover:from-emerald-950/60 hover:to-teal-950/50 hover:border-emerald-500/60 transition-all flex items-center justify-center gap-2"
        >
          <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M13 7l5 5m0 0l-5 5m5-5H6" />
          </svg>
          Continue to routing
        </button>
      ) : null}

      {/* ── Delete confirmation modal ───────────────────────────── */}
      {deleteTarget ? (
        <div
          className="fixed inset-0 z-[100] flex items-end sm:items-center justify-center p-4"
          style={{ background: 'rgba(0,0,0,0.78)', backdropFilter: 'blur(8px)' }}
        >
          <div
            className="w-full max-w-sm rounded-2xl border border-red-900/40 bg-[#0c1420] shadow-2xl shadow-red-950/60 overflow-hidden animate-slide-up"
          >
            {/* Red accent bar */}
            <div className="h-1 w-full bg-gradient-to-r from-red-700 via-red-500 to-orange-500" />

            <div className="p-5 flex flex-col gap-4">
              {/* Icon + title */}
              <div className="flex items-start gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-red-700/50 bg-red-950/60">
                  <svg className="h-5 w-5 text-red-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </div>
                <div>
                  <h3 className="text-sm font-bold text-white">Delete Load Profile?</h3>
                  <p className="text-[11px] font-mono text-slate-400 mt-0.5">This action cannot be undone</p>
                </div>
              </div>

              {/* Profile details card */}
              <div className="rounded-xl border border-slate-700/50 bg-slate-900/60 p-3 flex flex-col gap-1">
                <p className="font-semibold text-white text-sm">{deleteTarget.name}</p>
                <p className="font-mono text-[11px] text-slate-400">
                  {deleteTarget.height}m × {deleteTarget.width}m · {deleteTarget.weight}T ·{' '}
                  {deleteTarget.compartments} compartment{deleteTarget.compartments === 1 ? '' : 's'}
                </p>
                {deleteTarget.compartmentPurpose && (
                  <p className="text-[10px] font-mono text-slate-500 line-clamp-2 mt-1">
                    {deleteTarget.compartmentPurpose}
                  </p>
                )}
              </div>

              <p className="text-xs font-mono text-slate-400 leading-relaxed">
                Are you sure you want to permanently delete{' '}
                <span className="text-white font-semibold">"{deleteTarget.name}"</span>? Any routes
                evaluated with it will not be affected, but the profile itself cannot be recovered.
              </p>

              {/* Actions */}
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setDeleteTarget(null)}
                  className="flex-1 ripple-btn btn-press rounded-xl border border-slate-600/60 bg-slate-800/60 py-2.5 text-xs font-mono text-slate-300 hover:bg-slate-700/60 hover:text-white transition"
                >
                  Keep Profile
                </button>
                <button
                  type="button"
                  onClick={confirmDelete}
                  className="flex-1 ripple-btn btn-press rounded-xl bg-gradient-to-r from-red-700 to-red-600 hover:from-red-600 hover:to-red-500 py-2.5 text-xs font-semibold text-white shadow-lg shadow-red-950/40 transition flex items-center justify-center gap-1.5"
                >
                  <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                  Yes, Delete
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  )
}

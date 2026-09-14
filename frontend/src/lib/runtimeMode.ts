export type AppRuntimeMode = 'online' | 'offline-judge'

/** Parse public boolean flags without treating arbitrary non-empty strings as enabled. */
export function publicBooleanFlag(value: string | undefined): boolean {
  return value?.trim().toLowerCase() === 'true'
}

/**
 * Resolve the public runtime contract. The named mode is canonical; the old
 * boolean remains supported for the Docker judge bundle and cannot override an
 * explicitly selected online build.
 */
export function resolveRuntimeMode(
  configuredMode: string | undefined,
  legacyLocalDemoFlag: string | undefined,
): AppRuntimeMode {
  const normalized = configuredMode?.trim().toLowerCase()
  if (normalized && normalized !== 'online' && normalized !== 'offline-judge') {
    throw new Error('VITE_APP_MODE must be either "online" or "offline-judge".')
  }
  const legacyOffline = publicBooleanFlag(legacyLocalDemoFlag)
  if (normalized === 'online' && legacyOffline) {
    throw new Error('Conflicting runtime flags: online mode cannot enable the local demo bypass.')
  }
  return normalized === 'offline-judge' || legacyOffline ? 'offline-judge' : 'online'
}

/**
 * Offline judge builds may call the bundled backend only through the page's
 * own origin. This prevents a stale deployment variable from silently sending
 * judge inputs to a cloud API.
 */
export function resolveApiBaseUrl(
  configuredUrl: string | undefined,
  mode: AppRuntimeMode,
): string {
  const value = configuredUrl?.trim() || '/api/v1'
  if (value.startsWith('/') && !value.startsWith('//')) return value.replace(/\/$/, '') || '/'
  if (mode === 'offline-judge') {
    throw new Error('Offline judge mode requires a same-origin VITE_API_BASE_URL such as /api/v1.')
  }
  let parsed: URL
  try {
    parsed = new URL(value)
  } catch {
    throw new Error('VITE_API_BASE_URL must be a same-origin path or an absolute HTTPS URL.')
  }
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname)
  if ((parsed.protocol !== 'https:' && !(loopback && parsed.protocol === 'http:')) ||
      parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error('VITE_API_BASE_URL must use HTTPS without credentials, query parameters, or fragments.')
  }
  return value.replace(/\/$/, '')
}

interface PublicBuildMeta {
  env?: {
    MODE?: string
    VITE_APP_MODE?: string
    VITE_LOCAL_DEMO_MODE?: string
  }
}

// This module is also imported by vite.config.ts, whose Node type context does
// not include Vite's global ImportMetaEnv augmentation.
const publicEnv = (import.meta as PublicBuildMeta).env
const viteBuildMode = publicEnv?.MODE
const namedBuildMode = viteBuildMode === 'online' || viteBuildMode === 'offline-judge'
  ? viteBuildMode
  : undefined

export const APP_RUNTIME_MODE = resolveRuntimeMode(
  publicEnv?.VITE_APP_MODE ?? namedBuildMode,
  publicEnv?.VITE_LOCAL_DEMO_MODE,
)

/** The auth bypass and external-resource guards share this single decision. */
export const LOCAL_DEMO_MODE = APP_RUNTIME_MODE === 'offline-judge'

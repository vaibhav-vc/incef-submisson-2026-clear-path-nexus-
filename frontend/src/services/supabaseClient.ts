import { createClient, type Session, type SupabaseClient } from '@supabase/supabase-js'
import { validateAuthConfiguration } from '../lib/authConfiguration'
import { withTimeout } from '../lib/sessionLifecycle'

// Auth stays with Supabase, same as the Android client: we sign in here and
// lift the access token off the session to present to the backend as a
// bearer token. The backend verifies it via JWKS (see
// backend/app/core/security.py). No credentials are stored or minted here.
//
// The anon key is a public, RLS-scoped key (same one embedded in
// android/.../SupabaseClient.kt) - it is meant to ship in client bundles.
const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL as string | undefined
const SUPABASE_ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined

const configuration = validateAuthConfiguration(SUPABASE_URL, SUPABASE_ANON_KEY)
export const authConfigurationError = configuration.error
export const isSupabaseConfigured = !authConfigurationError

if (!isSupabaseConfigured) {
  // Fail loud in dev rather than silently sending unauthenticated requests
  // that the backend will 401 on one-by-one.
  console.error(
    '[supabaseClient] Public Supabase configuration is missing or invalid. ' +
      'The application will remain in CONFIGURATION_REQUIRED until these are supplied.',
  )
}

export const supabase: SupabaseClient | null = isSupabaseConfigured
  ? createClient(configuration.url, configuration.key)
  : null

export async function getAccessToken(): Promise<string | null> {
  if (!supabase) return null
  const { data, error } = await withTimeout(supabase.auth.getSession())
  if (error) {
    // Do not send a protected request without a token when session recovery failed.
    throw new Error('The secure session could not be read. Sign in again.', { cause: error })
  }
  return data.session?.access_token ?? null
}

export function onAuthStateChange(callback: (session: Session | null) => void) {
  if (!supabase) {
    callback(null)
    return () => undefined
  }
  const {
    data: { subscription },
  } = supabase.auth.onAuthStateChange((_event, session) => callback(session))
  return () => subscription.unsubscribe()
}

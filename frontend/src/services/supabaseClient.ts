import { createClient, type Session, type SupabaseClient } from '@supabase/supabase-js'

// Auth stays with Supabase, same as the Android client: we sign in here and
// lift the access token off the session to present to the backend as a
// bearer token. The backend verifies it via JWKS (see
// backend/app/core/security.py). No credentials are stored or minted here.
//
// The anon key is a public, RLS-scoped key (same one embedded in
// android/.../SupabaseClient.kt) - it is meant to ship in client bundles.
const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL as string | undefined
const SUPABASE_ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined

export const isSupabaseConfigured = Boolean(SUPABASE_URL && SUPABASE_ANON_KEY)

if (!isSupabaseConfigured) {
  // Fail loud in dev rather than silently sending unauthenticated requests
  // that the backend will 401 on one-by-one.
  console.error(
    '[supabaseClient] VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY are not set. ' +
      'The application will remain in CONFIGURATION_REQUIRED until these are supplied.',
  )
}

export const supabase: SupabaseClient | null = isSupabaseConfigured
  ? createClient(SUPABASE_URL as string, SUPABASE_ANON_KEY as string)
  : null

export async function getAccessToken(): Promise<string | null> {
  if (!supabase) return null
  const { data, error } = await supabase.auth.getSession()
  if (error) {
    console.warn('[supabaseClient] failed to read session', error)
    return null
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

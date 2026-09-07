export interface AuthConfiguration {
  url: string
  key: string
  error: string | null
}

function jwtRole(key: string): unknown {
  try {
    const parts = key.split('.')
    if (parts.length !== 3) return undefined
    return JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')))?.role
  } catch {
    return undefined
  }
}

/** Vite exposes VITE_* values. Reject known server keys before bundling begins. */
export function assertPublicBuildEnvironment(env: Record<string, string | undefined>): void {
  for (const [name, raw] of Object.entries(env)) {
    if (!name.startsWith('VITE_')) continue
    const value = raw?.trim() ?? ''
    if (value.includes('sb_secret_') || jwtRole(value) === 'service_role') {
      throw new Error('Refusing to bundle server credentials in public VITE_* configuration.')
    }
    if (/^https?:\/\//i.test(value)) {
      let parsed: URL
      try { parsed = new URL(value) } catch { continue }
      if (parsed.username || parsed.password) {
        throw new Error('Refusing to bundle a credential-bearing URL in public VITE_* configuration.')
      }
    }
  }
}

/** Validate public build configuration before the SDK can throw during import. */
export function validateAuthConfiguration(rawUrl?: string, rawKey?: string): AuthConfiguration {
  const url = rawUrl?.trim() ?? ''
  const key = rawKey?.trim() ?? ''
  const fail = (error: string): AuthConfiguration => ({ url, key, error })
  if (!url || !key) return fail('The public Supabase project URL and public API key are required.')
  try {
    const parsed = new URL(url)
    const local = ['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname)
    if ((parsed.protocol !== 'https:' && !(local && parsed.protocol === 'http:')) ||
        parsed.username || parsed.password || parsed.search || parsed.hash || parsed.pathname !== '/') {
      return fail('Use an HTTPS Supabase project URL (HTTP is permitted only for local development).')
    }
    if (parsed.hostname === 'your-project.supabase.co' || parsed.hostname === 'your-project-id.supabase.co') {
      return fail('Replace the template project URL with your actual Supabase origin.')
    }
  } catch {
    return fail('The Supabase project URL is not a valid absolute URL.')
  }
  if (key.startsWith('sb_secret_')) return fail('A server secret was supplied. Only a public publishable or anonymous key may be used in the browser.')
  if (key.startsWith('sb_publishable_') && key.length > 'sb_publishable_'.length) return { url, key, error: null }
  if (jwtRole(key) === 'anon') return { url, key, error: null }
  return fail('Use a public publishable key or legacy anonymous key, never a service-role key or placeholder.')
}

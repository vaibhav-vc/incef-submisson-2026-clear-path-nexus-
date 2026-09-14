/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_APP_MODE?: 'online' | 'offline-judge'
  readonly VITE_API_BASE_URL?: string
  readonly VITE_LOCAL_DEMO_MODE?: string
  readonly VITE_SUPABASE_URL?: string
  readonly VITE_SUPABASE_ANON_KEY?: string
  // Deployment-tunable values consumed by src/config.ts.
  readonly VITE_MAP_CENTER_LAT?: string
  readonly VITE_MAP_CENTER_LON?: string
  readonly VITE_MAP_DEFAULT_ZOOM?: string
  readonly VITE_MAP_ZONE_RADIUS_M?: string
  readonly VITE_MAP_CONDITION_RADIUS_M?: string
  readonly VITE_LIVEOPS_REFRESH_MS?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

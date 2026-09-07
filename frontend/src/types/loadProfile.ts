export interface LoadProfile {
  id: string
  name: string
  height: number
  width: number
  weight: number
  compartments: number
  /** Why compartment count matters for this load (distribution, hazmat isolation, etc.) */
  compartmentPurpose?: string
  notes?: string
  createdAt: string
}

const STORAGE_KEY = 'clearpath_load_profiles'

export function readLoadProfiles(): LoadProfile[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as LoadProfile[]
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

export function writeLoadProfiles(profiles: LoadProfile[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(profiles))
}

export function createLoadProfile(input: Omit<LoadProfile, 'id' | 'createdAt'>): LoadProfile {
  return {
    ...input,
    id: `lp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    createdAt: new Date().toISOString(),
  }
}

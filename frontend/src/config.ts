/**
 * Deployment-tunable frontend values.
 *
 * Map geometry and polling cadence remain deployment settings. Operational
 * corridor selections are intentionally absent: station choices come from the
 * authenticated backend directory at runtime.
 *
 * Every value falls back to its previous literal, so an unconfigured build
 * behaves exactly as before.
 */

function envNumber(value: string | undefined, fallback: number): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

/** Opening map view, used until a route or station set defines its own bounds. */
export const MAP_DEFAULT_CENTER: [number, number] = [
  envNumber(import.meta.env.VITE_MAP_CENTER_LAT, 21.1458),
  envNumber(import.meta.env.VITE_MAP_CENTER_LON, 79.0882),
]
export const MAP_DEFAULT_ZOOM = envNumber(import.meta.env.VITE_MAP_DEFAULT_ZOOM, 6)

/** Overlay circle radii in metres. */
export const MAP_ENVIRONMENTAL_ZONE_RADIUS_M = envNumber(
  import.meta.env.VITE_MAP_ZONE_RADIUS_M,
  12000,
)
export const MAP_CONDITION_RADIUS_M = envNumber(
  import.meta.env.VITE_MAP_CONDITION_RADIUS_M,
  5000,
)

/** How often the LiveOps control center re-polls the backend, in milliseconds. */
export const LIVEOPS_REFRESH_MS = envNumber(import.meta.env.VITE_LIVEOPS_REFRESH_MS, 15_000)

import type { Station } from '../types/route'
import type { OsmStation } from '../components/StationPickerModal'

export interface NearestStationResult {
  station: Station
  distanceKm: number
}

export function haversineKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6371
  const dLat = ((lat2 - lat1) * Math.PI) / 180
  const dLon = ((lon2 - lon1) * Math.PI) / 180
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) * Math.sin(dLon / 2) ** 2
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

export function findNearestStation(stations: Station[], lat: number, lon: number): NearestStationResult | null {
  if (stations.length === 0 || Number.isNaN(lat) || Number.isNaN(lon)) return null

  let best: NearestStationResult | null = null
  for (const station of stations) {
    const distanceKm = haversineKm(lat, lon, station.lat, station.lon)
    if (!best || distanceKm < best.distanceKm) {
      best = { station, distanceKm: Math.round(distanceKm * 10) / 10 }
    }
  }
  return best
}

// ── OSM Overpass: fetch real railway stations ─────────────────────────────────

const OVERPASS_URL = 'https://overpass-api.de/api/interpreter'

interface OverpassElement {
  type: 'node' | 'way'
  id: number
  lat?: number
  lon?: number
  center?: { lat: number; lon: number }
  tags?: Record<string, string>
}

/**
 * Query the OSM Overpass API for railway stations within `radiusKm` of a point.
 * Returns an array of OsmStation objects sorted by ascending distance.
 */
export async function fetchNearbyStationsOSM(
  lat: number,
  lon: number,
  radiusKm = 20,
): Promise<OsmStation[]> {
  const radiusM = radiusKm * 1000
  // Query both node and way features tagged railway=station or railway=halt
  const query = `
[out:json][timeout:20];
(
  node["railway"="station"](around:${radiusM},${lat},${lon});
  node["railway"="halt"](around:${radiusM},${lat},${lon});
  way["railway"="station"](around:${radiusM},${lat},${lon});
);
out center body;
`.trim()

  const resp = await fetch(OVERPASS_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: `data=${encodeURIComponent(query)}`,
  })

  if (!resp.ok) throw new Error(`Overpass API error: ${resp.status}`)
  const json: { elements: OverpassElement[] } = await resp.json()

  const seen = new Set<string>()
  const results: OsmStation[] = []

  for (const el of json.elements) {
    const elLat = el.lat ?? el.center?.lat
    const elLon = el.lon ?? el.center?.lon
    if (elLat == null || elLon == null) continue

    const name =
      el.tags?.name ??
      el.tags?.['name:en'] ??
      el.tags?.['name:hi'] ??
      `Unknown station`

    // Deduplicate by name + approximate position
    const key = `${name.toLowerCase().trim()}:${elLat.toFixed(2)}:${elLon.toFixed(2)}`
    if (seen.has(key)) continue
    seen.add(key)

    const distanceKm = Math.round(haversineKm(lat, lon, elLat, elLon) * 10) / 10

    results.push({
      osmId: el.id,
      name,
      lat: elLat,
      lon: elLon,
      distanceKm,
      operator: el.tags?.operator ?? el.tags?.network,
      stationType:
        el.tags?.['station'] ??
        el.tags?.['railway'] ??
        (el.tags?.['railway'] === 'halt' ? 'Halt' : 'Railway station'),
    })
  }

  // Sort by distance ascending
  results.sort((a, b) => a.distanceKm - b.distanceKm)
  return results
}

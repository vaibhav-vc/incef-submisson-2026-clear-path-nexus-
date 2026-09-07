import type { MapCondition, SegmentPath, Station } from '../types/route'
import { fetchMapConditions } from './api'

export function sampleRoutePoints(
  segments: SegmentPath[],
  stations: Station[],
  maxPoints = 6,
): { lat: number; lon: number; id: string }[] {
  const raw: { lat: number; lon: number; id: string }[] = []

  segments.forEach((segment) => {
    const coordinates = segment.coordinates
    if (coordinates.length === 0) return
    raw.push({ lat: coordinates[0][0], lon: coordinates[0][1], id: `${segment.id}-start` })
    if (coordinates.length > 2) {
      const midpoint = coordinates[Math.floor(coordinates.length / 2)]
      raw.push({ lat: midpoint[0], lon: midpoint[1], id: `${segment.id}-mid` })
    }
    const end = coordinates[coordinates.length - 1]
    raw.push({ lat: end[0], lon: end[1], id: `${segment.id}-end` })
  })

  stations.forEach((station) => {
    raw.push({ lat: station.lat, lon: station.lon, id: `st-${station.code}` })
  })

  const unique: { lat: number; lon: number; id: string }[] = []
  const seen = new Set<string>()
  for (const point of raw) {
    const key = `${point.lat.toFixed(3)}:${point.lon.toFixed(3)}`
    if (seen.has(key)) continue
    seen.add(key)
    unique.push(point)
  }
  return unique.slice(0, maxPoints)
}

export async function resolveMapConditions(opts: {
  segments: SegmentPath[]
  stations: Station[]
  destinationCode?: string
}): Promise<MapCondition[]> {
  const points = sampleRoutePoints(opts.segments, opts.stations)
  if (points.length === 0) return []

  const data = await fetchMapConditions({
    points,
    destination_code: opts.destinationCode,
  })
  if (data.status !== 'AVAILABLE') {
    const failures = Array.isArray(data.failures)
      ? data.failures
          .map(
            (failure: { point_id?: string; message?: string }) =>
              `${failure.point_id ?? 'point'}: ${failure.message ?? 'unavailable'}`,
          )
          .join('; ')
      : 'provider unavailable'
    throw new Error(`Map-condition provider unavailable (${failures})`)
  }
  return data.conditions as MapCondition[]
}

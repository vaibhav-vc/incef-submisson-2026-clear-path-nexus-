import { useCallback, useEffect, useRef, useState } from 'react'
import type { MapCondition, SegmentPath, Station } from '../types/route'
import { resolveMapConditions } from '../services/weatherConditions'

const POLL_MS = 10 * 60 * 1000

export function useLiveMapConditions(
  segments: SegmentPath[],
  stations: Station[],
  destinationCode?: string,
  enabled = true,
) {
  const [conditions, setConditions] = useState<MapCondition[]>([])
  const [loading, setLoading] = useState(false)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [error, setError] = useState<string | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const refresh = useCallback(async () => {
    if (!enabled) return
    setLoading(true)
    setError(null)
    try {
      const data = await resolveMapConditions({ segments, stations, destinationCode })
      setConditions(data)
      setLastUpdated(new Date())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Weather fetch failed')
    } finally {
      setLoading(false)
    }
  }, [segments, stations, destinationCode, enabled])

  useEffect(() => {
    refresh()
    timerRef.current = setInterval(refresh, POLL_MS)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [refresh])

  return { conditions, loading, lastUpdated, error, refresh }
}

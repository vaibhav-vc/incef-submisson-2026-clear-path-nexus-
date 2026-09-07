import type { OperatorLoadingWindow, RouteSuggestResponse, TrainLocationInput } from '../types/route'
import { suggestRoute } from './api'

function mergeRouteResults(legs: RouteSuggestResponse[]): RouteSuggestResponse {
  if (legs.length === 0) {
    throw new Error('No route legs to merge.')
  }

  const merged = { ...legs[legs.length - 1] }
  merged.route_ids = legs.map((leg) => leg.route_id)
  const seen = new Set<string>()
  const segments = legs.flatMap((leg) =>
    leg.segments.filter((seg) => {
      if (seen.has(seg.id)) return false
      seen.add(seg.id)
      return true
    }),
  )

  merged.segments = segments
  merged.remaining_km = legs.reduce((sum, leg) => sum + (leg.remaining_km ?? 0), 0)
  const allEstimatedHoursAvailable = legs.every((leg) => leg.estimated_hours != null)
  merged.estimated_hours = allEstimatedHoursAvailable
    ? legs.reduce((sum, leg) => sum + (leg.estimated_hours as number), 0)
    : undefined
  const allEtaHoursAvailable = legs.every((leg) => leg.eta_hours != null)
  merged.eta_hours = allEtaHoursAvailable
    ? legs.reduce((sum, leg) => sum + (leg.eta_hours as number), 0)
    : undefined
  merged.track_details = legs.flatMap((leg) => leg.track_details ?? [])
  merged.environmental_alerts = [...new Set(legs.flatMap((leg) => leg.environmental_alerts ?? []))]
  merged.train_position = legs[0].train_position
  merged.reliability_score = Math.min(...legs.map((leg) => leg.reliability_score))
  const decisionPrecedence = ['READY', 'HOLD', 'UNAVAILABLE', 'HARD_BLOCKED'] as const
  merged.decision_state = legs.reduce(
    (worst, leg) => decisionPrecedence.indexOf(leg.decision_state) > decisionPrecedence.indexOf(worst)
      ? leg.decision_state
      : worst,
    'READY' as RouteSuggestResponse['decision_state'],
  )

  if (merged.status === 'APPROVED') {
    merged.status = legs.every((leg) => leg.status === 'APPROVED') ? 'APPROVED' : 'HARD_BLOCKED'
  }

  return merged
}

export async function suggestRouteThroughWaypoints(payload: {
  cargo: { height: number; width: number; weight: number }
  destinationCodes: string[]
  location: TrainLocationInput
  portId: string
  vesselId: string
  trainArrivalHours: number
  loadingWindow?: OperatorLoadingWindow
}): Promise<RouteSuggestResponse> {
  const codes = payload.destinationCodes.map((c) => c.toUpperCase()).filter(Boolean)
  if (codes.length === 0) {
    throw new Error('Add at least one destination.')
  }

  let location = payload.location
  const legs: RouteSuggestResponse[] = []

  for (const destinationCode of codes) {
    const data = await suggestRoute({
      cargo: payload.cargo,
      destination_code: destinationCode,
      location,
      port_id: payload.portId,
      vessel_id: payload.vesselId,
      train_arrival_hours: payload.trainArrivalHours,
      loading_window: payload.loadingWindow,
    })
    legs.push(data)

    location = { mode: 'station', station_code: destinationCode }
  }

  return mergeRouteResults(legs)
}

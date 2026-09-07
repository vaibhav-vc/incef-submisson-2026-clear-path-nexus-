import type { EnvironmentalZone } from '../types/route'
import { CONDITION_SYMBOLS, type ConditionCategory, type ConditionType } from './conditionSymbols'

export interface MapSymbolEntry {
  icon: string
  title: string
  description: string
  category: 'markers' | 'routes' | 'weather' | 'environmental' | 'operational' | 'zones'
}

export const MAP_SYMBOL_GUIDE: MapSymbolEntry[] = [
  {
    icon: '📍',
    title: 'Station marker',
    description: 'Blue pin — railway junction or yard on the corridor (e.g. NGP, MMR, JNPT). Click for station code and name.',
    category: 'markers',
  },
  {
    icon: '🚆',
    title: 'Train position',
    description: 'Light-blue pin — train snapped to the nearest track from GPS, coordinates, or station input.',
    category: 'markers',
  },
  {
    icon: '🟢',
    title: 'Approved segment',
    description: 'Green line — track block cleared for cargo; safe to traverse.',
    category: 'routes',
  },
  {
    icon: '🔴',
    title: 'Blocked segment',
    description: 'Red line — clearance violation on this tract. Do not dispatch.',
    category: 'routes',
  },
  {
    icon: '🔵',
    title: 'Current segment',
    description: 'Bright blue thick line — block the train is on now.',
    category: 'routes',
  },
  ...Object.entries(CONDITION_SYMBOLS)
    .filter(([, s]) => s.category === 'weather')
    .map(([, s]) => ({
      icon: s.icon,
      title: s.label,
      description: s.detail,
      category: 'weather' as const,
    })),
  ...Object.entries(CONDITION_SYMBOLS)
    .filter(([, s]) => s.category === 'environmental')
    .map(([, s]) => ({
      icon: s.icon,
      title: s.label,
      description: s.detail,
      category: 'environmental' as const,
    })),
  ...Object.entries(CONDITION_SYMBOLS)
    .filter(([, s]) => s.category === 'operational')
    .map(([, s]) => ({
      icon: s.icon,
      title: s.label,
      description: s.detail,
      category: 'operational' as const,
    })),
  {
    icon: '🟧',
    title: 'Environmental zone',
    description: 'Semi-transparent polygon — area under active weather or environmental watch.',
    category: 'zones',
  },
]

/** Legacy zone type icons — maps old polygon zone types to symbols. */
export const ZONE_WEATHER_ICONS: Record<string, { icon: string; label: string; detail: string }> = {
  storm: { icon: '⛈️', label: 'Storm watch', detail: CONDITION_SYMBOLS.thunderstorm.detail },
  fog: { icon: '🌫️', label: 'Fog / mist', detail: CONDITION_SYMBOLS.fog.detail },
  cloud: { icon: '☁️', label: 'Cloud cover', detail: CONDITION_SYMBOLS.cloudy.detail },
  dust: { icon: '💨', label: 'Dust haze', detail: CONDITION_SYMBOLS.dust.detail },
  solar: { icon: '☀️', label: 'Solar radiation', detail: CONDITION_SYMBOLS.solar.detail },
}

export function zoneCentroid(coordinates: [number, number][]): { lat: number; lon: number } {
  const lat = coordinates.reduce((s, c) => s + c[0], 0) / coordinates.length
  const lon = coordinates.reduce((s, c) => s + c[1], 0) / coordinates.length
  return { lat, lon }
}

export function conditionsToZones(
  conditions: { id: string; type: ConditionType; category: ConditionCategory; lat: number; lon: number }[],
): EnvironmentalZone[] {
  const envWeather = conditions.filter((c) => c.category !== 'operational')
  return envWeather.map((c) => ({
    id: `zone-${c.id}`,
    type: c.type,
    coordinates: [
      [c.lat + 0.15, c.lon - 0.2],
      [c.lat + 0.15, c.lon + 0.2],
      [c.lat - 0.15, c.lon + 0.2],
      [c.lat - 0.15, c.lon - 0.2],
    ],
  }))
}

export { CONDITION_SYMBOLS, type ConditionType, type ConditionCategory }

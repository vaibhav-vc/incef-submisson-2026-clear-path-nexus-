export type ConditionCategory = 'weather' | 'environmental' | 'operational'

export type ConditionType =
  | 'clear'
  | 'partly_cloudy'
  | 'cloudy'
  | 'mist'
  | 'fog'
  | 'light_rain'
  | 'heavy_rain'
  | 'snow'
  | 'sleet'
  | 'thunderstorm'
  | 'strong_wind'
  | 'high_winds'
  | 'high_temp'
  | 'low_temp'
  | 'high_humidity'
  | 'low_humidity'
  | 'low_visibility'
  | 'high_uv'
  | 'icing'
  | 'hail'
  | 'general_alert'
  | 'storm_warning'
  | 'flood_risk'
  | 'landslide_risk'
  | 'wildfire_risk'
  | 'seismic_activity'
  | 'hazmat_alert'
  | 'air_pollution'
  | 'debris_on_track'
  | 'vegetation_risk'
  | 'all_clear'
  | 'good_signal'
  | 'weak_signal'
  | 'no_signal'
  | 'track_clear'
  | 'track_caution'
  | 'track_blocked'
  | 'maintenance'
  | 'station_active'
  | 'port_active'
  | 'solar'
  | 'dust'

export interface ConditionSymbol {
  icon: string
  label: string
  detail: string
  category: ConditionCategory
}

export const CONDITION_SYMBOLS: Record<ConditionType, ConditionSymbol> = {
  clear: {
    icon: '☀️',
    label: 'Clear / Sunny',
    detail: 'Good visibility — normal operating conditions.',
    category: 'weather',
  },
  partly_cloudy: {
    icon: '⛅',
    label: 'Partly Cloudy',
    detail: 'Partial cloud cover; minor visibility reduction possible.',
    category: 'weather',
  },
  cloudy: {
    icon: '☁️',
    label: 'Cloudy / Overcast',
    detail: 'Overcast skies; moderate visibility reduction along open track.',
    category: 'weather',
  },
  mist: {
    icon: '🌁',
    label: 'Mist',
    detail: 'Reduced visibility from light mist; proceed with caution.',
    category: 'weather',
  },
  fog: {
    icon: '🌫️',
    label: 'Fog',
    detail: 'Low visibility from dense fog; speed caps and extra block protection may apply.',
    category: 'weather',
  },
  light_rain: {
    icon: '🌦️',
    label: 'Light Rain',
    detail: 'Light precipitation; minor schedule risk and reduced braking performance.',
    category: 'weather',
  },
  heavy_rain: {
    icon: '🌧️',
    label: 'Heavy Rain',
    detail: 'High precipitation; flooding and washout risk on embankments.',
    category: 'weather',
  },
  snow: {
    icon: '🌨️',
    label: 'Snow',
    detail: 'Snowfall; traction and visibility reduced on exposed segments.',
    category: 'weather',
  },
  sleet: {
    icon: '🌨️',
    label: 'Sleet / Ice Pellets',
    detail: 'Mixed ice pellets; slippery rail conditions possible.',
    category: 'weather',
  },
  thunderstorm: {
    icon: '⛈️',
    label: 'Thunderstorm',
    detail: 'Lightning activity; high delay risk and signaling interference possible.',
    category: 'weather',
  },
  strong_wind: {
    icon: '💨',
    label: 'Strong Wind',
    detail: 'High wind speed; crosswind risk on elevated or open viaducts.',
    category: 'weather',
  },
  high_winds: {
    icon: '🌬️',
    label: 'High Winds',
    detail: 'Gusty conditions; empty wagon and overhead line risk.',
    category: 'weather',
  },
  high_temp: {
    icon: '🌡️',
    label: 'High Temperature',
    detail: 'Elevated ambient temperature; rail buckling and crew heat stress risk.',
    category: 'weather',
  },
  low_temp: {
    icon: '🥶',
    label: 'Low Temperature',
    detail: 'Cold conditions; frost and brittle rail risk on northern segments.',
    category: 'weather',
  },
  high_humidity: {
    icon: '💧',
    label: 'High Humidity',
    detail: 'Moist conditions; corrosion and brake efficiency concerns.',
    category: 'weather',
  },
  low_humidity: {
    icon: '🏜️',
    label: 'Low Humidity',
    detail: 'Dry conditions; dust and static discharge risk in open tract.',
    category: 'weather',
  },
  low_visibility: {
    icon: '👁️',
    label: 'Low Visibility',
    detail: 'Visibility hazard; sighting distance below safe dispatch threshold.',
    category: 'weather',
  },
  high_uv: {
    icon: '🔆',
    label: 'High UV Index',
    detail: 'Elevated UV risk; crew exposure limits on outdoor work.',
    category: 'weather',
  },
  icing: {
    icon: '🧊',
    label: 'Icing Risk',
    detail: 'Ice accumulation on rails and overhead equipment possible.',
    category: 'weather',
  },
  hail: {
    icon: '🌨️',
    label: 'Hail',
    detail: 'Hailstones; damage risk to rolling stock and wayside equipment.',
    category: 'weather',
  },
  solar: {
    icon: '☀️',
    label: 'Solar / Kp Alert',
    detail: 'Elevated geomagnetic activity; monitor wayside telemetry.',
    category: 'weather',
  },
  dust: {
    icon: '💨',
    label: 'Dust Haze',
    detail: 'Suspended dust reducing sighting distance in dry western segments.',
    category: 'weather',
  },
  general_alert: {
    icon: '⚠️',
    label: 'General Alert',
    detail: 'Operational caution — review corridor advisories before dispatch.',
    category: 'environmental',
  },
  storm_warning: {
    icon: '🌀',
    label: 'Storm Warning',
    detail: 'Severe storm activity; consider alternate routing or hold.',
    category: 'environmental',
  },
  flood_risk: {
    icon: '🌊',
    label: 'Flood Risk',
    detail: 'Water overflow risk near culverts and low-lying track sections.',
    category: 'environmental',
  },
  landslide_risk: {
    icon: '⛰️',
    label: 'Landslide Risk',
    detail: 'Terrain instability; monitor cuttings and hillside embankments.',
    category: 'environmental',
  },
  wildfire_risk: {
    icon: '🔥',
    label: 'Wildfire Risk',
    detail: 'Fire hazard in adjacent vegetation; smoke may reduce visibility.',
    category: 'environmental',
  },
  seismic_activity: {
    icon: '📳',
    label: 'Seismic Activity',
    detail: 'Earthquake risk zone; verify track geometry after any tremor.',
    category: 'environmental',
  },
  hazmat_alert: {
    icon: '☢️',
    label: 'Hazmat Alert',
    detail: 'Hazardous material incident or restriction in corridor vicinity.',
    category: 'environmental',
  },
  air_pollution: {
    icon: '🏭',
    label: 'Air Pollution',
    detail: 'Poor air quality; visibility and crew health may be affected.',
    category: 'environmental',
  },
  debris_on_track: {
    icon: '🪨',
    label: 'Debris on Track',
    detail: 'Track obstruction reported or suspected; verify before passage.',
    category: 'environmental',
  },
  vegetation_risk: {
    icon: '🌿',
    label: 'Vegetation Risk',
    detail: 'Overgrowth risk; branches may encroach on loading gauge.',
    category: 'environmental',
  },
  all_clear: {
    icon: '✅',
    label: 'All Clear',
    detail: 'Normal operations — no active environmental or weather alerts.',
    category: 'operational',
  },
  good_signal: {
    icon: '📶',
    label: 'Good Signal',
    detail: 'Strong connectivity for ETCS / wayside telemetry.',
    category: 'operational',
  },
  weak_signal: {
    icon: '📡',
    label: 'Weak Signal',
    detail: 'Low connectivity; telemetry gaps possible in this block.',
    category: 'operational',
  },
  no_signal: {
    icon: '📵',
    label: 'No Signal',
    detail: 'No connectivity; manual block working may be required.',
    category: 'operational',
  },
  track_clear: {
    icon: '🛤️',
    label: 'Track Clear',
    detail: 'Block cleared for cargo dimensions; safe passage.',
    category: 'operational',
  },
  track_caution: {
    icon: '⚠️',
    label: 'Track Caution',
    detail: 'Proceed with care — congestion or advisory in effect.',
    category: 'operational',
  },
  track_blocked: {
    icon: '🚫',
    label: 'Track Blocked',
    detail: 'Route unavailable — clearance violation or hard block.',
    category: 'operational',
  },
  maintenance: {
    icon: '🔧',
    label: 'Maintenance',
    detail: 'Work in progress; temporary speed restrictions may apply.',
    category: 'operational',
  },
  station_active: {
    icon: '🏢',
    label: 'Station Active',
    detail: 'Operational station on the corridor.',
    category: 'operational',
  },
  port_active: {
    icon: '⚓',
    label: 'Port Active',
    detail: 'Port operations active; berth sync window applies.',
    category: 'operational',
  },
}

export const CATEGORY_COLORS: Record<ConditionCategory, { stroke: string; fill: string; dot: string }> = {
  weather: { stroke: '#38BDF8', fill: 'rgba(56, 189, 248, 0.2)', dot: '#38BDF8' },
  environmental: { stroke: '#F97316', fill: 'rgba(249, 115, 22, 0.2)', dot: '#F97316' },
  operational: { stroke: '#22C55E', fill: 'rgba(34, 197, 94, 0.2)', dot: '#22C55E' },
}

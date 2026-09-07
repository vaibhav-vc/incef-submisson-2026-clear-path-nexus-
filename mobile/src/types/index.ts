export type WeatherCondition = 'clear' | 'clouds' | 'rain' | 'thunderstorm' | 'snow' | 'unknown';

export type RouteStatus = 'APPROVED' | 'CAUTION' | 'HARD_BLOCKED';

export type BentoSize = 'small' | 'medium' | 'large' | 'half';

export type ToastType = 'success' | 'warning' | 'error' | 'info';

export interface Station {
  code: string;
  name: string;
  lat: number;
  lon: number;
  distanceKm?: number;
}

export interface WeatherData {
  stationCode: string;
  condition: WeatherCondition;
  temperature: number;
  windSpeed: number;
  visibility: number;
  score: number;
  fetchedAt: string;
}

export interface ScoreBreakdown {
  weather: { score: number; weight: 0.40 };
  port: { score: number; weight: 0.30 };
  congestion: { score: number; weight: 0.15 };
  historical: { score: number; weight: 0.15 };
}

export interface RouteEvaluation {
  id?: number;
  stations: Station[];
  breakdown: ScoreBreakdown;
  finalScore: number;
  status: RouteStatus;
  approvedAt?: string;
  createdAt: string;
}

export interface LoadProfile {
  id?: number;
  name: string;
  cargoHeight: number;
  cargoWidth: number;
  cargoWeight: number;
  createdAt: string;
}

export interface AppTheme {
  background: string;
  surface1: string;
  surface2: string;
  glass: string;
  glassBorder: string;
  primary: string;
  warning: string;
  danger: string;
  accent: string;
  textPrimary: string;
  textSecondary: string;
  textDisabled: string;
}

export interface ToastMessage {
  id: string;
  type: ToastType;
  message: string;
  duration?: number;
}

export interface TrackGeometry {
  coordinates: Array<{ lat: number; lon: number }>;
}

export interface BentoCard {
  size: BentoSize;
  glowColor?: string;
}

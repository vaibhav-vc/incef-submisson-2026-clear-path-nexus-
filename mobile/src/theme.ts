import type { AppTheme, RouteStatus, WeatherCondition } from './types';

export const palette = {
  base: '#070B14',
  surface: '#0F1623',
  raised: '#151E2E',
  glass: 'rgba(255, 255, 255, 0.05)',
  glassStrong: 'rgba(15, 22, 35, 0.6)',
  glassBorder: 'rgba(255, 255, 255, 0.10)',
  glassBorderSoft: 'rgba(255,255,255,0.08)',
  highlight: 'rgba(255,255,255,0.15)',
  primary: '#00FF88',
  warning: '#FF8C00',
  danger: '#FF3B5C',
  info: '#3B82F6',
  text: '#F0F4FF',
  textMuted: '#8892A4',
  textDisabled: '#3D4657',
  white: '#FFFFFF',
  black: '#000000',
  glowGreen: 'rgba(0, 255, 136, 0.15)',
  glowOrange: 'rgba(255, 140, 0, 0.15)',
  glowRed: 'rgba(255, 59, 92, 0.15)',
  input: 'rgba(255,255,255,0.05)',
  buttonSecondary: 'rgba(255,255,255,0.06)',
  destructiveBg: 'rgba(255, 59, 92, 0.15)',
  destructiveBorder: 'rgba(255, 59, 92, 0.30)',
  offlineBg: 'rgba(255, 140, 0, 0.15)',
  mapCurrent: '#3B82F6',
} as const;

export const darkMapStyle = [
  { elementType: 'geometry', stylers: [{ color: '#0a0f1e' }] },
  { elementType: 'labels.text.fill', stylers: [{ color: '#8892A4' }] },
  { elementType: 'labels.text.stroke', stylers: [{ color: '#070B14' }] },
  { featureType: 'road', elementType: 'geometry', stylers: [{ color: '#151E2E' }] },
  { featureType: 'road', elementType: 'geometry.stroke', stylers: [{ color: '#0F1623' }] },
  { featureType: 'water', stylers: [{ color: '#050A14' }] },
  { featureType: 'poi', stylers: [{ visibility: 'off' }] },
  {
    featureType: 'transit.station.rail',
    elementType: 'labels.icon',
    stylers: [{ visibility: 'on' }, { color: '#00FF88' }],
  },
];

export const lightTheme: AppTheme = {
  background: '#F5F5F5',
  surface1: '#FFFFFF',
  surface2: '#E0E0E0',
  glass: 'rgba(255, 255, 255, 0.85)',
  glassBorder: '#E0E0E0',
  primary: '#1A6B3C',
  warning: '#FF8C00',
  danger: '#FF3B5C',
  accent: '#FF8C00',
  textPrimary: '#1A1A1A',
  textSecondary: '#4B5563',
  textDisabled: '#9CA3AF',
};

export const darkTheme: AppTheme = {
  background: '#070B14',
  surface1: '#0F1623',
  surface2: '#151E2E',
  glass: 'rgba(15, 22, 35, 0.6)',
  glassBorder: 'rgba(255, 255, 255, 0.10)',
  primary: '#00FF88',
  warning: '#FF8C00',
  danger: '#FF3B5C',
  accent: '#3B82F6',
  textPrimary: '#F0F4FF',
  textSecondary: '#8892A4',
  textDisabled: '#3D4657',
};

export function getStatusColor(status: RouteStatus): string {
  switch (status) {
    case 'APPROVED':
      return '#00FF88';
    case 'CAUTION':
      return '#FF8C00';
    case 'HARD_BLOCKED':
      return '#FF3B5C';
    default:
      return '#8892A4';
  }
}

export function getWeatherEmoji(condition: WeatherCondition): string {
  switch (condition) {
    case 'clear':
      return '☀️';
    case 'clouds':
      return '☁️';
    case 'rain':
      return '🌧️';
    case 'thunderstorm':
      return '⛈️';
    case 'snow':
      return '❄️';
    default:
      return '❓';
  }
}

export function getScoreColor(score: number): string {
  if (score < 0.45) return '#FF3B5C';
  if (score < 0.65) return '#FF8C00';
  return '#00FF88';
}

export function statusColor(status?: RouteStatus): string {
  if (status === 'HARD_BLOCKED') return palette.danger;
  if (status === 'CAUTION') return palette.warning;
  return palette.primary;
}

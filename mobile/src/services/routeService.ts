import { fetchWeatherForStation } from './weatherService';
import { saveRouteHistory, getRouteHistoryList } from './database';
import type { Station, RouteEvaluation, RouteStatus, ScoreBreakdown } from '../types';

export async function evaluateRoute(stations: Station[]): Promise<RouteEvaluation> {
  if (stations.length < 2) {
    throw new Error('At least two stations (origin and destination) are required to evaluate a route.');
  }

  // Fetch weather for each station in parallel
  const weatherPromises = stations.map((st) =>
    fetchWeatherForStation(st.code, st.lat, st.lon).catch(() => null)
  );
  const weatherResults = await Promise.all(weatherPromises);

  // Compute average weather score
  const validScores = weatherResults.map((w) => w?.score ?? 0.7);
  const weatherScore = validScores.reduce((acc, curr) => acc + curr, 0) / validScores.length;

  // Placeholder scores as documented
  const portScore = 0.65;
  const congestionScore = 0.80;
  const historicalScore = 0.70;

  // Weighted formula
  const finalScore =
    0.40 * weatherScore +
    0.30 * portScore +
    0.15 * congestionScore +
    0.15 * historicalScore;

  // Status mapping
  let status: RouteStatus = 'HARD_BLOCKED';
  if (finalScore >= 0.65) {
    status = 'APPROVED';
  } else if (finalScore >= 0.45) {
    status = 'CAUTION';
  }

  const breakdown: ScoreBreakdown = {
    weather: { score: weatherScore, weight: 0.40 },
    port: { score: portScore, weight: 0.30 },
    congestion: { score: congestionScore, weight: 0.15 },
    historical: { score: historicalScore, weight: 0.15 },
  };

  return {
    stations,
    breakdown,
    finalScore,
    status,
    createdAt: new Date().toISOString(),
  };
}

export async function saveRoute(evaluation: RouteEvaluation): Promise<void> {
  await saveRouteHistory(evaluation);
}

export async function getRouteHistory(): Promise<RouteEvaluation[]> {
  return getRouteHistoryList();
}

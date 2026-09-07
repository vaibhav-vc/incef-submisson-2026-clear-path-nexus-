import { config } from '../config';
import { logger } from '../utils/logger';
import { getWeatherCache, saveWeatherCache } from './database';
import type { WeatherData, WeatherCondition } from '../types';

export function shouldRefresh(fetchedAt: string): boolean {
  try {
    const diff = Date.now() - new Date(fetchedAt).getTime();
    return diff > 10 * 60 * 1000; // 10 minutes
  } catch (error) {
    return true;
  }
}

function getWeatherConditionFromId(id: number): WeatherCondition {
  if (id >= 200 && id < 300) return 'thunderstorm';
  if (id >= 500 && id < 600) return 'rain';
  if (id >= 600 && id < 700) return 'snow';
  if (id >= 801 && id < 900) return 'clouds';
  if (id === 800) return 'clear';
  return 'unknown';
}

function calculateScoreFromId(id: number): number {
  if (id >= 200 && id < 300) return 0.2;
  if (id >= 500 && id < 600) return 0.6;
  if (id >= 600 && id < 700) return 0.5;
  if (id >= 800 && id < 900) {
    if (id === 800) return 1.0;
    return 0.7; // general clouds / unknown weather
  }
  return 0.7;
}

export async function fetchWeatherForStation(
  code: string,
  lat: number,
  lon: number
): Promise<WeatherData> {
  const cached = await getWeatherCache(code);
  if (cached && !shouldRefresh(cached.fetchedAt)) {
    logger.api(`Using cached weather for station: ${code}`);
    return cached;
  }

  logger.api(`Fetching fresh weather for ${code} (${lat}, ${lon})`);
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), config.requestTimeoutMs);

  try {
    const url = `${config.openWeatherBaseUrl}?lat=${lat}&lon=${lon}&appid=${config.weatherKey}&units=metric`;
    const response = await fetch(url, { signal: controller.signal });
    clearTimeout(timeoutId);

    if (!response.ok) {
      throw new Error(`OpenWeather API returned status ${response.status}`);
    }

    const data = await response.json();
    const weatherId = data.weather?.[0]?.id || 800;
    const condition = getWeatherConditionFromId(weatherId);
    const score = calculateScoreFromId(weatherId);

    const weatherResult: WeatherData = {
      stationCode: code,
      condition,
      temperature: data.main?.temp ?? 25,
      windSpeed: data.wind?.speed ?? 0,
      visibility: data.visibility ?? 10000,
      score,
      fetchedAt: new Date().toISOString(),
    };

    await saveWeatherCache(weatherResult);
    return weatherResult;
  } catch (error) {
    clearTimeout(timeoutId);
    logger.error(`Failed to fetch weather for ${code}:`, error instanceof Error ? error : new Error(String(error)));
    if (cached) {
      logger.api(`Falling back to expired cache for ${code}`);
      return cached;
    }
    // Return a default safety weather structure if completely failed
    return {
      stationCode: code,
      condition: 'unknown',
      temperature: 25,
      windSpeed: 0,
      visibility: 10000,
      score: 0.5,
      fetchedAt: new Date().toISOString(),
    };
  }
}

export async function getCachedWeather(code: string): Promise<WeatherData | null> {
  return getWeatherCache(code);
}

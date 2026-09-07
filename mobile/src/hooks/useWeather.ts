import { useState, useEffect, useCallback, useRef } from 'react';
import { fetchWeatherForStation, getCachedWeather } from '../services/weatherService';
import type { WeatherData } from '../types';

export function useWeather(stationCodes: string[], stations: Array<{ code: string; lat: number; lon: number }>) {
  const [weatherMap, setWeatherMap] = useState<Record<string, WeatherData>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  const stationsRef = useRef(stations);
  stationsRef.current = stations;

  const fetchAllWeather = useCallback(async () => {
    if (stationCodes.length === 0) return;
    setLoading(true);
    setError(null);
    try {
      const results: Record<string, WeatherData> = {};
      const promises = stationCodes.map(async (code) => {
        // Find matching station details
        const st = stationsRef.current.find((s) => s.code === code);
        if (!st) return;

        // Try getting cached first
        const cached = await getCachedWeather(code);
        if (cached) {
          const diff = Date.now() - new Date(cached.fetchedAt).getTime();
          if (diff <= 10 * 60 * 1000) {
            results[code] = cached;
            return;
          }
        }

        // Fetch fresh if stale or missing
        try {
          const fresh = await fetchWeatherForStation(code, st.lat, st.lon);
          results[code] = fresh;
        } catch (e) {
          if (cached) {
            results[code] = cached;
          }
        }
      });

      await Promise.all(promises);
      setWeatherMap((prev) => ({ ...prev, ...results }));
      setLastUpdated(new Date().toISOString());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to fetch weather');
    } finally {
      setLoading(false);
    }
  }, [stationCodes]);

  useEffect(() => {
    fetchAllWeather();

    const interval = setInterval(() => {
      fetchAllWeather();
    }, 10 * 60 * 1000); // 10 minutes auto-refresh

    return () => clearInterval(interval);
  }, [fetchAllWeather]);

  return { weatherMap, loading, error, lastUpdated, refresh: fetchAllWeather };
}

import { useState, useEffect } from 'react';
import { getNearbyStations } from '../services/stationService';
import type { Station } from '../types';

export function useNearbyStations(location: { latitude: number; longitude: number } | null) {
  const [stations, setStations] = useState<Station[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!location) return;

    let active = true;
    const controller = new AbortController();

    async function fetchStations() {
      setLoading(true);
      setError(null);
      try {
        const list = await getNearbyStations(location!.latitude, location!.longitude, 20);
        if (active) {
          setStations(list);
        }
      } catch (err) {
        if (active) {
          setError(err instanceof Error ? err.message : 'Failed to search nearby railway stations');
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    fetchStations();

    return () => {
      active = false;
      controller.abort();
    };
  }, [location]);

  return { stations, loading, error };
}

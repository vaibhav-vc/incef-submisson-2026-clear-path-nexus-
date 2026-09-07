import { useState, useEffect, useCallback } from 'react';
import * as Location from 'expo-location';
import { logger } from '../utils/logger';

export function useLocation() {
  const [location, setLocation] = useState<{ latitude: number; longitude: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [permissionDenied, setPermissionDenied] = useState(false);

  const requestPermissionAndFetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== 'granted') {
        setPermissionDenied(true);
        setError('Location permission denied');
        setLoading(false);
        return;
      }
      setPermissionDenied(false);
      const currentLoc = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.Balanced,
      });
      setLocation({
        latitude: currentLoc.coords.latitude,
        longitude: currentLoc.coords.longitude,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to obtain location');
      logger.error('Failed to obtain location', e instanceof Error ? e : new Error(String(e)));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    requestPermissionAndFetch();

    let watcher: Location.LocationSubscription | null = null;
    let active = true;

    async function startWatcher() {
      try {
        const { status } = await Location.getForegroundPermissionsAsync();
        if (status !== 'granted') return;

        watcher = await Location.watchPositionAsync(
          {
            accuracy: Location.Accuracy.Balanced,
            timeInterval: 5000,
            distanceInterval: 10,
          },
          (newLoc) => {
            if (active) {
              setLocation({
                latitude: newLoc.coords.latitude,
                longitude: newLoc.coords.longitude,
              });
            }
          }
        );
      } catch (e) {
        logger.error('Error in location watcher', e instanceof Error ? e : new Error(String(e)));
      }
    }

    startWatcher();

    return () => {
      active = false;
      if (watcher) {
        watcher.remove();
      }
    };
  }, [requestPermissionAndFetch]);

  return { location, error, loading, permissionDenied, refresh: requestPermissionAndFetch };
}

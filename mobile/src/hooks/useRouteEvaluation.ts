import { useState, useCallback } from 'react';
import { evaluateRoute } from '../services/routeService';
import { hapticFeedback } from '../utils/haptics';
import type { Station, RouteEvaluation } from '../types';

export function useRouteEvaluation(stations: Station[]) {
  const [evaluation, setEvaluation] = useState<RouteEvaluation | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const evaluate = useCallback(async () => {
    if (stations.length < 2) {
      setError('Select origin and destination stations.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await evaluateRoute(stations);
      setEvaluation(result);

      // Trigger custom status haptics
      if (result.status === 'APPROVED') {
        await hapticFeedback.success();
      } else if (result.status === 'CAUTION') {
        await hapticFeedback.warning();
      } else {
        await hapticFeedback.heavy();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Evaluation failed');
      await hapticFeedback.error();
    } finally {
      setLoading(false);
    }
  }, [stations]);

  const reset = useCallback(() => {
    setEvaluation(null);
    setError(null);
  }, []);

  return { evaluation, loading, error, evaluate, reset };
}

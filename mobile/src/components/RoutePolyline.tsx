import React, { useEffect, useRef } from 'react';
import { Animated } from 'react-native';
import { Polyline } from 'react-native-maps';
import { getStatusColor } from '../theme';
import type { TrackGeometry, RouteStatus } from '../types';

interface RoutePolylineProps {
  trackGeometry: TrackGeometry[];
  status: RouteStatus;
}

export const RoutePolyline: React.FC<RoutePolylineProps> = React.memo(({ trackGeometry, status }) => {
  const drawProgress = useRef(new Animated.Value(0)).current;
  const statusColor = getStatusColor(status);

  useEffect(() => {
    drawProgress.setValue(0);
    Animated.timing(drawProgress, {
      toValue: 1.0,
      duration: 1500,
      useNativeDriver: false,
    }).start();
  }, [trackGeometry, drawProgress]);

  // Merge segments coordinates for progressive path estimation
  const coordinates = trackGeometry.flatMap((track) =>
    track.coordinates.map((coord) => ({
      latitude: coord.lat,
      longitude: coord.lon,
    }))
  );

  if (coordinates.length === 0) return null;

  return (
    <>
      {/* Glow Line */}
      <Polyline
        coordinates={coordinates}
        strokeColor={statusColor}
        strokeWidth={12}
        lineDashPattern={[1]}
        lineCap="round"
        lineJoin="round"
        geodesic
      />
      {/* Primary Line */}
      <Polyline
        coordinates={coordinates}
        strokeColor={statusColor}
        strokeWidth={4}
        lineCap="round"
        lineJoin="round"
        geodesic
      />
    </>
  );
});

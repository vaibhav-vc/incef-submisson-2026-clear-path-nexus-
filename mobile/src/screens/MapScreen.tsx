import React, { useMemo } from 'react';
import { StyleSheet, View, Text, Pressable, Dimensions } from 'react-native';
import MapView, { PROVIDER_DEFAULT } from 'react-native-maps';
import { GlassCard } from '../components/GlassCard';
import { MapLegend } from '../components/MapLegend';
import { LocationDot } from '../components/LocationDot';
import { StationMarker } from '../components/StationMarker';
import { RoutePolyline } from '../components/RoutePolyline';
import { WeatherStrip } from '../components/WeatherStrip';
import { OfflineBanner } from '../components/OfflineBanner';
import { useTheme } from '../hooks/useTheme';
import { darkMapStyle } from '../theme';
import type { Station, RouteEvaluation, WeatherData, TrackGeometry } from '../types';

interface MapScreenProps {
  evaluation: RouteEvaluation | null;
  stations: Station[];
  weatherMap: Record<string, WeatherData>;
  trackGeometry: TrackGeometry[];
  userLocation: { latitude: number; longitude: number } | null;
  isOffline: boolean;
  onLocateUser: () => void;
  onApproveRoute: () => void;
  routeApproved: boolean;
}

const { width } = Dimensions.get('window');

export const MapScreen: React.FC<MapScreenProps> = ({
  evaluation,
  stations,
  weatherMap,
  trackGeometry,
  userLocation,
  isOffline,
  onLocateUser,
  onApproveRoute,
  routeApproved,
}) => {
  const { theme } = useTheme();

  const initialRegion = useMemo(() => {
    if (userLocation) {
      return {
        latitude: userLocation.latitude,
        longitude: userLocation.longitude,
        latitudeDelta: 0.1,
        longitudeDelta: 0.1,
      };
    }
    // Default to Mumbai center region if not available
    return {
      latitude: 19.076,
      longitude: 72.8777,
      latitudeDelta: 0.5,
      longitudeDelta: 0.5,
    };
  }, [userLocation]);

  return (
    <View style={styles.container}>
      <MapView
        provider={PROVIDER_DEFAULT}
        style={styles.map}
        customMapStyle={darkMapStyle}
        initialRegion={initialRegion}
      >
        {userLocation && <LocationDot coordinate={userLocation} />}

        {stations.map((st) => (
          <StationMarker
            key={st.code}
            station={st}
            selected={evaluation?.stations.some((s) => s.code === st.code) ?? false}
            weather={weatherMap[st.code]}
            onPress={() => {}}
          />
        ))}

        {evaluation && trackGeometry.length > 0 && (
          <RoutePolyline trackGeometry={trackGeometry} status={evaluation.status} />
        )}
      </MapView>

      <OfflineBanner visible={isOffline} />

      {/* Floating UI Elements */}
      <View style={styles.overlayTop}>
        <GlassCard size="small" style={styles.locationCard}>
          <Pressable onPress={onLocateUser} style={styles.pillButton}>
            <Text style={styles.buttonText}>📍 My Location</Text>
          </Pressable>
        </GlassCard>
      </View>

      <MapLegend />

      {evaluation && (
        <View style={styles.overlayBottom}>
          <GlassCard size="large" style={styles.statusCard}>
            <View style={styles.statusInfo}>
              <Text style={styles.statusText}>
                Status: {evaluation.status} ({Math.round(evaluation.finalScore * 100)}%)
              </Text>
              <Pressable
                testID="approve-route-on-map"
                onPress={onApproveRoute}
                style={[
                  styles.approveBtn,
                  routeApproved && styles.approvedBtn,
                  evaluation.status !== 'APPROVED' && styles.disabledBtn,
                ]}
                disabled={evaluation.status !== 'APPROVED' || routeApproved}
              >
                <Text style={[styles.approveBtnText, routeApproved && styles.approvedBtnText]}>
                  {routeApproved ? 'APPROVED' : 'APPROVE ROUTE'}
                </Text>
              </Pressable>
            </View>
          </GlassCard>

          <WeatherStrip stations={evaluation.stations} weatherMap={weatherMap} />
        </View>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    position: 'relative',
  },
  map: {
    ...StyleSheet.absoluteFillObject,
  },
  overlayTop: {
    position: 'absolute',
    top: 60,
    right: 16,
    zIndex: 10,
  },
  locationCard: {
    borderRadius: 24,
    padding: 0,
  },
  pillButton: {
    paddingVertical: 10,
    paddingHorizontal: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonText: {
    color: '#F0F4FF',
    fontSize: 12,
    fontWeight: '700',
  },
  overlayBottom: {
    position: 'absolute',
    bottom: 24,
    left: 16,
    right: 16,
    zIndex: 10,
    gap: 12,
  },
  statusCard: {
    paddingVertical: 12,
    paddingHorizontal: 16,
  },
  statusInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  statusText: {
    color: '#F0F4FF',
    fontSize: 13,
    fontWeight: '700',
  },
  approveBtn: {
    backgroundColor: '#00FF88',
    borderRadius: 10,
    paddingVertical: 8,
    paddingHorizontal: 14,
    shadowColor: '#00FF88',
    shadowRadius: 10,
    shadowOpacity: 0.4,
    elevation: 3,
  },
  approvedBtn: {
    backgroundColor: 'rgba(255, 255, 255, 0.06)',
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.12)',
  },
  disabledBtn: {
    backgroundColor: 'rgba(255,255,255,0.05)',
    shadowOpacity: 0,
    elevation: 0,
  },
  approveBtnText: {
    color: '#070B14',
    fontSize: 11,
    fontWeight: '800',
  },
  approvedBtnText: {
    color: '#00FF88',
  },
});

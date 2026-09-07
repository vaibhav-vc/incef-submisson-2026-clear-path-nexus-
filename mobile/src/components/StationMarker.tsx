import React, { useRef } from 'react';
import { StyleSheet, View, Text, Pressable, Animated } from 'react-native';
import { Marker } from 'react-native-maps';
import { useTheme } from '../hooks/useTheme';
import { getWeatherEmoji } from '../theme';
import type { Station, WeatherData } from '../types';

interface StationMarkerProps {
  station: Station;
  selected: boolean;
  weather?: WeatherData;
  onPress: () => void;
}

export const StationMarker: React.FC<StationMarkerProps> = React.memo(({
  station,
  selected,
  weather,
  onPress,
}) => {
  const { theme, isDark } = useTheme();
  const scale = useRef(new Animated.Value(1.0)).current;

  const handlePress = () => {
    Animated.sequence([
      Animated.timing(scale, {
        toValue: 1.3,
        duration: 100,
        useNativeDriver: true,
      }),
      Animated.timing(scale, {
        toValue: 1.0,
        duration: 100,
        useNativeDriver: true,
      }),
    ]).start(() => {
      onPress();
    });
  };

  const weatherEmoji = weather ? getWeatherEmoji(weather.condition) : '';

  return (
    <Marker
      coordinate={{ latitude: station.lat, longitude: station.lon }}
      onPress={handlePress}
    >
      <Animated.View
        style={[
          styles.markerContainer,
          {
            backgroundColor: isDark ? 'rgba(15, 22, 35, 0.8)' : 'rgba(255, 255, 255, 0.9)',
            borderColor: selected ? '#00FF88' : 'rgba(255, 255, 255, 0.15)',
            transform: [{ scale }],
          },
          selected && styles.selectedGlow,
        ]}
      >
        <Text style={styles.stationText}>{station.code}</Text>
        {weatherEmoji ? <Text style={styles.emoji}>{weatherEmoji}</Text> : null}
      </Animated.View>
    </Marker>
  );
});

const styles = StyleSheet.create({
  markerContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 20,
    borderWidth: 1.5,
    gap: 4,
  },
  selectedGlow: {
    shadowColor: '#00FF88',
    shadowRadius: 10,
    shadowOpacity: 0.8,
    shadowOffset: { width: 0, height: 0 },
    elevation: 5,
  },
  stationText: {
    fontSize: 10,
    fontWeight: '700',
    color: '#F0F4FF',
    letterSpacing: 1.5,
    textTransform: 'uppercase',
  },
  emoji: {
    fontSize: 12,
  },
});

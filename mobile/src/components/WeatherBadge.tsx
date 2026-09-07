import React from 'react';
import { StyleSheet, View, Text } from 'react-native';
import { GlassCard } from './GlassCard';
import { SkeletonCard } from './SkeletonCard';
import { getWeatherEmoji } from '../theme';
import type { WeatherData } from '../types';

interface WeatherBadgeProps {
  weather: WeatherData | null;
  loading: boolean;
}

export const WeatherBadge: React.FC<WeatherBadgeProps> = React.memo(({ weather, loading }) => {
  if (loading) {
    return <SkeletonCard width={70} height={32} borderRadius={16} />;
  }

  if (!weather) {
    return (
      <GlassCard size="small" style={styles.badgeCard}>
        <Text style={styles.text}>N/A</Text>
      </GlassCard>
    );
  }

  const emoji = getWeatherEmoji(weather.condition);

  return (
    <GlassCard size="small" style={styles.badgeCard}>
      <View style={styles.container}>
        <Text style={styles.emoji}>{emoji}</Text>
        <Text style={styles.temp}>{Math.round(weather.temperature)}°C</Text>
      </View>
    </GlassCard>
  );
});

const styles = StyleSheet.create({
  badgeCard: {
    borderRadius: 16,
    paddingVertical: 4,
    paddingHorizontal: 8,
    alignItems: 'center',
    justifyContent: 'center',
  },
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  emoji: {
    fontSize: 14,
  },
  temp: {
    fontSize: 12,
    fontWeight: '600',
    color: '#F0F4FF',
  },
  text: {
    fontSize: 11,
    color: '#8892A4',
  },
});

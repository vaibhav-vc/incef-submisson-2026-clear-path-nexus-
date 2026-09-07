import React, { useEffect, useRef } from 'react';
import { StyleSheet, ScrollView, View, Text, Animated } from 'react-native';
import { GlassCard } from './GlassCard';
import { getWeatherEmoji, getScoreColor } from '../theme';
import type { Station, WeatherData } from '../types';

interface WeatherStripProps {
  stations: Station[];
  weatherMap: Record<string, WeatherData>;
}

export const WeatherStrip: React.FC<WeatherStripProps> = React.memo(({ stations, weatherMap }) => {
  const pulseAnim = useRef(new Animated.Value(0.4)).current;

  // Find lowest score
  const lowestScore = Math.min(
    ...stations.map((s) => weatherMap[s.code]?.score ?? 1.0)
  );

  useEffect(() => {
    const anim = Animated.loop(
      Animated.sequence([
        Animated.timing(pulseAnim, {
          toValue: 1.0,
          duration: 1000,
          useNativeDriver: true,
        }),
        Animated.timing(pulseAnim, {
          toValue: 0.4,
          duration: 1000,
          useNativeDriver: true,
        }),
      ])
    );
    anim.start();
    return () => anim.stop();
  }, [pulseAnim]);

  return (
    <View style={styles.container}>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.scroll}>
        {stations.map((station) => {
          const weather = weatherMap[station.code];
          if (!weather) return null;

          const isLowest = weather.score === lowestScore;
          const borderColor = getScoreColor(weather.score);
          const emoji = getWeatherEmoji(weather.condition);

          const cardContent = (
            <GlassCard
              size="small"
              style={[
                styles.pillCard,
                { borderColor },
              ]}
            >
              <Text style={styles.code}>{station.code}</Text>
              <Text style={styles.emoji}>{emoji}</Text>
              <Text style={styles.temp}>{Math.round(weather.temperature)}°C</Text>
            </GlassCard>
          );

          if (isLowest) {
            return (
              <Animated.View key={station.code} style={{ opacity: pulseAnim }}>
                {cardContent}
              </Animated.View>
            );
          }

          return <View key={station.code}>{cardContent}</View>;
        })}
      </ScrollView>
    </View>
  );
});

const styles = StyleSheet.create({
  container: {
    width: '100%',
    marginVertical: 4,
  },
  scroll: {
    gap: 8,
    paddingHorizontal: 4,
  },
  pillCard: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 20,
    borderWidth: 1.5,
    gap: 6,
  },
  code: {
    fontSize: 11,
    fontWeight: '700',
    color: '#8892A4',
    letterSpacing: 1.5,
  },
  emoji: {
    fontSize: 14,
  },
  temp: {
    fontSize: 12,
    fontWeight: '600',
    color: '#F0F4FF',
  },
});

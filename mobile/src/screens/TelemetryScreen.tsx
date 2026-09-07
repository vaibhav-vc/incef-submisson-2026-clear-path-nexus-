import React, { useEffect, useRef } from 'react';
import { StyleSheet, View, Text, ScrollView, RefreshControl, Animated } from 'react-native';
import { BentoGrid } from '../components/BentoGrid';
import { GlassCard } from '../components/GlassCard';
import { ScoreRing } from '../components/ScoreRing';
import { EmptyState } from '../components/EmptyState';
import { WeatherStrip } from '../components/WeatherStrip';
import { formatRelativeTime } from '../utils/time';
import type { RouteEvaluation, WeatherData } from '../types';

interface TelemetryScreenProps {
  evaluation: RouteEvaluation | null;
  weatherMap: Record<string, WeatherData>;
  onRefresh: () => Promise<void>;
  refreshing: boolean;
}

export const TelemetryScreen: React.FC<TelemetryScreenProps> = ({
  evaluation,
  weatherMap,
  onRefresh,
  refreshing,
}) => {
  const weatherBarWidth = useRef(new Animated.Value(0)).current;
  const portBarWidth = useRef(new Animated.Value(0)).current;
  const congestionBarWidth = useRef(new Animated.Value(0)).current;
  const historicalBarWidth = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (evaluation) {
      weatherBarWidth.setValue(0);
      portBarWidth.setValue(0);
      congestionBarWidth.setValue(0);
      historicalBarWidth.setValue(0);

      Animated.stagger(100, [
        Animated.spring(weatherBarWidth, {
          toValue: evaluation.breakdown.weather.score,
          tension: 30,
          friction: 6,
          useNativeDriver: false,
        }),
        Animated.spring(portBarWidth, {
          toValue: evaluation.breakdown.port.score,
          tension: 30,
          friction: 6,
          useNativeDriver: false,
        }),
        Animated.spring(congestionBarWidth, {
          toValue: evaluation.breakdown.congestion.score,
          tension: 30,
          friction: 6,
          useNativeDriver: false,
        }),
        Animated.spring(historicalBarWidth, {
          toValue: evaluation.breakdown.historical.score,
          tension: 30,
          friction: 6,
          useNativeDriver: false,
        }),
      ]).start();
    }
  }, [evaluation, weatherBarWidth, portBarWidth, congestionBarWidth, historicalBarWidth]);

  if (!evaluation) {
    return (
      <View style={styles.container}>
        <EmptyState
          icon="🛤️"
          title="No evaluated route yet"
          subtitle="Navigate to Map or Position to design and analyze track clearances."
        />
      </View>
    );
  }

  return (
    <ScrollView
      style={styles.container}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#00FF88" />
      }
    >
      <BentoGrid>
        <GlassCard size="large" style={styles.ringCard}>
          <ScoreRing score={evaluation.finalScore} status={evaluation.status} animated />
          <Text style={styles.caption}>
            Updated {formatRelativeTime(evaluation.createdAt)}
          </Text>
        </GlassCard>

        {/* Factors Breakdown */}
        <GlassCard size="large">
          <Text style={styles.cardTitle}>Reliability Breakdown</Text>
          <View style={styles.factorsList}>
            {/* Weather factor */}
            <View style={styles.factorRow}>
              <View style={styles.factorHeader}>
                <Text style={styles.factorLabel}>Weather (40%)</Text>
                <Text style={styles.factorVal}>{Math.round(evaluation.breakdown.weather.score * 100)}%</Text>
              </View>
              <View style={styles.barContainer}>
                <Animated.View
                  style={[
                    styles.barFill,
                    {
                      width: weatherBarWidth.interpolate({
                        inputRange: [0, 1],
                        outputRange: ['0%', '100%'],
                      }),
                      backgroundColor: '#3B82F6',
                    },
                  ]}
                />
              </View>
            </View>

            {/* Port factor */}
            <View style={styles.factorRow}>
              <View style={styles.factorHeader}>
                <Text style={styles.factorLabel}>Port Congestion (30%)</Text>
                <Text style={styles.factorVal}>{Math.round(evaluation.breakdown.port.score * 100)}%</Text>
              </View>
              <View style={styles.barContainer}>
                <Animated.View
                  style={[
                    styles.barFill,
                    {
                      width: portBarWidth.interpolate({
                        inputRange: [0, 1],
                        outputRange: ['0%', '100%'],
                      }),
                      backgroundColor: '#FF8C00',
                    },
                  ]}
                />
              </View>
            </View>

            {/* Track Congestion */}
            <View style={styles.factorRow}>
              <View style={styles.factorHeader}>
                <Text style={styles.factorLabel}>Corridor Congestion (15%)</Text>
                <Text style={styles.factorVal}>{Math.round(evaluation.breakdown.congestion.score * 100)}%</Text>
              </View>
              <View style={styles.barContainer}>
                <Animated.View
                  style={[
                    styles.barFill,
                    {
                      width: congestionBarWidth.interpolate({
                        inputRange: [0, 1],
                        outputRange: ['0%', '100%'],
                      }),
                      backgroundColor: '#00FF88',
                    },
                  ]}
                />
              </View>
            </View>

            {/* Historical factor */}
            <View style={styles.factorRow}>
              <View style={styles.factorHeader}>
                <Text style={styles.factorLabel}>Historical Delay Factor (15%)</Text>
                <Text style={styles.factorVal}>{Math.round(evaluation.breakdown.historical.score * 100)}%</Text>
              </View>
              <View style={styles.barContainer}>
                <Animated.View
                  style={[
                    styles.barFill,
                    {
                      width: historicalBarWidth.interpolate({
                        inputRange: [0, 1],
                        outputRange: ['0%', '100%'],
                      }),
                      backgroundColor: '#FF3B5C',
                    },
                  ]}
                />
              </View>
            </View>
          </View>
        </GlassCard>

        {/* Live Weather strip card */}
        <GlassCard size="large">
          <Text style={styles.cardTitle}>Live Station Weather</Text>
          <WeatherStrip stations={evaluation.stations} weatherMap={weatherMap} />
        </GlassCard>
      </BentoGrid>
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#070B14',
  },
  ringCard: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 20,
  },
  caption: {
    color: '#8892A4',
    fontSize: 11,
    fontWeight: '500',
    marginTop: 8,
  },
  cardTitle: {
    fontSize: 15,
    fontWeight: '700',
    color: '#F0F4FF',
    marginBottom: 16,
  },
  factorsList: {
    gap: 16,
  },
  factorRow: {
    gap: 6,
  },
  factorHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  factorLabel: {
    fontSize: 12,
    color: '#8892A4',
    fontWeight: '600',
  },
  factorVal: {
    fontSize: 12,
    color: '#F0F4FF',
    fontWeight: '700',
  },
  barContainer: {
    height: 8,
    backgroundColor: 'rgba(255,255,255,0.08)',
    borderRadius: 4,
    overflow: 'hidden',
  },
  barFill: {
    height: '100%',
    borderRadius: 4,
  },
});

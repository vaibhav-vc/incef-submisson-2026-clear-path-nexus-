import React from 'react';
import { StyleSheet, View, Text, ScrollView, RefreshControl } from 'react-native';
import { BentoGrid } from '../components/BentoGrid';
import { GlassCard } from '../components/GlassCard';
import { EmptyState } from '../components/EmptyState';
import { getStatusColor } from '../theme';
import { formatRelativeTime } from '../utils/time';
import type { RouteEvaluation } from '../types';

interface HistoryScreenProps {
  history: RouteEvaluation[];
  onRefresh: () => Promise<void>;
  refreshing: boolean;
}

export const HistoryScreen: React.FC<HistoryScreenProps> = ({
  history,
  onRefresh,
  refreshing,
}) => {
  return (
    <ScrollView
      style={styles.container}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#00FF88" />
      }
    >
      {history.length === 0 ? (
        <EmptyState
          icon="🛤️"
          title="No routes evaluated yet"
          subtitle="Plot and approve transit corridor routes to verify clearances and save them here."
        />
      ) : (
        <BentoGrid>
          {history.map((item, index) => {
            const fromStation = item.stations[0]?.code || 'N/A';
            const toStation = item.stations[item.stations.length - 1]?.code || 'N/A';
            const intermediate = item.stations.slice(1, -1).map((s) => s.code).join(' → ');
            const statusColor = getStatusColor(item.status);

            return (
              <GlassCard key={item.id || index} size="large" style={styles.historyCard}>
                <View style={styles.header}>
                  <Text style={styles.routeTitle}>
                    {fromStation} → {toStation}
                  </Text>
                  <View style={[styles.statusIndicator, { backgroundColor: statusColor }]}>
                    <Text style={styles.statusText}>{item.status}</Text>
                  </View>
                </View>

                {intermediate ? (
                  <Text style={styles.intermediateText} numberOfLines={1}>
                    Via: {intermediate}
                  </Text>
                ) : null}

                <View style={styles.footer}>
                  <Text style={styles.scoreText}>
                    Reliability Score: {Math.round(item.finalScore * 100)}%
                  </Text>
                  <Text style={styles.timestamp}>
                    {formatRelativeTime(item.createdAt)}
                  </Text>
                </View>
              </GlassCard>
            );
          })}
        </BentoGrid>
      )}
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#070B14',
    paddingVertical: 12,
  },
  historyCard: {
    gap: 10,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  routeTitle: {
    color: '#F0F4FF',
    fontSize: 15,
    fontWeight: '700',
  },
  statusIndicator: {
    paddingVertical: 3,
    paddingHorizontal: 8,
    borderRadius: 6,
  },
  statusText: {
    color: '#070B14',
    fontSize: 9,
    fontWeight: '800',
  },
  intermediateText: {
    color: '#8892A4',
    fontSize: 12,
    fontWeight: '500',
  },
  footer: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: 6,
    borderTopWidth: 1,
    borderTopColor: 'rgba(255, 255, 255, 0.08)',
    paddingTop: 8,
  },
  scoreText: {
    color: '#F0F4FF',
    fontSize: 11,
    fontWeight: '600',
  },
  timestamp: {
    color: '#8892A4',
    fontSize: 10,
    fontWeight: '500',
  },
});

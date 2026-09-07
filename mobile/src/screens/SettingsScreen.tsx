import React from 'react';
import { StyleSheet, View, Text, Pressable, Alert } from 'react-native';
import { BentoGrid } from '../components/BentoGrid';
import { GlassCard } from '../components/GlassCard';
import { useTheme } from '../hooks/useTheme';
import { hapticFeedback } from '../utils/haptics';

interface SettingsScreenProps {
  onClearHistory: () => Promise<void>;
  onApproveRoute: () => void;
  hasActiveRoute: boolean;
}

export const SettingsScreen: React.FC<SettingsScreenProps> = ({
  onClearHistory,
  onApproveRoute,
  hasActiveRoute,
}) => {
  const { toggleTheme, isDark } = useTheme();

  const handleClearHistoryPress = () => {
    Alert.alert(
      'Clear History',
      'Are you sure you want to clear all route history? This action is permanent.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Clear All',
          style: 'destructive',
          onPress: async () => {
            await hapticFeedback.heavy();
            await onClearHistory();
          },
        },
      ]
    );
  };

  return (
    <View style={styles.container}>
      <BentoGrid>
        <GlassCard size="large">
          <Text style={styles.sectionTitle}>App Preferences</Text>
          <Pressable onPress={toggleTheme} style={styles.settingRow}>
            <Text style={styles.settingLabel}>App Theme</Text>
            <View style={styles.toggleBadge}>
              <Text style={styles.badgeText}>{isDark ? 'DARK MODE' : 'LIGHT MODE'}</Text>
            </View>
          </Pressable>
        </GlassCard>

        <GlassCard size="large">
          <Text style={styles.sectionTitle}>Danger Zone</Text>
          <Pressable
            testID="clear-history-button"
            onPress={handleClearHistoryPress}
            style={styles.destructiveBtn}
          >
            <Text style={styles.destructiveText}>Clear Route History</Text>
          </Pressable>
        </GlassCard>

        {hasActiveRoute ? (
          <GlassCard size="large">
            <Text style={styles.sectionTitle}>Secondary Actions</Text>
            <Pressable
              testID="approve-route-secondary-settings"
              onPress={onApproveRoute}
              style={styles.secondaryBtn}
            >
              <Text style={styles.secondaryBtnText}>Approve Route (Dispatch)</Text>
            </Pressable>
          </GlassCard>
        ) : null}

        <View style={styles.footer}>
          <Text style={styles.versionText}>ClearPath Nexus v1.2</Text>
          <Text style={styles.creditText}>Data-driven intelligence platform</Text>
        </View>
      </BentoGrid>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#070B14',
    paddingVertical: 12,
  },
  sectionTitle: {
    fontSize: 14,
    fontWeight: '700',
    color: '#F0F4FF',
    marginBottom: 16,
  },
  settingRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 8,
  },
  settingLabel: {
    fontSize: 13,
    color: '#8892A4',
    fontWeight: '600',
  },
  toggleBadge: {
    backgroundColor: 'rgba(255,255,255,0.06)',
    borderColor: 'rgba(255,255,255,0.12)',
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 6,
    paddingHorizontal: 12,
  },
  badgeText: {
    color: '#00FF88',
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
  destructiveBtn: {
    backgroundColor: 'rgba(255,59,92,0.15)',
    borderWidth: 1,
    borderColor: 'rgba(255,59,92,0.30)',
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
  },
  destructiveText: {
    color: '#FF3B5C',
    fontSize: 13,
    fontWeight: '700',
  },
  secondaryBtn: {
    backgroundColor: 'rgba(255,255,255,0.06)',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.12)',
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
  },
  secondaryBtnText: {
    color: '#F0F4FF',
    fontSize: 13,
    fontWeight: '700',
  },
  footer: {
    width: '100%',
    alignItems: 'center',
    marginTop: 24,
    gap: 4,
  },
  versionText: {
    color: '#8892A4',
    fontSize: 11,
    fontWeight: '600',
  },
  creditText: {
    color: '#3D4657',
    fontSize: 10,
    fontWeight: '500',
  },
});

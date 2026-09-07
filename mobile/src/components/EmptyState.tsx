import React from 'react';
import { StyleSheet, View, Text, Pressable } from 'react-native';
import { GlassCard } from './GlassCard';

interface EmptyStateProps {
  icon: string;
  title: string;
  subtitle: string;
  onAction?: () => void;
  actionLabel?: string;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  icon,
  title,
  subtitle,
  onAction,
  actionLabel,
}) => {
  return (
    <GlassCard size="large" style={styles.card}>
      <View style={styles.container}>
        <Text style={styles.icon}>{icon}</Text>
        <Text style={styles.title}>{title}</Text>
        <Text style={styles.subtitle}>{subtitle}</Text>
        {onAction && actionLabel && (
          <Pressable style={styles.button} onPress={onAction}>
            <Text style={styles.buttonText}>{actionLabel}</Text>
          </Pressable>
        )}
      </View>
    </GlassCard>
  );
};

const styles = StyleSheet.create({
  card: {
    paddingVertical: 40,
    alignItems: 'center',
    justifyContent: 'center',
  },
  container: {
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
  },
  icon: {
    fontSize: 40,
    marginBottom: 8,
  },
  title: {
    fontSize: 16,
    fontWeight: '700',
    color: '#F0F4FF',
    textAlign: 'center',
  },
  subtitle: {
    fontSize: 13,
    fontWeight: '500',
    color: '#8892A4',
    textAlign: 'center',
  },
  button: {
    backgroundColor: '#00FF88',
    borderRadius: 10,
    paddingVertical: 8,
    paddingHorizontal: 16,
    marginTop: 12,
  },
  buttonText: {
    color: '#070B14',
    fontWeight: '700',
    fontSize: 13,
  },
});

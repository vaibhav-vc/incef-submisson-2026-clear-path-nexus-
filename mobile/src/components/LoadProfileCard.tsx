import React from 'react';
import { StyleSheet, View, Text, Pressable, Alert } from 'react-native';
import { GlassCard } from './GlassCard';
import type { LoadProfile } from '../types';

interface LoadProfileCardProps {
  profile: LoadProfile;
  onDelete: () => void;
  onSelect: () => void;
}

export const LoadProfileCard: React.FC<LoadProfileCardProps> = React.memo(({
  profile,
  onDelete,
  onSelect,
}) => {
  const handleDeletePress = () => {
    Alert.alert(
      'Delete Profile',
      `Are you sure you want to delete profile "${profile.name}"?`,
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Delete', style: 'destructive', onPress: onDelete },
      ]
    );
  };

  return (
    <GlassCard size="half" style={styles.card}>
      <Pressable onPress={onSelect} style={styles.pressable}>
        <View style={styles.header}>
          <Text style={styles.name} numberOfLines={1}>
            {profile.name}
          </Text>
        </View>
        <View style={styles.details}>
          <Text style={styles.detailText}>H: {profile.cargoHeight}m</Text>
          <Text style={styles.detailText}>W: {profile.cargoWidth}m</Text>
          <Text style={styles.detailText}>Wt: {profile.cargoWeight}t</Text>
        </View>
        <Pressable
          testID={`delete-profile-${profile.id}`}
          style={styles.deleteButton}
          onPress={handleDeletePress}
        >
          <Text style={styles.deleteText}>Delete</Text>
        </Pressable>
      </Pressable>
    </GlassCard>
  );
});

const styles = StyleSheet.create({
  card: {
    height: 120,
    justifyContent: 'space-between',
  },
  pressable: {
    flex: 1,
    justifyContent: 'space-between',
  },
  header: {
    marginBottom: 4,
  },
  name: {
    color: '#F0F4FF',
    fontSize: 14,
    fontWeight: '700',
  },
  details: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginVertical: 4,
  },
  detailText: {
    color: '#8892A4',
    fontSize: 11,
    fontWeight: '600',
  },
  deleteButton: {
    backgroundColor: 'rgba(255,59,92,0.15)',
    borderWidth: 1,
    borderColor: 'rgba(255,59,92,0.30)',
    borderRadius: 8,
    paddingVertical: 4,
    alignItems: 'center',
    marginTop: 6,
  },
  deleteText: {
    color: '#FF3B5C',
    fontSize: 10,
    fontWeight: '700',
  },
});

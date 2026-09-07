import React, { useState } from 'react';
import { StyleSheet, View, Text, TextInput, FlatList, Pressable, Keyboard, Alert } from 'react-native';
import { GlassCard } from './GlassCard';
import { searchStations } from '../services/stationService';
import type { Station } from '../types';

interface WaypointInputProps {
  waypoint: Station | null;
  index: number;
  onSelect: (s: Station) => void;
  onRemove: () => void;
  onDrag: () => void;
}

export const WaypointInput: React.FC<WaypointInputProps> = React.memo(({
  waypoint,
  index,
  onSelect,
  onRemove,
  onDrag,
}) => {
  const [query, setQuery] = useState(waypoint?.name || '');
  const [results, setResults] = useState<Station[]>([]);
  const [loading, setLoading] = useState(false);
  const searchTimeoutRef = React.useRef<NodeJS.Timeout | null>(null);

  const performSearch = async (text: string) => {
    if (text.trim().length < 2) {
      setResults([]);
      return;
    }
    setLoading(true);
    try {
      const data = await searchStations(text);
      setResults(data);
    } catch (_) {}
    setLoading(false);
  };

  const handleTextChange = (text: string) => {
    setQuery(text);
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }
    searchTimeoutRef.current = setTimeout(() => {
      performSearch(text);
    }, 300);
  };

  const selectStation = (station: Station) => {
    onSelect(station);
    setQuery(station.name);
    setResults([]);
    Keyboard.dismiss();
  };

  const confirmRemove = () => {
    Alert.alert(
      'Remove Stop',
      'Remove this stop from route?',
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Remove', style: 'destructive', onPress: onRemove },
      ]
    );
  };

  return (
    <GlassCard size="large" style={styles.card}>
      <View style={styles.header}>
        <Pressable onPress={onDrag} style={styles.dragHandle}>
          <Text style={styles.dragText}>☰</Text>
        </Pressable>
        <Text style={styles.label}>Stop #{index + 1}</Text>
        <Pressable onPress={confirmRemove} style={styles.removeButton}>
          <Text style={styles.removeText}>✕</Text>
        </Pressable>
      </View>
      <TextInput
        style={styles.input}
        value={query}
        placeholder="Search railway station..."
        placeholderTextColor="#3D4657"
        onChangeText={handleTextChange}
        returnKeyType="search"
      />
      {results.length > 0 && (
        <View style={styles.resultsContainer}>
          <FlatList
            data={results}
            keyExtractor={(item) => item.code}
            renderItem={({ item }) => (
              <Pressable onPress={() => selectStation(item)} style={styles.resultRow}>
                <Text style={styles.resultName}>{item.name}</Text>
                <Text style={styles.resultCode}>{item.code}</Text>
              </Pressable>
            )}
            style={styles.resultsList}
            keyboardShouldPersistTaps="handled"
          />
        </View>
      )}
    </GlassCard>
  );
});

const styles = StyleSheet.create({
  card: {
    marginVertical: 4,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  dragHandle: {
    padding: 4,
  },
  dragText: {
    color: '#8892A4',
    fontSize: 16,
  },
  label: {
    color: '#F0F4FF',
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 1.5,
    textTransform: 'uppercase',
  },
  removeButton: {
    padding: 4,
  },
  removeText: {
    color: '#FF3B5C',
    fontSize: 14,
    fontWeight: '700',
  },
  input: {
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderColor: 'rgba(255,255,255,0.10)',
    borderWidth: 1,
    borderRadius: 12,
    color: '#F0F4FF',
    padding: 12,
    fontSize: 13,
  },
  resultsContainer: {
    backgroundColor: '#0F1623',
    borderColor: 'rgba(255, 255, 255, 0.10)',
    borderWidth: 1,
    borderRadius: 12,
    marginTop: 6,
    maxHeight: 120,
    overflow: 'hidden',
  },
  resultsList: {
    padding: 4,
  },
  resultRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    padding: 10,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255,255,255,0.05)',
  },
  resultName: {
    color: '#F0F4FF',
    fontSize: 12,
    fontWeight: '600',
  },
  resultCode: {
    color: '#8892A4',
    fontSize: 10,
    fontWeight: '700',
  },
});

import React, { useState } from 'react';
import { StyleSheet, View, Text, Pressable, ScrollView, RefreshControl, TextInput, Modal, KeyboardAvoidingView, Platform, Keyboard } from 'react-native';
import { BentoGrid } from '../components/BentoGrid';
import { GlassCard } from '../components/GlassCard';
import { LoadProfileCard } from '../components/LoadProfileCard';
import { EmptyState } from '../components/EmptyState';
import { hapticFeedback } from '../utils/haptics';
import type { LoadProfile } from '../types';

interface ProfilesScreenProps {
  profiles: LoadProfile[];
  onCreateProfile: (profile: { name: string; cargoHeight: number; cargoWidth: number; cargoWeight: number }) => Promise<void>;
  onDeleteProfile: (id: number) => Promise<void>;
  onSelectProfile: (profile: LoadProfile) => void;
  onRefresh: () => Promise<void>;
  refreshing: boolean;
}

export const ProfilesScreen: React.FC<ProfilesScreenProps> = ({
  profiles,
  onCreateProfile,
  onDeleteProfile,
  onSelectProfile,
  onRefresh,
  refreshing,
}) => {
  const [modalVisible, setModalVisible] = useState(false);
  const [name, setName] = useState('');
  const [height, setHeight] = useState('');
  const [width, setWidth] = useState('');
  const [weight, setWeight] = useState('');

  const inputHeightRef = React.useRef<TextInput>(null);
  const inputWidthRef = React.useRef<TextInput>(null);
  const inputWeightRef = React.useRef<TextInput>(null);

  const handleSubmit = async () => {
    if (!name.trim() || !height || !width || !weight) {
      return;
    }
    const h = parseFloat(height);
    const w = parseFloat(width);
    const wt = parseFloat(weight);

    if (isNaN(h) || isNaN(w) || isNaN(wt)) return;

    await hapticFeedback.light();
    await onCreateProfile({
      name: name.trim(),
      cargoHeight: h,
      cargoWidth: w,
      cargoWeight: wt,
    });

    // Reset fields
    setName('');
    setHeight('');
    setWidth('');
    setWeight('');
    setModalVisible(false);
  };

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Pressable
          testID="create-profile-button"
          onPress={() => setModalVisible(true)}
          style={styles.createBtn}
        >
          <Text style={styles.createBtnText}>Create Profile</Text>
        </Pressable>
      </View>

      <ScrollView
        style={styles.scroll}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#00FF88" />
        }
      >
        {profiles.length === 0 ? (
          <EmptyState
            icon="📦"
            title="No load profiles yet"
            subtitle="Define physical dimensions of rolling stock cargo to check clearances."
            onAction={() => setModalVisible(true)}
            actionLabel="Create Profile"
          />
        ) : (
          <BentoGrid>
            {profiles.map((p) => (
              <LoadProfileCard
                key={p.id}
                profile={p}
                onSelect={() => onSelectProfile(p)}
                onDelete={() => onDeleteProfile(p.id!)}
              />
            ))}
          </BentoGrid>
        )}
      </ScrollView>

      {/* Create Modal */}
      <Modal visible={modalVisible} transparent animationType="slide">
        <KeyboardAvoidingView
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
          style={styles.modalBg}
        >
          <GlassCard size="large" style={styles.modalContent}>
            <Text style={styles.modalTitle}>New Load Profile</Text>
            
            <View style={styles.form}>
              <Text style={styles.label}>Profile Name</Text>
              <TextInput
                style={styles.input}
                value={name}
                onChangeText={setName}
                placeholder="e.g. Standard Container"
                placeholderTextColor="#3D4657"
                returnKeyType="next"
                onSubmitEditing={() => inputHeightRef.current?.focus()}
              />

              <Text style={styles.label}>Cargo Height (meters)</Text>
              <TextInput
                ref={inputHeightRef}
                style={styles.input}
                value={height}
                onChangeText={setHeight}
                placeholder="e.g. 4.25"
                placeholderTextColor="#3D4657"
                keyboardType="numeric"
                returnKeyType="next"
                onSubmitEditing={() => inputWidthRef.current?.focus()}
              />

              <Text style={styles.label}>Cargo Width (meters)</Text>
              <TextInput
                ref={inputWidthRef}
                style={styles.input}
                value={width}
                onChangeText={setWidth}
                placeholder="e.g. 3.20"
                placeholderTextColor="#3D4657"
                keyboardType="numeric"
                returnKeyType="next"
                onSubmitEditing={() => inputWeightRef.current?.focus()}
              />

              <Text style={styles.label}>Cargo Weight (metric tons)</Text>
              <TextInput
                ref={inputWeightRef}
                style={styles.input}
                value={weight}
                onChangeText={setWeight}
                placeholder="e.g. 65"
                placeholderTextColor="#3D4657"
                keyboardType="numeric"
                returnKeyType="done"
                onSubmitEditing={handleSubmit}
              />

              <View style={styles.modalActions}>
                <Pressable onPress={() => setModalVisible(false)} style={styles.cancelBtn}>
                  <Text style={styles.cancelBtnText}>Cancel</Text>
                </Pressable>
                <Pressable onPress={handleSubmit} style={styles.submitBtn}>
                  <Text style={styles.submitBtnText}>Save Profile</Text>
                </Pressable>
              </View>
            </View>
          </GlassCard>
        </KeyboardAvoidingView>
      </Modal>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#070B14',
  },
  header: {
    padding: 16,
    alignItems: 'flex-end',
  },
  createBtn: {
    backgroundColor: '#00FF88',
    borderRadius: 14,
    paddingVertical: 10,
    paddingHorizontal: 20,
    shadowColor: '#00FF88',
    shadowRadius: 12,
    shadowOpacity: 0.4,
    elevation: 3,
  },
  createBtnText: {
    color: '#070B14',
    fontWeight: '700',
    fontSize: 14,
  },
  scroll: {
    flex: 1,
  },
  modalBg: {
    flex: 1,
    backgroundColor: 'rgba(7, 11, 20, 0.85)',
    justifyContent: 'center',
    padding: 24,
  },
  modalContent: {
    padding: 20,
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: '#F0F4FF',
    marginBottom: 16,
    textAlign: 'center',
  },
  form: {
    gap: 12,
  },
  label: {
    fontSize: 10,
    fontWeight: '700',
    color: '#8892A4',
    letterSpacing: 1.5,
    textTransform: 'uppercase',
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
  modalActions: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 16,
  },
  cancelBtn: {
    backgroundColor: 'rgba(255,255,255,0.06)',
    borderColor: 'rgba(255,255,255,0.12)',
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 12,
    paddingHorizontal: 20,
    width: '45%',
    alignItems: 'center',
  },
  cancelBtnText: {
    color: '#F0F4FF',
    fontWeight: '600',
  },
  submitBtn: {
    backgroundColor: '#00FF88',
    borderRadius: 12,
    paddingVertical: 12,
    paddingHorizontal: 20,
    width: '45%',
    alignItems: 'center',
  },
  submitBtnText: {
    color: '#070B14',
    fontWeight: '700',
  },
});

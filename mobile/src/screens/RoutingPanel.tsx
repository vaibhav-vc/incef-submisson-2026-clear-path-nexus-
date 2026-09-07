import React, { useState } from 'react';
import { StyleSheet, View, Text, Pressable, ScrollView, TextInput, ActivityIndicator, Alert, Modal } from 'react-native';
import { GlassCard } from '../components/GlassCard';
import { WaypointInput } from '../components/WaypointInput';
import { ScoreRing } from '../components/ScoreRing';
import type { Station, RouteEvaluation, LoadProfile } from '../types';

interface RoutingPanelProps {
  fromStation: Station | null;
  waypoints: Array<Station | null>;
  loadProfiles: LoadProfile[];
  selectedProfile: LoadProfile | null;
  onSetFrom: (s: Station) => void;
  onAddWaypoint: () => void;
  onUpdateWaypoint: (index: number, s: Station) => void;
  onRemoveWaypoint: (index: number) => void;
  onSelectProfile: (profile: LoadProfile) => void;
  onEvaluate: () => Promise<void>;
  onApproveRoute: () => void;
  loading: boolean;
  evaluation: RouteEvaluation | null;
  routeApproved: boolean;
}

export const RoutingPanel: React.FC<RoutingPanelProps> = ({
  fromStation,
  waypoints,
  loadProfiles,
  selectedProfile,
  onSetFrom,
  onAddWaypoint,
  onUpdateWaypoint,
  onRemoveWaypoint,
  onSelectProfile,
  onEvaluate,
  onApproveRoute,
  loading,
  evaluation,
  routeApproved,
}) => {
  const [profileModalVisible, setProfileModalVisible] = useState(false);

  return (
    <View style={styles.container}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <Text style={styles.headerLabel}>FROM STATION</Text>
        <WaypointInput
          waypoint={fromStation}
          index={-1}
          onSelect={onSetFrom}
          onRemove={() => {}}
          onDrag={() => {}}
        />

        <View style={styles.sectionHeader}>
          <Text style={styles.headerLabel}>WAYPOINTS</Text>
          {waypoints.length < 5 && (
            <Pressable onPress={onAddWaypoint} style={styles.addBtn}>
              <Text style={styles.addBtnText}>Add Stop +</Text>
            </Pressable>
          )}
        </View>

        {waypoints.map((wp, index) => (
          <WaypointInput
            key={index}
            waypoint={wp}
            index={index}
            onSelect={(s) => onUpdateWaypoint(index, s)}
            onRemove={() => onRemoveWaypoint(index)}
            onDrag={() => {}}
          />
        ))}

        <Text style={styles.headerLabel}>CARGO PROFILE</Text>
        <GlassCard size="large" style={styles.profileCard}>
          <Pressable onPress={() => setProfileModalVisible(true)} style={styles.profileSelector}>
            <Text style={styles.profileText}>
              {selectedProfile ? `${selectedProfile.name} (H: ${selectedProfile.cargoHeight}m)` : 'Select Cargo Profile'}
            </Text>
            <Text style={styles.selectorArrow}>▼</Text>
          </Pressable>
        </GlassCard>

        <Pressable
          testID="evaluate-route-button"
          onPress={onEvaluate}
          style={[styles.evalBtn, loading && styles.disabledBtn]}
          disabled={loading}
        >
          {loading ? (
            <ActivityIndicator color="#070B14" />
          ) : (
            <Text style={styles.evalBtnText}>EVALUATE ROUTE</Text>
          )}
        </Pressable>

        {evaluation && (
          <View style={styles.approvalSection}>
            <ScoreRing score={evaluation.finalScore} status={evaluation.status} animated />
            <Pressable
              testID="approve-route-panel-button"
              onPress={onApproveRoute}
              style={[
                styles.approveBtn,
                routeApproved && styles.approvedBtn,
                evaluation.status !== 'APPROVED' && styles.disabledBtn,
              ]}
              disabled={evaluation.status !== 'APPROVED' || routeApproved}
            >
              <Text style={[styles.approveBtnText, routeApproved && styles.approvedBtnText]}>
                {routeApproved ? 'Approved BADGE' : 'APPROVE ROUTE'}
              </Text>
            </Pressable>
          </View>
        )}
      </ScrollView>

      {/* Profile Selector Modal */}
      <Modal visible={profileModalVisible} transparent animationType="slide">
        <View style={styles.modalBg}>
          <GlassCard size="large" style={styles.modalContent}>
            <Text style={styles.modalTitle}>Select Profile</Text>
            <ScrollView style={styles.modalScroll}>
              {loadProfiles.map((p) => (
                <Pressable
                  key={p.id}
                  onPress={() => {
                    onSelectProfile(p);
                    setProfileModalVisible(false);
                  }}
                  style={styles.modalRow}
                >
                  <Text style={styles.modalRowText}>{p.name}</Text>
                  <Text style={styles.modalRowSub}>H: {p.cargoHeight}m, W: {p.cargoWidth}m</Text>
                </Pressable>
              ))}
            </ScrollView>
            <Pressable onPress={() => setProfileModalVisible(false)} style={styles.closeBtn}>
              <Text style={styles.closeBtnText}>Cancel</Text>
            </Pressable>
          </GlassCard>
        </View>
      </Modal>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#070B14',
  },
  scroll: {
    padding: 16,
    gap: 12,
  },
  headerLabel: {
    fontSize: 10,
    fontWeight: '700',
    color: '#8892A4',
    letterSpacing: 1.5,
    textTransform: 'uppercase',
    marginTop: 8,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  addBtn: {
    backgroundColor: 'rgba(255,255,255,0.06)',
    borderColor: 'rgba(255,255,255,0.12)',
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 4,
    paddingHorizontal: 10,
  },
  addBtnText: {
    color: '#F0F4FF',
    fontSize: 11,
    fontWeight: '600',
  },
  profileCard: {
    padding: 0,
  },
  profileSelector: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: 14,
  },
  profileText: {
    color: '#F0F4FF',
    fontSize: 14,
    fontWeight: '600',
  },
  selectorArrow: {
    color: '#8892A4',
    fontSize: 12,
  },
  evalBtn: {
    backgroundColor: '#00FF88',
    borderRadius: 14,
    paddingVertical: 14,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 12,
    shadowColor: '#00FF88',
    shadowRadius: 12,
    shadowOpacity: 0.4,
    elevation: 3,
  },
  disabledBtn: {
    opacity: 0.4,
  },
  evalBtnText: {
    color: '#070B14',
    fontWeight: '700',
    fontSize: 15,
  },
  approvalSection: {
    marginTop: 20,
    alignItems: 'center',
    gap: 12,
  },
  approveBtn: {
    backgroundColor: '#00FF88',
    borderRadius: 14,
    paddingVertical: 14,
    width: '100%',
    alignItems: 'center',
  },
  approvedBtn: {
    backgroundColor: 'rgba(255, 255, 255, 0.06)',
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.12)',
  },
  approveBtnText: {
    color: '#070B14',
    fontWeight: '700',
    fontSize: 15,
  },
  approvedBtnText: {
    color: '#00FF88',
  },
  modalBg: {
    flex: 1,
    backgroundColor: 'rgba(7, 11, 20, 0.85)',
    justifyContent: 'center',
    padding: 24,
  },
  modalContent: {
    maxHeight: '70%',
    padding: 20,
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: '#F0F4FF',
    marginBottom: 16,
    textAlign: 'center',
  },
  modalScroll: {
    maxHeight: 300,
  },
  modalRow: {
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255, 255, 255, 0.08)',
  },
  modalRowText: {
    color: '#F0F4FF',
    fontSize: 14,
    fontWeight: '600',
  },
  modalRowSub: {
    color: '#8892A4',
    fontSize: 11,
    marginTop: 2,
  },
  closeBtn: {
    backgroundColor: 'rgba(255,255,255,0.06)',
    borderRadius: 12,
    paddingVertical: 12,
    alignItems: 'center',
    marginTop: 16,
  },
  closeBtnText: {
    color: '#F0F4FF',
    fontWeight: '600',
  },
});

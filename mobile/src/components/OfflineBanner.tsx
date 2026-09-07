import React, { useEffect, useRef } from 'react';
import { StyleSheet, View, Text, Animated } from 'react-native';
import { BlurView } from 'expo-blur';

interface OfflineBannerProps {
  visible: boolean;
  message?: string;
  isAmber?: boolean;
}

export const OfflineBanner: React.FC<OfflineBannerProps> = ({
  visible,
  message = 'Offline — showing cached data',
  isAmber = true,
}) => {
  const slideAnim = useRef(new Animated.Value(-100)).current;

  useEffect(() => {
    Animated.timing(slideAnim, {
      toValue: visible ? 0 : -100,
      duration: 300,
      useNativeDriver: true,
    }).start();
  }, [visible, slideAnim]);

  return (
    <Animated.View
      style={[
        styles.container,
        {
          transform: [{ translateY: slideAnim }],
        },
      ]}
    >
      <BlurView intensity={80} tint="dark" style={styles.blur}>
        <View style={styles.highlightLine} />
        <View style={styles.inner}>
          <Text style={styles.icon}>{isAmber ? '⚠️' : '📍'}</Text>
          <Text style={styles.text}>{message}</Text>
        </View>
      </BlurView>
    </Animated.View>
  );
};

const styles = StyleSheet.create({
  container: {
    position: 'absolute',
    top: 50,
    left: 20,
    right: 20,
    zIndex: 9999,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: 'rgba(255, 140, 0, 0.3)',
    overflow: 'hidden',
  },
  blur: {
    padding: 14,
    backgroundColor: 'rgba(15, 22, 35, 0.75)',
  },
  inner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    justifyContent: 'center',
  },
  highlightLine: {
    position: 'absolute',
    top: 0,
    left: 20,
    right: 20,
    height: 1,
    backgroundColor: 'rgba(255,140,0,0.4)',
  },
  icon: {
    fontSize: 14,
  },
  text: {
    color: '#FF8C00',
    fontSize: 12,
    fontWeight: '700',
  },
});

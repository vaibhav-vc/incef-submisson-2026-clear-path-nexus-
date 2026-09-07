import React, { useEffect, useRef } from 'react';
import { StyleSheet, View, Animated, Platform } from 'react-native';
import { BlurView } from 'expo-blur';
import { useTheme } from '../hooks/useTheme';
import type { BentoSize } from '../types';

interface GlassCardProps {
  children: React.ReactNode;
  style?: any;
  glowColor?: string;
  size?: BentoSize;
  testID?: string;
}

export const GlassCard: React.FC<GlassCardProps> = React.memo(({
  children,
  style,
  glowColor,
  size = 'large',
  testID,
}) => {
  const { theme, isDark } = useTheme();
  const scale = useRef(new Animated.Value(0.95)).current;
  const opacity = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.timing(scale, {
        toValue: 1.0,
        duration: 250,
        useNativeDriver: true,
      }),
      Animated.timing(opacity, {
        toValue: 1.0,
        duration: 250,
        useNativeDriver: true,
      }),
    ]).start();
  }, [scale, opacity]);

  const widthStyle =
    size === 'small'
      ? styles.small
      : size === 'medium'
      ? styles.medium
      : size === 'half'
      ? styles.half
      : styles.large;

  // Glow shadow logic (iOS only)
  const isIOS = Platform.OS === 'ios';
  const glowStyle = isIOS && glowColor
    ? {
        shadowColor: glowColor,
        shadowRadius: 20,
        shadowOpacity: 0.3,
        shadowOffset: { width: 0, height: 0 },
      }
    : {};

  return (
    <Animated.View
      testID={testID}
      style={[
        styles.cardContainer,
        widthStyle,
        {
          borderColor: theme.glassBorder,
          backgroundColor: isDark ? 'rgba(15, 22, 35, 0.6)' : 'rgba(255, 255, 255, 0.85)',
          opacity,
          transform: [{ scale }],
        },
        glowStyle,
        style,
      ]}
    >
      <BlurView intensity={80} tint={isDark ? 'dark' : 'light'} style={StyleSheet.absoluteFill}>
        <View style={[styles.highlightLine, { backgroundColor: isDark ? 'rgba(255, 255, 255, 0.15)' : 'rgba(0, 0, 0, 0.05)' }]} />
        <View style={styles.content}>{children}</View>
      </BlurView>
    </Animated.View>
  );
});

const styles = StyleSheet.create({
  cardContainer: {
    borderRadius: 20,
    borderWidth: 1,
    overflow: 'hidden',
  },
  content: {
    padding: 16,
    flex: 1,
  },
  highlightLine: {
    position: 'absolute',
    top: 0,
    left: 20,
    right: 20,
    height: 1,
  },
  small: {
    width: '31%',
  },
  medium: {
    width: '65%',
  },
  half: {
    width: '48%',
  },
  large: {
    width: '100%',
  },
});

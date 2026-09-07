import React, { useEffect, useRef } from 'react';
import { StyleSheet, Animated } from 'react-native';

interface SkeletonCardProps {
  width?: any;
  height?: any;
  borderRadius?: number;
  style?: any;
}

export const SkeletonCard: React.FC<SkeletonCardProps> = React.memo(({
  width = '100%',
  height = 60,
  borderRadius = 12,
  style,
}) => {
  const opacity = useRef(new Animated.Value(0.3)).current;

  useEffect(() => {
    const animation = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, {
          toValue: 1.0,
          duration: 800,
          useNativeDriver: true,
        }),
        Animated.timing(opacity, {
          toValue: 0.3,
          duration: 800,
          useNativeDriver: true,
        }),
      ])
    );
    animation.start();

    return () => animation.stop();
  }, [opacity]);

  return (
    <Animated.View
      style={[
        styles.skeleton,
        {
          width,
          height,
          borderRadius,
          opacity,
        },
        style,
      ]}
    />
  );
});

const styles = StyleSheet.create({
  skeleton: {
    backgroundColor: '#151E2E',
  },
});

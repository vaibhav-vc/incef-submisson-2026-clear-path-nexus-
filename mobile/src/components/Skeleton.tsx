import { useEffect, useRef } from 'react';
import { Animated, DimensionValue, StyleSheet, View } from 'react-native';
import { palette } from '../theme';

export function SkeletonBar({ width = '100%', height = 14 }: { width?: DimensionValue; height?: number }) {
  const opacity = useRef(new Animated.Value(0.3)).current;

  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 1, duration: 650, useNativeDriver: true }),
        Animated.timing(opacity, { toValue: 0.3, duration: 650, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => {
      loop.stop();
    };
  }, [opacity]);

  return <Animated.View style={[styles.bar, { width, height }, { opacity }]} />;
}

export function LoadProfileSkeletons() {
  return (
    <View style={styles.stack}>
      {[0, 1, 2].map((item) => (
        <View key={item} style={styles.card}>
          <SkeletonBar width="55%" height={16} />
          <SkeletonBar width="78%" height={12} />
          <SkeletonBar width="38%" height={12} />
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  stack: { gap: 12 },
  card: {
    borderRadius: 20,
    borderWidth: 1,
    borderColor: palette.glassBorder,
    backgroundColor: palette.surface,
    padding: 14,
    gap: 10,
  },
  bar: { borderRadius: 999, backgroundColor: palette.raised },
});

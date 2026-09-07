import React, { useEffect, useRef } from 'react';
import { StyleSheet, View, Animated } from 'react-native';
import { Marker } from 'react-native-maps';

interface LocationDotProps {
  coordinate: { latitude: number; longitude: number };
}

export const LocationDot: React.FC<LocationDotProps> = ({ coordinate }) => {
  const scale = useRef(new Animated.Value(1.0)).current;
  const opacity = useRef(new Animated.Value(1.0)).current;

  useEffect(() => {
    const animation = Animated.loop(
      Animated.parallel([
        Animated.timing(scale, {
          toValue: 2.5,
          duration: 2000,
          useNativeDriver: true,
        }),
        Animated.timing(opacity, {
          toValue: 0.0,
          duration: 2000,
          useNativeDriver: true,
        }),
      ])
    );
    animation.start();
    return () => animation.stop();
  }, [scale, opacity]);

  return (
    <Marker coordinate={coordinate} anchor={{ x: 0.5, y: 0.5 }}>
      <View style={styles.container}>
        <Animated.View
          style={[
            styles.ring,
            {
              transform: [{ scale }],
              opacity,
            },
          ]}
        />
        <View style={styles.dot} />
      </View>
    </Marker>
  );
};

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    justifyContent: 'center',
    width: 30,
    height: 30,
  },
  dot: {
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: '#3B82F6',
    borderWidth: 2,
    borderColor: '#FFFFFF',
    position: 'absolute',
  },
  ring: {
    width: 20,
    height: 20,
    borderRadius: 10,
    backgroundColor: 'rgba(59, 130, 246, 0.4)',
  },
});

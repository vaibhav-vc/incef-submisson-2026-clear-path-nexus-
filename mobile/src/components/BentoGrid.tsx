import React, { useEffect, useRef } from 'react';
import { StyleSheet, View, Animated, ViewStyle, StyleProp } from 'react-native';
import type { BentoSize } from '../types';

interface BentoGridProps {
  children: React.ReactNode;
  style?: StyleProp<ViewStyle>;
}

export const BentoGrid: React.FC<BentoGridProps> = ({ children, style }) => {
  const childArray = React.Children.toArray(children).filter(React.isValidElement) as React.ReactElement<{ size?: BentoSize }>[];
  // Stagger entry animations
  const animatedValues = useRef(childArray.map(() => new Animated.Value(0))).current;

  useEffect(() => {
    const animations = childArray.map((_, i) =>
      Animated.timing(animatedValues[i], {
        toValue: 1,
        duration: 300,
        delay: i * 50, // 50ms stagger
        useNativeDriver: true,
      })
    );
    Animated.stagger(50, animations).start();
  }, [childArray, animatedValues]);

  return (
    <View style={[styles.grid, style]}>
      {childArray.map((child, index) => {
        const opacity = animatedValues[index];
        const scale = animatedValues[index].interpolate({
          inputRange: [0, 1],
          outputRange: [0.95, 1],
        });

        return (
          <Animated.View
            key={index}
            style={{
              opacity,
              transform: [{ scale }],
              width: child.props.size === 'small' ? '31%' : child.props.size === 'medium' ? '65%' : child.props.size === 'half' ? '48%' : '100%',
              marginVertical: 6,
            }}
          >
            {child}
          </Animated.View>
        );
      })}
    </View>
  );
};

const styles = StyleSheet.create({
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    gap: 12,
  },
});

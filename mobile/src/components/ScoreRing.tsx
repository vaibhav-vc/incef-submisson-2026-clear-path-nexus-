import React, { useEffect, useRef } from 'react';
import { StyleSheet, View, Text, Animated, Easing } from 'react-native';
import Svg, { Circle } from 'react-native-svg';
import { getScoreColor, getStatusColor } from '../theme';
import type { RouteStatus } from '../types';

interface ScoreRingProps {
  score: number; // 0.0 to 1.0
  status: RouteStatus;
  animated?: boolean;
}

const AnimatedCircle = Animated.createAnimatedComponent(Circle);
const AnimatedText = Animated.createAnimatedComponent(Text);

export const ScoreRing: React.FC<ScoreRingProps> = React.memo(({
  score,
  status,
  animated = true,
}) => {
  const size = 140;
  const strokeWidth = 8;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;

  const animationValue = useRef(new Animated.Value(0)).current;
  const glowOpacity = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    animationValue.setValue(0);
    glowOpacity.setValue(0);
    
    Animated.sequence([
      Animated.timing(animationValue, {
        toValue: score,
        duration: animated ? 1200 : 0,
        easing: Easing.out(Easing.cubic),
        useNativeDriver: true,
      }),
      Animated.timing(glowOpacity, {
        toValue: 0.3,
        duration: 300,
        useNativeDriver: true,
      })
    ]).start();
  }, [score, animated, animationValue, glowOpacity]);

  // Color matching current score
  const color = getScoreColor(score);

  // SVG stroke-dashoffset interpolation
  const strokeDashoffset = animationValue.interpolate({
    inputRange: [0, 1],
    outputRange: [circumference, 0],
  });

  // Numeric count-up text
  const displayScore = Math.round(score * 100);

  return (
    <View style={styles.container}>
      <Animated.View style={[styles.ringContainer, { shadowColor: color, shadowRadius: 20, shadowOpacity: glowOpacity }]}>
        <Svg width={size} height={size}>
          {/* Background Ring */}
          <Circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            stroke="rgba(255, 255, 255, 0.08)"
            strokeWidth={strokeWidth}
            fill="none"
          />
          {/* Foreground Ring */}
          <AnimatedCircle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            stroke={color}
            strokeWidth={strokeWidth}
            strokeDasharray={circumference}
            strokeDashoffset={strokeDashoffset}
            strokeLinecap="round"
            fill="none"
            rotation="-90"
            origin={`${size / 2}, ${size / 2}`}
          />
        </Svg>
        <View style={[StyleSheet.absoluteFillObject, styles.textOverlay]}>
          <Text style={styles.scoreText}>{displayScore}</Text>
          <Text style={[styles.statusLabel, { color: getStatusColor(status) }]}>{status}</Text>
        </View>
      </Animated.View>
    </View>
  );
});

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    justifyContent: 'center',
    marginVertical: 12,
  },
  ringContainer: {
    width: 140,
    height: 140,
    position: 'relative',
    alignItems: 'center',
    justifyContent: 'center',
  },
  textOverlay: {
    position: 'absolute',
    alignItems: 'center',
    justifyContent: 'center',
  },
  scoreText: {
    fontSize: 36,
    fontWeight: '800',
    color: '#F0F4FF',
    letterSpacing: -1,
  },
  statusLabel: {
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 1.5,
    textTransform: 'uppercase',
    marginTop: 4,
  },
});

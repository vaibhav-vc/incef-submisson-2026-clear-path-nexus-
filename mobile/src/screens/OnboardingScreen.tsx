import React, { useState, useRef } from 'react';
import { StyleSheet, View, Text, Pressable, ScrollView, Dimensions } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { GlassCard } from '../components/GlassCard';
import { useTheme } from '../hooks/useTheme';

interface OnboardingScreenProps {
  onComplete: () => void;
}

const { width } = Dimensions.get('window');

export const OnboardingScreen: React.FC<OnboardingScreenProps> = ({ onComplete }) => {
  const { theme } = useTheme();
  const [activeIndex, setActiveIndex] = useState(0);
  const scrollRef = useRef<ScrollView>(null);

  const screens = [
    {
      title: '🚂 ClearPath Nexus',
      subtitle: 'Freight Corridor Intelligence',
      desc: 'Seamless cargo clearance evaluations for Indian Railways freight transit corridors.',
    },
    {
      title: '🗺️ Find Your Route',
      subtitle: 'Multi-Destination Transit',
      desc: 'Plot custom paths between terminals, search stations, and check dimensions instantly.',
    },
    {
      title: '🌦️ Live Intelligence',
      subtitle: 'Track telemetry & Weather',
      desc: 'Overpass and OpenWeather integrations warn dispatchers about storm risks and clearances.',
    },
    {
      title: '✅ Approve & Dispatch',
      subtitle: 'Safe Clearance Approval',
      desc: 'Save verified paths, evaluate cargo loads, and dispatch trains securely.',
    },
  ];

  const handleScroll = (event: any) => {
    const slide = Math.round(event.nativeEvent.contentOffset.x / width);
    if (slide !== activeIndex) {
      setActiveIndex(slide);
    }
  };

  const handleNext = async () => {
    if (activeIndex < screens.length - 1) {
      scrollRef.current?.scrollTo({
        x: (activeIndex + 1) * width,
        animated: true,
      });
      setActiveIndex(activeIndex + 1);
    } else {
      await finishOnboarding();
    }
  };

  const finishOnboarding = async () => {
    try {
      await AsyncStorage.setItem('onboarding_complete', 'true');
    } catch (_) {}
    onComplete();
  };

  return (
    <View style={styles.container}>
      <ScrollView
        ref={scrollRef}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        onScroll={handleScroll}
        scrollEventThrottle={16}
        style={styles.scroller}
      >
        {screens.map((item, index) => (
          <View key={index} style={[styles.slide, { width }]}>
            <GlassCard size="large" style={styles.card}>
              <Text style={styles.emojiTitle}>{item.title}</Text>
              <Text style={styles.subtitle}>{item.subtitle}</Text>
              <Text style={styles.desc}>{item.desc}</Text>
            </GlassCard>
          </View>
        ))}
      </ScrollView>

      {/* Progress Dots */}
      <View style={styles.footer}>
        <View style={styles.dots}>
          {screens.map((_, index) => (
            <View
              key={index}
              style={[
                styles.dot,
                {
                  backgroundColor: index === activeIndex ? '#00FF88' : 'rgba(255, 255, 255, 0.2)',
                },
              ]}
            />
          ))}
        </View>

        <View style={styles.buttons}>
          <Pressable onPress={finishOnboarding} style={styles.skipBtn}>
            <Text style={styles.skipText}>Skip</Text>
          </Pressable>
          <Pressable onPress={handleNext} style={styles.nextBtn}>
            <Text style={styles.nextText}>
              {activeIndex === screens.length - 1 ? 'Get Started' : 'Next'}
            </Text>
          </Pressable>
        </View>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#070B14',
  },
  scroller: {
    flex: 1,
  },
  slide: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
  },
  card: {
    padding: 32,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 16,
  },
  emojiTitle: {
    fontSize: 28,
    fontWeight: '800',
    color: '#F0F4FF',
    textAlign: 'center',
  },
  subtitle: {
    fontSize: 16,
    fontWeight: '700',
    color: '#3B82F6',
    textAlign: 'center',
  },
  desc: {
    fontSize: 14,
    fontWeight: '400',
    color: '#8892A4',
    textAlign: 'center',
    lineHeight: 20,
  },
  footer: {
    paddingBottom: 40,
    paddingHorizontal: 24,
    gap: 24,
  },
  dots: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 8,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  buttons: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  skipBtn: {
    padding: 12,
  },
  skipText: {
    color: '#8892A4',
    fontWeight: '600',
    fontSize: 15,
  },
  nextBtn: {
    backgroundColor: '#00FF88',
    borderRadius: 14,
    paddingVertical: 12,
    paddingHorizontal: 24,
    shadowColor: '#00FF88',
    shadowRadius: 12,
    shadowOpacity: 0.4,
    elevation: 3,
  },
  nextText: {
    color: '#070B14',
    fontWeight: '700',
    fontSize: 15,
  },
});

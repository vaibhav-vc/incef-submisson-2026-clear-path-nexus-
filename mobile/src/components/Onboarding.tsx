import AsyncStorage from '@react-native-async-storage/async-storage';
import { BlurView } from 'expo-blur';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Dimensions, FlatList, Platform, Pressable, StyleSheet, Text, View, ViewToken } from 'react-native';
import { palette } from '../theme';

const STORAGE_KEY = 'onboarding_complete';
const { width } = Dimensions.get('window');

const SLIDES = [
  { icon: 'TRAIN', title: 'ClearPath Nexus', body: 'Smart railway cargo clearance for India' },
  { icon: 'MAP', title: 'Find Your Route', body: 'Select stations, add stops, and evaluate each corridor segment.' },
  { icon: 'WX', title: 'Live Intelligence', body: 'Weather, congestion, history, and port timing shape the dispatch score.' },
  { icon: 'OK', title: 'Approve & Dispatch', body: 'Confirm only routes with the right clearance and reliability profile.' },
];

export default function Onboarding() {
  const [visible, setVisible] = useState(false);
  const [index, setIndex] = useState(0);
  const listRef = useRef<FlatList<(typeof SLIDES)[number]>>(null);

  useEffect(() => {
    let active = true;
    void AsyncStorage.getItem(STORAGE_KEY).then((value) => {
      if (active) setVisible(value !== 'true');
    });
    return () => {
      active = false;
    };
  }, []);

  const complete = useCallback(async () => {
    await AsyncStorage.setItem(STORAGE_KEY, 'true');
    setVisible(false);
  }, []);

  const next = useCallback(() => {
    if (index >= SLIDES.length - 1) {
      void complete();
      return;
    }
    listRef.current?.scrollToIndex({ index: index + 1, animated: true });
  }, [complete, index]);

  const onViewableItemsChanged = useRef(({ viewableItems }: { viewableItems: ViewToken[] }) => {
    const nextIndex = viewableItems[0]?.index;
    if (nextIndex != null) setIndex(nextIndex);
  }).current;

  if (!visible) return null;

  return (
    <View style={styles.root}>
      <FlatList
        ref={listRef}
        data={SLIDES}
        keyExtractor={(item) => item.title}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        onViewableItemsChanged={onViewableItemsChanged}
        viewabilityConfig={{ itemVisiblePercentThreshold: 60 }}
        renderItem={({ item }) => (
          <View style={styles.slide}>
            {Platform.OS === 'android' ? (
              <SlideCard item={item} />
            ) : (
              <BlurView intensity={80} tint="dark" style={styles.blur}>
                <SlideCard item={item} />
              </BlurView>
            )}
          </View>
        )}
      />
      <View style={styles.footer}>
        <Pressable testID="onboarding-skip" onPress={complete} hitSlop={10}>
          <Text style={styles.skip}>Skip</Text>
        </Pressable>
        <View style={styles.dots}>
          {SLIDES.map((slide, dotIndex) => (
            <View key={slide.title} style={[styles.dot, dotIndex === index && styles.dotActive]} />
          ))}
        </View>
        <Pressable testID="onboarding-next" style={styles.next} onPress={next}>
          <Text style={styles.nextText}>{index === SLIDES.length - 1 ? 'Get Started' : 'Next'}</Text>
        </Pressable>
      </View>
    </View>
  );
}

function SlideCard({ item }: { item: (typeof SLIDES)[number] }) {
  return (
    <View style={styles.card}>
      <View style={styles.highlight} />
      <Text style={styles.icon}>{item.icon}</Text>
      <Text style={styles.title}>{item.title}</Text>
      <Text style={styles.body}>{item.body}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { ...StyleSheet.absoluteFillObject, zIndex: 80, backgroundColor: palette.base },
  slide: { width, alignItems: 'center', justifyContent: 'center', padding: 24 },
  blur: { width: '100%', borderRadius: 20, overflow: 'hidden' },
  card: {
    width: '100%',
    minHeight: 320,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 16,
    padding: 28,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: palette.glassBorder,
    backgroundColor: palette.glassStrong,
    overflow: 'hidden',
  },
  highlight: { position: 'absolute', top: 0, left: 20, right: 20, height: 1, backgroundColor: palette.highlight },
  icon: { color: palette.primary, fontSize: 34, fontWeight: '900', letterSpacing: 0 },
  title: { color: palette.text, fontSize: 24, fontWeight: '800', textAlign: 'center' },
  body: { color: palette.textMuted, fontSize: 15, lineHeight: 22, textAlign: 'center' },
  footer: {
    position: 'absolute',
    left: 24,
    right: 24,
    bottom: 28,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  skip: { color: palette.textMuted, fontWeight: '700' },
  dots: { flexDirection: 'row', gap: 8 },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: palette.glassBorder },
  dotActive: { width: 22, backgroundColor: palette.primary },
  next: { backgroundColor: palette.primary, borderRadius: 14, paddingHorizontal: 16, paddingVertical: 12 },
  nextText: { color: palette.base, fontWeight: '800' },
});

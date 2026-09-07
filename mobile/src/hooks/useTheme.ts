import { useState, useEffect, useCallback } from 'react';
import { useColorScheme } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { darkTheme, lightTheme } from '../theme';
import type { AppTheme } from '../types';

export function useTheme() {
  const systemScheme = useColorScheme();
  const [isDark, setIsDark] = useState(systemScheme !== 'light');

  useEffect(() => {
    async function loadThemePreference() {
      try {
        const value = await AsyncStorage.getItem('user_theme_preference');
        if (value !== null) {
          setIsDark(value === 'dark');
        } else {
          setIsDark(systemScheme !== 'light');
        }
      } catch (_) {}
    }
    loadThemePreference();
  }, [systemScheme]);

  const toggleTheme = useCallback(async () => {
    try {
      const nextMode = !isDark;
      setIsDark(nextMode);
      await AsyncStorage.setItem('user_theme_preference', nextMode ? 'dark' : 'light');
    } catch (_) {}
  }, [isDark]);

  const theme: AppTheme = isDark ? darkTheme : lightTheme;

  return { theme, isDark, toggleTheme };
}

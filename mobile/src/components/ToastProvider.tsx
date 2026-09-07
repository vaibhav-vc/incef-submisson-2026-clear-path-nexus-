import React, { createContext, useContext, useState, useCallback, useRef } from 'react';
import { StyleSheet, View, Text, Animated, Pressable, Dimensions } from 'react-native';
import { GlassCard } from './GlassCard';
import type { ToastMessage, ToastType } from '../types';

interface ToastContextType {
  showToast: (message: string, type: ToastType, duration?: number) => void;
}

const ToastContext = createContext<ToastContextType | null>(null);

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return context;
}

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const anims = useRef<Record<string, Animated.Value>>({}).current;

  const dismissToast = useCallback((id: string) => {
    const anim = anims[id];
    if (anim) {
      Animated.timing(anim, {
        toValue: -150,
        duration: 250,
        useNativeDriver: true,
      }).start(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
        delete anims[id];
      });
    }
  }, [anims]);

  const showToast = useCallback((message: string, type: ToastType, duration: number = 3000) => {
    const id = Math.random().toString(36).substring(7);
    const anim = new Animated.Value(-150);
    anims[id] = anim;

    setToasts((prev) => {
      const next = [...prev, { id, type, message, duration }];
      if (next.length > 3) {
        // Dismiss the oldest active toast
        dismissToast(next[0].id);
        return next.slice(1);
      }
      return next;
    });

    Animated.spring(anim, {
      toValue: 0,
      useNativeDriver: true,
      friction: 8,
      tension: 40,
    }).start();

    if (duration > 0) {
      setTimeout(() => {
        dismissToast(id);
      }, duration);
    }
  }, [dismissToast, anims]);

  const getTypeColor = (type: ToastType): string => {
    switch (type) {
      case 'success':
        return '#00FF88';
      case 'warning':
        return '#FF8C00';
      case 'error':
        return '#FF3B5C';
      case 'info':
        return '#3B82F6';
      default:
        return '#F0F4FF';
    }
  };

  return (
    <ToastContext.Provider value={{ showToast }}>
      <View style={styles.container}>
        {children}
        <View style={styles.toastStack}>
          {toasts.map((toast) => {
            const anim = anims[toast.id] || new Animated.Value(0);
            return (
              <Animated.View
                key={toast.id}
                style={[
                  styles.toastWrapper,
                  {
                    transform: [{ translateY: anim }],
                  },
                ]}
              >
                <Pressable onPress={() => dismissToast(toast.id)}>
                  <GlassCard
                    size="large"
                    style={[
                      styles.toastCard,
                      {
                        borderLeftColor: getTypeColor(toast.type),
                        borderLeftWidth: 4,
                      },
                    ]}
                  >
                    <View style={styles.toastInner}>
                      <Text style={styles.emoji}>
                        {toast.type === 'success' ? '✅' : toast.type === 'warning' ? '⚠️' : toast.type === 'error' ? '❌' : 'ℹ️'}
                      </Text>
                      <Text style={styles.toastText}>{toast.message}</Text>
                    </View>
                  </GlassCard>
                </Pressable>
              </Animated.View>
            );
          })}
        </View>
      </View>
    </ToastContext.Provider>
  );
};

export default ToastProvider;

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  toastStack: {
    position: 'absolute',
    top: 50,
    left: 20,
    right: 20,
    zIndex: 9999,
    gap: 8,
  },
  toastWrapper: {
    width: '100%',
  },
  toastCard: {
    paddingVertical: 10,
    paddingHorizontal: 16,
    borderRadius: 12,
  },
  toastInner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  emoji: {
    fontSize: 16,
  },
  toastText: {
    color: '#F0F4FF',
    fontSize: 13,
    fontWeight: '600',
    flex: 1,
  },
});

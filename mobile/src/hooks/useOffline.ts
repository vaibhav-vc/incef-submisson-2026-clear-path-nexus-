import { useState, useEffect } from 'react';
import NetInfo from '@react-native-community/netinfo';

export function useOffline() {
  const [isOffline, setIsOffline] = useState(false);
  const [wasOffline, setWasOffline] = useState(false);

  useEffect(() => {
    let previouslyOffline = false;

    const unsubscribe = NetInfo.addEventListener((state) => {
      const offline = state.isConnected === false || state.isInternetReachable === false;
      setIsOffline(offline);

      if (!offline && previouslyOffline) {
        setWasOffline(true);
        // Reset the wasOffline transition flag after 5 seconds
        const timer = setTimeout(() => {
          setWasOffline(false);
        }, 5000);
        return () => clearTimeout(timer);
      }

      previouslyOffline = offline;
    });

    return () => {
      unsubscribe();
    };
  }, []);

  return { isOffline, wasOffline };
}

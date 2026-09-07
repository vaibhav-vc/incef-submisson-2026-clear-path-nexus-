import React from 'react';
import { StyleSheet, View, Text, Pressable, ScrollView } from 'react-native';
import { logger } from '../utils/logger';
import { GlassCard } from './GlassCard';

interface Props {
  children: React.ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  expanded: boolean;
}

export class ErrorBoundary extends React.Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
    expanded: false,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error, expanded: false };
  }

  public componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    logger.error('ErrorBoundary caught an unhandled exception:', error, errorInfo as any);
  }

  private handleRestart = () => {
    this.setState({ hasError: false, error: null, expanded: false });
  };

  public render() {
    if (this.state.hasError) {
      return (
        <View style={styles.container}>
          <GlassCard size="large" style={styles.card}>
            <Text style={styles.title}>Something went wrong</Text>
            <Text style={styles.subtitle}>
              ClearPath encountered an error. Your data is safe.
            </Text>
            <Pressable style={styles.button} onPress={this.handleRestart}>
              <Text style={styles.buttonText}>Restart App</Text>
            </Pressable>
            <Pressable
              onPress={() => this.setState({ expanded: !this.state.expanded })}
              style={styles.expandButton}
            >
              <Text style={styles.expandText}>
                {this.state.expanded ? '▼ Hide Details' : '▶ Technical details'}
              </Text>
            </Pressable>
            {this.state.expanded && (
              <ScrollView style={styles.errorScroll}>
                <Text style={styles.errorDetails}>
                  {this.state.error?.stack || this.state.error?.message || 'Unknown error'}
                </Text>
              </ScrollView>
            )}
          </GlassCard>
        </View>
      );
    }

    return this.props.children;
  }
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#070B14',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
  },
  card: {
    padding: 24,
    alignItems: 'center',
  },
  title: {
    fontSize: 20,
    fontWeight: '800',
    color: '#F0F4FF',
    marginBottom: 8,
    textAlign: 'center',
  },
  subtitle: {
    fontSize: 14,
    color: '#8892A4',
    textAlign: 'center',
    marginBottom: 24,
  },
  button: {
    backgroundColor: '#00FF88',
    borderRadius: 14,
    paddingVertical: 14,
    paddingHorizontal: 24,
    width: '100%',
    alignItems: 'center',
    shadowColor: '#00FF88',
    shadowRadius: 12,
    shadowOpacity: 0.4,
    elevation: 3,
  },
  buttonText: {
    color: '#070B14',
    fontWeight: '700',
    fontSize: 15,
  },
  expandButton: {
    marginTop: 20,
    padding: 8,
  },
  expandText: {
    color: '#3B82F6',
    fontSize: 12,
    fontWeight: '600',
  },
  errorScroll: {
    maxHeight: 150,
    width: '100%',
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderRadius: 8,
    padding: 10,
    marginTop: 12,
  },
  errorDetails: {
    color: '#FF3B5C',
    fontSize: 11,
    fontFamily: 'monospace',
  },
});
export default ErrorBoundary;

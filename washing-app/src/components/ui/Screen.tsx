/**
 * Layout primitives: a screen wrapper with safe-area handling and consistent
 * padding, plus a keyboard-avoiding scroll container for forms.
 */

import { type ReactNode } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  RefreshControl,
  ScrollView,
  StyleSheet,
  View,
  type ViewStyle,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useTheme } from '@/theme';

interface ScreenProps {
  children: ReactNode;
  /** Renders a pull-to-refresh spinner and wires the handler. */
  onRefresh?: () => void;
  refreshing?: boolean;
  scrollable?: boolean;
  contentStyle?: ViewStyle;
  /** Extra bottom padding, e.g. to clear a sticky footer button. */
  bottomInset?: number;
  testID?: string;
}

export function Screen({
  children,
  onRefresh,
  refreshing = false,
  scrollable = true,
  contentStyle,
  bottomInset = 0,
  testID,
}: ScreenProps) {
  const { colors, spacing } = useTheme();
  const insets = useSafeAreaInsets();

  const padding = {
    paddingTop: insets.top + spacing.sm,
    paddingLeft: spacing.lg + Math.max(insets.left, 0),
    paddingRight: spacing.lg + Math.max(insets.right, 0),
    paddingBottom: spacing.lg + insets.bottom + bottomInset,
  };

  if (!scrollable) {
    return (
      <View testID={testID} style={[styles.fill, { backgroundColor: colors.background }, padding, contentStyle]}>
        {children}
      </View>
    );
  }

  return (
    <KeyboardAvoidingView
      style={[styles.fill, { backgroundColor: colors.background }]}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={Platform.OS === 'ios' ? insets.top : 0}>
      <ScrollView
        testID={testID}
        style={styles.fill}
        contentContainerStyle={[padding, contentStyle]}
        // Lets a control receive a tap while the keyboard is open, which is what
        // makes dropdowns and date fields usable inside a form.
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode={Platform.OS === 'ios' ? 'interactive' : 'on-drag'}
        refreshControl={
          onRefresh ? (
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.tint} />
          ) : undefined
        }>
        {children}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
});

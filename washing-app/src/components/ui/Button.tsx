/**
 * The app's button.
 *
 * One component for every pressable action so loading, disabled and accessibility
 * states cannot differ between screens. `loading` disables the button and marks it
 * busy for screen readers, which prevents a double submission on slow networks.
 */

import { ActivityIndicator, Pressable, StyleSheet, Text, View, type StyleProp, type ViewStyle } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

import { useTheme } from '@/theme';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';

interface ButtonProps {
  label: string;
  onPress: () => void;
  variant?: ButtonVariant;
  loading?: boolean;
  disabled?: boolean;
  icon?: keyof typeof Ionicons.glyphMap;
  fullWidth?: boolean;
  style?: StyleProp<ViewStyle>;
  accessibilityHint?: string;
  testID?: string;
}

export function Button({
  label,
  onPress,
  variant = 'primary',
  loading = false,
  disabled = false,
  icon,
  fullWidth = true,
  style,
  accessibilityHint,
  testID,
}: ButtonProps) {
  const { colors, radius, spacing, type, minTouchTarget } = useTheme();
  const isInert = disabled || loading;

  const palette: Record<ButtonVariant, { background: string; border: string; text: string }> = {
    primary: { background: colors.tint, border: colors.tint, text: '#FFFFFF' },
    secondary: { background: colors.surface, border: colors.border, text: colors.text },
    ghost: { background: 'transparent', border: 'transparent', text: colors.tint },
    danger: { background: colors.dangerSurface, border: colors.danger, text: colors.danger },
  };
  const tone = palette[variant];

  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      disabled={isInert}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityHint={accessibilityHint}
      accessibilityState={{ disabled: isInert, busy: loading }}
      style={({ pressed }) => [
        styles.base,
        {
          backgroundColor: tone.background,
          borderColor: tone.border,
          borderRadius: radius.md,
          paddingHorizontal: spacing.lg,
          minHeight: minTouchTarget,
          opacity: isInert ? 0.55 : pressed ? 0.85 : 1,
          alignSelf: fullWidth ? 'stretch' : 'flex-start',
        },
        style,
      ]}>
      <View style={styles.content}>
        {loading ? (
          <ActivityIndicator size="small" color={tone.text} />
        ) : (
          <>
            {icon ? <Ionicons name={icon} size={18} color={tone.text} style={styles.icon} /> : null}
            <Text numberOfLines={1} style={[styles.label, type.bodyStrong, { color: tone.text }]}>
              {label}
            </Text>
          </>
        )}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  content: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
  },
  icon: { marginRight: 8 },
  label: { textAlign: 'center' },
});

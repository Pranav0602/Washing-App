/**
 * Containers and state components.
 *
 * Every list and detail screen in the app renders exactly one of
 * `LoadingState` / `ErrorState` / `EmptyState` before its content. Centralising them
 * is what makes it impossible for a screen to silently render nothing: the empty
 * case is an explicit, designed screen rather than a blank area.
 */

import { type ReactNode } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

import { errorHint } from '@/lib/format';
import { toDisplayMessage } from '@/lib/apiError';
import { useTheme } from '@/theme';

// ----------------------------------------------------------------- Card

export function Card({
  children,
  style,
  testID,
}: {
  children: ReactNode;
  style?: object;
  testID?: string;
}) {
  const { colors, radius, spacing } = useTheme();
  return (
    <View
      testID={testID}
      style={[
        {
          backgroundColor: colors.surface,
          borderColor: colors.border,
          borderWidth: 1,
          borderRadius: radius.lg,
          padding: spacing.lg,
          marginBottom: spacing.md,
        },
        style,
      ]}>
      {children}
    </View>
  );
}

/** A tappable card. Used for list rows that navigate. */
export function PressableCard({
  children,
  onPress,
  accessibilityLabel,
  accessibilityHint,
  testID,
}: {
  children: ReactNode;
  onPress: () => void;
  accessibilityLabel?: string;
  accessibilityHint?: string;
  testID?: string;
}) {
  const { colors, radius, spacing } = useTheme();
  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      accessibilityHint={accessibilityHint}
      style={({ pressed }) => [
        {
          backgroundColor: colors.surface,
          borderColor: colors.border,
          borderWidth: 1,
          borderRadius: radius.lg,
          padding: spacing.lg,
          marginBottom: spacing.md,
          opacity: pressed ? 0.85 : 1,
        },
      ]}>
      {children}
    </Pressable>
  );
}

export function SectionTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  const { colors, spacing, type } = useTheme();
  return (
    <View style={[styles.sectionRow, { marginBottom: spacing.md }]}>
      <Text
        accessibilityRole="header"
        style={[type.heading, { color: colors.text, flex: 1 }]}>
        {children}
      </Text>
      {action}
    </View>
  );
}

// ---------------------------------------------------------------- Badge

export type BadgeTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger' | 'accent';

export function Badge({
  label,
  tone = 'neutral',
  icon,
  testID,
}: {
  label: string;
  tone?: BadgeTone;
  icon?: keyof typeof Ionicons.glyphMap;
  testID?: string;
}) {
  const { colors, radius, spacing, type } = useTheme();

  const tones: Record<BadgeTone, { background: string; text: string }> = {
    neutral: { background: colors.surfaceAlt, text: colors.mutedText },
    info: { background: colors.infoSurface, text: colors.info },
    success: { background: colors.successSurface, text: colors.success },
    warning: { background: colors.warningSurface, text: colors.warning },
    danger: { background: colors.dangerSurface, text: colors.danger },
    accent: { background: colors.tint, text: '#FFFFFF' },
  };
  const palette = tones[tone];

  return (
    <View
      testID={testID}
      accessibilityRole="text"
      accessibilityLabel={label}
      style={[
        styles.badge,
        {
          backgroundColor: palette.background,
          borderRadius: radius.pill,
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.xs,
        },
      ]}>
      {icon ? <Ionicons name={icon} size={12} color={palette.text} style={styles.badgeIcon} /> : null}
      <Text style={[type.micro, { color: palette.text }]}>{label}</Text>
    </View>
  );
}

// ----------------------------------------------------------------- States

export function LoadingState({ label = 'Loading' }: { label?: string }) {
  const { colors, spacing, type } = useTheme();
  return (
    <View
      accessibilityRole="progressbar"
      accessibilityLabel={label}
      style={[styles.centered, { paddingVertical: spacing.xxl }]}>
      <ActivityIndicator size="large" color={colors.tint} />
      <Text style={[type.caption, { color: colors.mutedText, marginTop: spacing.md }]}>{label}</Text>
    </View>
  );
}

/** Placeholder rows shown while first-load data arrives. */
export function SkeletonList({ count = 3 }: { count?: number }) {
  const { colors, spacing, radius } = useTheme();
  return (
    <View accessibilityLabel="Loading content">
      {Array.from({ length: count }).map((_, index) => (
        <View
          key={index}
          style={{
            backgroundColor: colors.surfaceAlt,
            borderRadius: radius.md,
            height: 84,
            marginBottom: spacing.md,
          }}
        />
      ))}
    </View>
  );
}

export function ErrorState({
  error,
  onRetry,
  title = 'Something went wrong',
  testID,
}: {
  error: unknown;
  onRetry?: () => void;
  title?: string;
  testID?: string;
}) {
  const { colors, spacing, type, radius } = useTheme();

  // The backend's stable code often carries a next step the raw message lacks.
  const code = (error as { code?: string })?.code;
  const hint = errorHint(code);

  return (
    <View testID={testID} style={[styles.centered, { paddingVertical: spacing.xl }]}>
      <Ionicons name="alert-circle-outline" size={40} color={colors.danger} />
      <Text style={[type.heading, { color: colors.text, marginTop: spacing.md, textAlign: 'center' }]}>
        {title}
      </Text>
      <Text
        style={[
          type.caption,
          { color: colors.mutedText, marginTop: spacing.sm, textAlign: 'center' },
        ]}>
        {toDisplayMessage(error)}
      </Text>
      {hint ? (
        <View
          style={{
            marginTop: spacing.md,
            padding: spacing.md,
            backgroundColor: colors.infoSurface,
            borderRadius: radius.md,
          }}>
          <Text style={[type.caption, { color: colors.info, textAlign: 'center' }]}>{hint}</Text>
        </View>
      ) : null}
      {onRetry ? (
        <Pressable
          onPress={onRetry}
          accessibilityRole="button"
          accessibilityLabel="Try again"
          style={{
            marginTop: spacing.lg,
            paddingHorizontal: spacing.xl,
            paddingVertical: spacing.md,
            borderRadius: radius.md,
            borderWidth: 1,
            borderColor: colors.border,
          }}>
          <Text style={[type.bodyStrong, { color: colors.tint }]}>Try again</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

export function EmptyState({
  title,
  message,
  icon = 'file-tray-outline',
  action,
  testID,
}: {
  title: string;
  message?: string;
  icon?: keyof typeof Ionicons.glyphMap;
  action?: { label: string; onPress: () => void };
  testID?: string;
}) {
  const { colors, spacing, type, radius } = useTheme();
  return (
    <View testID={testID} style={[styles.centered, { paddingVertical: spacing.xl }]}>
      <Ionicons name={icon} size={40} color={colors.icon} />
      <Text style={[type.heading, { color: colors.text, marginTop: spacing.md, textAlign: 'center' }]}>
        {title}
      </Text>
      {message ? (
        <Text
          style={[
            type.caption,
            { color: colors.mutedText, marginTop: spacing.sm, textAlign: 'center' },
          ]}>
          {message}
        </Text>
      ) : null}
      {action ? (
        <Pressable
          onPress={action.onPress}
          accessibilityRole="button"
          accessibilityLabel={action.label}
          style={{
            marginTop: spacing.lg,
            paddingHorizontal: spacing.xl,
            paddingVertical: spacing.md,
            borderRadius: radius.md,
            backgroundColor: colors.tint,
          }}>
          <Text style={[type.bodyStrong, { color: '#FFFFFF' }]}>{action.label}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

// ---------------------------------------------------------------- Banner

export type BannerTone = 'info' | 'success' | 'warning' | 'danger';

/**
 * An inline, non-blocking message.
 *
 * Used for honest-status messaging the PDF requires: a stale ETA, a delay, a paused
 * zone. Announced to screen readers so a status change is not silent.
 */
export function Banner({
  tone = 'info',
  title,
  message,
  action,
  testID,
}: {
  tone?: BannerTone;
  title?: string;
  message: string;
  action?: { label: string; onPress: () => void };
  testID?: string;
}) {
  const { colors, spacing, type, radius } = useTheme();

  const tones: Record<BannerTone, { background: string; border: string; text: string }> = {
    info: { background: colors.infoSurface, border: colors.info, text: colors.info },
    success: { background: colors.successSurface, border: colors.success, text: colors.success },
    warning: { background: colors.warningSurface, border: colors.warning, text: colors.warning },
    danger: { background: colors.dangerSurface, border: colors.danger, text: colors.danger },
  };
  const palette = tones[tone];

  const icons: Record<BannerTone, keyof typeof Ionicons.glyphMap> = {
    info: 'information-circle-outline',
    success: 'checkmark-circle-outline',
    warning: 'alert-circle-outline',
    danger: 'close-circle-outline',
  };

  return (
    <View
      testID={testID}
      accessibilityRole="alert"
      accessibilityLiveRegion="polite"
      style={{
        backgroundColor: palette.background,
        borderLeftWidth: 3,
        borderLeftColor: palette.border,
        borderRadius: radius.md,
        padding: spacing.md,
        marginBottom: spacing.md,
      }}>
      <View style={styles.bannerRow}>
        <Ionicons name={icons[tone]} size={18} color={palette.text} style={styles.bannerIcon} />
        <View style={styles.bannerText}>
          {title ? (
            <Text style={[type.captionStrong, { color: palette.text }]}>{title}</Text>
          ) : null}
          <Text style={[type.caption, { color: palette.text, marginTop: title ? 2 : 0 }]}>{message}</Text>
        </View>
      </View>
      {action ? (
        <Pressable
          onPress={action.onPress}
          accessibilityRole="button"
          accessibilityLabel={action.label}
          style={{ marginTop: spacing.sm }}>
          <Text style={[type.captionStrong, { color: palette.text }]}>{action.label}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

// ------------------------------------------------------------------ Rows

/** A label/value row, used for money breakdowns and detail panels. */
export function DetailRow({
  label,
  value,
  emphasis = false,
  tone,
  testID,
}: {
  label: string;
  value: string;
  emphasis?: boolean;
  tone?: 'default' | 'success' | 'danger';
  testID?: string;
}) {
  const { colors, spacing, type } = useTheme();

  const valueColor =
    tone === 'success' ? colors.success : tone === 'danger' ? colors.danger : colors.text;

  return (
    <View
      testID={testID}
      style={[styles.detailRow, { paddingVertical: spacing.xs }]}
      accessible
      accessibilityLabel={`${label}: ${value}`}>
      <Text style={[type.body, { color: colors.mutedText, flex: 1, marginRight: spacing.md }]}>{label}</Text>
      <Text
        style={[
          emphasis ? type.bodyStrong : type.body,
          { color: valueColor, textAlign: 'right' },
        ]}>
        {value}
      </Text>
    </View>
  );
}

/** A bulleted inclusion/exclusion list. */
export function BulletList({
  title,
  items,
  tone = 'default',
}: {
  title: string;
  items: string[];
  tone?: 'default' | 'muted';
}) {
  const { colors, spacing, type } = useTheme();
  if (items.length === 0) return null;

  return (
    <View style={{ marginBottom: spacing.md }}>
      <Text style={[type.captionStrong, { color: colors.mutedText, marginBottom: spacing.xs }]}>
        {title}
      </Text>
      {items.map((item, index) => (
        <View key={`${item}-${index}`} style={[styles.bulletRow, { marginBottom: 2 }]}>
          <Text style={[type.caption, { color: colors.icon, marginRight: spacing.sm }]}>
            {tone === 'muted' ? '−' : '•'}
          </Text>
          <Text style={[type.caption, { color: colors.text, flex: 1 }]}>{item}</Text>
        </View>
      ))}
    </View>
  );
}

/** A thin divider that respects the theme. */
export function Divider() {
  const { colors, spacing } = useTheme();
  return <View style={{ height: 1, backgroundColor: colors.border, marginVertical: spacing.md }} />;
}

const styles = StyleSheet.create({
  sectionRow: { flexDirection: 'row', alignItems: 'center' },
  centered: { alignItems: 'center', justifyContent: 'center' },
  badge: { flexDirection: 'row', alignItems: 'center', alignSelf: 'flex-start' },
  badgeIcon: { marginRight: 4 },
  bannerRow: { flexDirection: 'row', alignItems: 'flex-start' },
  bannerIcon: { marginRight: 8 },
  bannerText: { flex: 1 },
  detailRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  bulletRow: { flexDirection: 'row', alignItems: 'flex-start' },
});

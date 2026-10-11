/**
 * The 10-minute arrival SLA countdown.
 *
 * Every on-demand booking promises a partner at the car within 10 minutes of
 * creation. This component renders the remaining time and the phase message,
 * and fires haptic feedback when the partner arrives.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import * as Haptics from 'expo-haptics';

import { Card } from '@/components/ui';
import { useTheme } from '@/theme';

export const ARRIVAL_SLA_MS = 10 * 60 * 1000;

export function computeArrivalDeadlineMs(createdAt: string): number {
  return new Date(createdAt).getTime() + ARRIVAL_SLA_MS;
}

export function remainingSeconds(deadlineMs: number, nowMs: number): number {
  return Math.max(0, Math.ceil((deadlineMs - nowMs) / 1000));
}

export function formatRemaining(totalSeconds: number): string {
  const safe = Math.max(0, totalSeconds);
  const minutes = Math.floor(safe / 60);
  const seconds = safe % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

export type ArrivalPhase = 'searching' | 'en_route' | 'arriving' | 'arrived' | 'overdue';

export function phaseFor(remainingSecs: number, status?: string): ArrivalPhase {
  if (status === 'arrived' || status === 'in_service' || status === 'completed' || status === 'payment_captured') {
    return 'arrived';
  }
  const elapsed = 600 - Math.max(0, remainingSecs);
  if (remainingSecs <= 0) return 'overdue';
  if (elapsed < 120) return 'searching';
  if (elapsed < 480) return 'en_route';
  return 'arriving';
}

const PHASE_MESSAGES: Record<ArrivalPhase, string> = {
  searching: 'Searching for nearest partner...',
  en_route: 'Partner assigned & driving to you',
  arriving: 'Partner arriving now!',
  arrived: 'Partner has arrived',
  overdue: 'Arrival taking longer than promised — we are on it',
};

export function ArrivalCountdown({
  createdAt,
  status,
}: {
  createdAt: string;
  status?: string;
}) {
  const { colors, spacing, type, radius } = useTheme();
  const deadlineMs = useMemo(() => computeArrivalDeadlineMs(createdAt), [createdAt]);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const firedHaptic = useRef(false);

  useEffect(() => {
    const handle = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(handle);
  }, []);

  const remaining = remainingSeconds(deadlineMs, nowMs);
  const phase = phaseFor(remaining, status);

  useEffect(() => {
    if (phase === 'arrived' && !firedHaptic.current) {
      firedHaptic.current = true;
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
    }
  }, [phase]);

  return (
    <Card testID="arrival-countdown">
      <View style={styles.row}>
        <View
          testID="countdown-pill"
          style={[styles.pill, { backgroundColor: colors.tint, borderRadius: radius.pill }]}>
          <Text testID="countdown-time" style={[type.title, { color: '#FFFFFF' }]}>
            {formatRemaining(remaining)}
          </Text>
        </View>
        <View style={{ flex: 1 }}>
          <Text style={[type.bodyStrong, { color: colors.text }]}>10-minute arrival promise</Text>
          <Text testID="countdown-status" style={[type.caption, { color: colors.mutedText, marginTop: 2 }]}>
            {PHASE_MESSAGES[phase]}
          </Text>
        </View>
      </View>
      <View
        style={[
          styles.barTrack,
          { backgroundColor: colors.border, borderRadius: radius.pill, marginTop: spacing.sm },
        ]}>
        <View
          testID="countdown-progress"
          style={[
            styles.barFill,
            {
              backgroundColor: colors.tint,
              width: `${Math.min(100, Math.max(0, (remaining / 600) * 100))}%`,
            },
          ]}
        />
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  pill: { paddingHorizontal: 14, paddingVertical: 8 },
  barTrack: { height: 6, overflow: 'hidden' },
  barFill: { height: '100%' },
});

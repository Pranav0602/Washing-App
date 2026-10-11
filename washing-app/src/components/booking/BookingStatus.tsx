/**
 * Booking status presentation.
 *
 * The lifecycle has a clear happy path and a set of exception branches. Showing a
 * linear progress bar for an exception would imply the job is still advancing, so
 * `StatusBadge` and `BookingTimeline` both branch explicitly: exceptions are labelled
 * as stopped, never as "step 4 of 10".
 */

import { StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

import type { BookingStatus } from '@/api/types';
import {
  HAPPY_PATH,
  STATUS_LABELS,
  bookingProgress,
  isExceptionStatus,
  isTerminalStatus,
} from '@/lib/format';
import { useTheme } from '@/theme';

import { Badge, DetailRow } from '@/components/ui';

const TONE_BY_STATUS: Record<BookingStatus, 'neutral' | 'info' | 'success' | 'warning' | 'danger' | 'accent'> = {
  requested: 'neutral',
  quote_accepted: 'info',
  dispatching: 'info',
  assigned: 'accent',
  en_route: 'accent',
  arrived: 'accent',
  in_service: 'accent',
  completed: 'success',
  payment_captured: 'success',
  partner_payout_eligible: 'success',
  expired_offer: 'warning',
  no_partner_available: 'warning',
  cancelled: 'danger',
  partner_no_show: 'danger',
  unsafe_site: 'warning',
  payment_failed: 'danger',
  disputed_work: 'warning',
  refunded: 'info',
};

export function StatusBadge({
  status,
  testID,
}: {
  status: BookingStatus;
  testID?: string;
}) {
  const tone = TONE_BY_STATUS[status] ?? 'neutral';
  return <Badge label={STATUS_LABELS[status] ?? status} tone={tone} testID={testID} />;
}

/**
 * A horizontal progress indicator for the happy path.
 *
 * Renders nothing extra for exception branches beyond an explicit note, so a stopped
 * job never looks like it is progressing.
 */
export function BookingProgress({ status }: { status: BookingStatus }) {
  const { colors, spacing } = useTheme();
  const progress = bookingProgress(status);

  if (progress === -1) {
    return (
      <View style={{ marginBottom: spacing.md }}>
        <Text style={{ color: colors.mutedText, fontSize: 13 }}>
          Progress stopped at this step. See the details below.
        </Text>
      </View>
    );
  }

  const percent = (progress / (HAPPY_PATH.length - 1)) * 100;

  return (
    <View
      style={{ marginBottom: spacing.md }}
      accessible
      accessibilityRole="progressbar"
      accessibilityLabel={`Step ${progress + 1} of ${HAPPY_PATH.length}`}
      accessibilityValue={{ min: 1, max: HAPPY_PATH.length, now: progress + 1 }}>
      <View style={[styles.track, { backgroundColor: colors.surfaceAlt, borderRadius: 4 }]}>
        <View
          style={{
            width: `${percent}%`,
            backgroundColor: colors.tint,
            height: '100%',
            borderRadius: 4,
          }}
        />
      </View>
      <View style={[styles.captionRow, { marginTop: spacing.xs }]}>
        <Text style={{ color: colors.mutedText, fontSize: 12 }}>{STATUS_LABELS[HAPPY_PATH[0]]}</Text>
        <Text style={{ color: colors.mutedText, fontSize: 12 }}>
          {STATUS_LABELS[HAPPY_PATH[Math.min(progress + 1, HAPPY_PATH.length - 1)]]}
        </Text>
      </View>
    </View>
  );
}

export interface TimelineStep {
  label: string;
  detail?: string;
  done: boolean;
  active?: boolean;
  /** Set when this step is what went wrong. */
  failed?: boolean;
}

/** A vertical step list used on the booking detail screen. */
export function BookingTimeline({ steps }: { steps: TimelineStep[] }) {
  const { colors, spacing, type } = useTheme();

  return (
    <View>
      {steps.map((step, index) => {
        const isLast = index === steps.length - 1;
        const iconColor = step.failed
          ? colors.danger
          : step.done
            ? colors.success
            : step.active
              ? colors.tint
              : colors.border;
        const icon: keyof typeof Ionicons.glyphMap = step.failed
          ? 'close-circle'
          : step.done
            ? 'checkmark-circle'
            : step.active
              ? 'ellipse'
              : 'ellipse-outline';

        return (
          <View key={`${step.label}-${index}`} style={styles.timelineRow}>
            <View style={styles.timelineGutter}>
              <Ionicons name={icon} size={20} color={iconColor} />
              {!isLast ? (
                <View
                  style={{
                    flex: 1,
                    width: 2,
                    backgroundColor: step.done ? colors.success : colors.border,
                    marginVertical: 2,
                  }}
                />
              ) : null}
            </View>
            <View style={{ flex: 1, paddingBottom: isLast ? 0 : spacing.lg }}>
              <Text
                style={[
                  step.active || step.failed ? type.bodyStrong : type.body,
                  { color: step.active || step.failed ? colors.text : colors.mutedText },
                ]}>
                {step.label}
              </Text>
              {step.detail ? (
                <Text style={[type.caption, { color: colors.mutedText, marginTop: 2 }]}>{step.detail}</Text>
              ) : null}
            </View>
          </View>
        );
      })}
    </View>
  );
}

/**
 * The honest arrival panel.
 *
 * An arrival promise only exists after a partner has accepted. Showing a fabricated
 * estimate before then would violate the PDF's honest-ETA rule, so the absent case is
 * explicit and says what is happening instead.
 */
export function PromiseWindow({
  status,
  promiseStart,
  promiseEnd,
  partnerName,
  isStaleLocation,
}: {
  status: BookingStatus;
  promiseStart: string | null;
  promiseEnd: string | null;
  partnerName: string | null;
  isStaleLocation?: boolean;
}) {
  const { colors, spacing, type } = useTheme();

  if (!promiseStart) {
    return (
      <View style={{ marginBottom: spacing.md }}>
        <Text style={[type.captionStrong, { color: colors.mutedText }]}>Arrival window</Text>
        <Text style={[type.body, { color: colors.text, marginTop: 4 }]}>
          {status === 'dispatching' || status === 'quote_accepted'
            ? 'Finding a partner near you. Your arrival window is confirmed once a partner accepts.'
            : 'No arrival window has been confirmed yet.'}
        </Text>
      </View>
    );
  }

  return (
    <View style={{ marginBottom: spacing.md }}>
      <Text style={[type.captionStrong, { color: colors.mutedText }]}>Arrival window</Text>
      <View style={[styles.promiseRow, { marginTop: 4 }]}>
        <Ionicons name="time-outline" size={18} color={colors.tint} style={styles.promiseIcon} />
        <Text style={[type.bodyStrong, { color: colors.text, flex: 1 }]}>
          {formatPromise(promiseStart, promiseEnd)}
        </Text>
      </View>
      {partnerName ? (
        <Text style={[type.caption, { color: colors.mutedText, marginTop: 4 }]}>
          Partner: {partnerName}
        </Text>
      ) : null}
      {isStaleLocation ? (
        <Text style={[type.caption, { color: colors.warning, marginTop: 4 }]}>
          This window was set some time ago and may have moved. We will update you if it does.
        </Text>
      ) : null}
    </View>
  );
}

function formatPromise(start: string, end: string | null): string {
  const startDate = new Date(start);
  if (!end) {
    return startDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  const fmt = (value: string) =>
    new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return `${fmt(start)} – ${fmt(end)}`;
}

/** Compact one-line summary used on list rows. */
export function BookingStatusLine({
  status,
  detail,
}: {
  status: BookingStatus;
  detail?: string;
}) {
  const { colors, spacing, type } = useTheme();
  const tone = isExceptionStatus(status) ? colors.danger : isTerminalStatus(status) ? colors.mutedText : colors.text;

  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm }}>
      <Text style={[type.captionStrong, { color: tone }]}>{STATUS_LABELS[status] ?? status}</Text>
      {detail ? <Text style={[type.caption, { color: colors.mutedText }]}>{detail}</Text> : null}
    </View>
  );
}

export { DetailRow };

const styles = StyleSheet.create({
  track: { height: 6, width: '100%', overflow: 'hidden' },
  captionRow: { flexDirection: 'row', justifyContent: 'space-between' },
  timelineRow: { flexDirection: 'row' },
  timelineGutter: { alignItems: 'center', width: 28 },
  promiseRow: { flexDirection: 'row', alignItems: 'center' },
  promiseIcon: { marginRight: 6 },
});

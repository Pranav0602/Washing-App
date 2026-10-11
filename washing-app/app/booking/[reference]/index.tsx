/**
 * Booking tracking.
 *
 * The customer's single source of truth for a job: live status, honest arrival window,
 * the append-only event history, photo evidence, and the actions available to them
 * right now. The action list is driven by the server's `allowed_transitions`, so the app
 * can never offer an action the backend would reject.
 */

import { useCallback, useMemo, useState } from 'react';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { Image, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';

import { bookingApi, evidenceApi } from '@/api/endpoints';
import { bookingKeys } from '@/query/keys';
import { useSession } from '@/auth/SessionProvider';
import {
  formatDateTime,
  formatMoney,
  formatRelative,
  formatWindow,
  isTerminalStatus,
} from '@/lib/format';
import { ArrivalCountdown } from '@/components/booking/ArrivalCountdown';
import { SatisfactionGate } from '@/components/booking/SatisfactionGate';
import { PaymentGatewayModal } from '@/components/payment/PaymentGatewayModal';
import {
  BookingProgress,
  BookingTimeline,
  PromiseWindow,
  StatusBadge,
  type TimelineStep
} from '@/components/booking/BookingStatus';
import {
  Banner,
  Button,
  Card,
  DetailRow,
  Divider,
  EmptyState,
  ErrorState,
  LoadingState,
  SectionTitle,
} from '@/components/ui';
import { useTheme } from '@/theme';

export default function BookingDetailScreen() {
  const { reference } = useLocalSearchParams<{ reference: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors, spacing, type } = useTheme();
  const queryClient = useQueryClient();
  // A partner follows an offer into this screen and ops opens it from the job board,
  // so "my booking" is not always true here. The customer-only actions below are
  // gated on the role, because the API's `can_cancel` only reflects booking status.
  const { isCustomer } = useSession();
  const [paymentOpen, setPaymentOpen] = useState(false);

  const bookingQuery = useQuery({
    queryKey: bookingKeys.detail(reference ?? ''),
    queryFn: () => bookingApi.get(reference!),
    enabled: Boolean(reference),
    // Keep a live job fresh without hammering the API.
    refetchInterval: 20_000
  });

  const eventsQuery = useQuery({
    queryKey: bookingKeys.events(reference ?? ''),
    queryFn: () => bookingApi.events(reference!),
    enabled: Boolean(reference)
  });

  const evidenceQuery = useQuery({
    queryKey: bookingKeys.evidence(reference ?? ''),
    queryFn: () => evidenceApi.list(reference!),
    enabled: Boolean(reference)
  });

  const cancel = useMutation({
    mutationFn: () => bookingApi.cancel(reference!, 'customer_request'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: bookingKeys.root })
  });

  const rate = useMutation({
    mutationFn: (rating: number) => bookingApi.rate(reference!, rating),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: bookingKeys.root })
  });

  const booking = bookingQuery.data;

  const onRefresh = useCallback(() => {
    void bookingQuery.refetch();
    void eventsQuery.refetch();
  }, [bookingQuery, eventsQuery]);

  const timelineSteps = useMemo<TimelineStep[]>(() => {
    if (!booking) return [];
    const failed = isTerminalStatus(booking.status) && booking.status !== 'partner_payout_eligible';

    return [
      {
        label: 'Booking confirmed',
        detail: booking.created_at ? formatDateTime(booking.created_at) : undefined,
        done: true
      },
      {
        label: 'Finding a partner',
        detail: booking.assigned_at
          ? `Assigned ${formatRelative(booking.assigned_at)}`
          : 'Searching for a vetted partner near you',
        done: Boolean(booking.assigned_at),
        active: !booking.assigned_at,
        failed: failed && !booking.assigned_at
      },
      {
        label: 'Partner on the way',
        detail: booking.en_route_at ? formatDateTime(booking.en_route_at) : undefined,
        done: Boolean(booking.en_route_at),
        active: booking.status === 'en_route'
      },
      {
        label: 'Arrived',
        detail: booking.arrived_at ? formatDateTime(booking.arrived_at) : undefined,
        done: Boolean(booking.arrived_at),
        active: booking.status === 'arrived'
      },
      {
        label: 'Wash in progress',
        detail: booking.started_at ? formatDateTime(booking.started_at) : undefined,
        done: Boolean(booking.started_at),
        active: booking.status === 'in_service'
      },
      {
        label: 'Completed',
        detail: booking.completed_at ? formatDateTime(booking.completed_at) : undefined,
        done: Boolean(booking.completed_at),
        active: booking.status === 'completed',
        failed: failed && booking.cancelled_at !== null
      },
      {
        label: 'Payment taken',
        detail: booking.captured_minor
          ? formatMoney(booking.captured_minor, booking.currency)
          : undefined,
        done: booking.captured_minor > 0,
        active: booking.status === 'payment_captured'
      },
    ];
  }, [booking]);

  if (bookingQuery.isLoading) {
    return <FullScreen><LoadingState label="Loading your booking" /></FullScreen>;
  }

  if (bookingQuery.isError || !booking) {
    return (
      <FullScreen>
        <ErrorState
          error={bookingQuery.error}
          onRetry={onRefresh}
          title="Could not load this booking"
        />
      </FullScreen>
    );
  }

  return (
    <ScrollView
      testID="booking-detail-screen"
      style={{ flex: 1, backgroundColor: colors.background }}
      contentContainerStyle={{
        padding: spacing.lg,
        paddingTop: insets.top + spacing.md,
        paddingBottom: insets.bottom + spacing.xl
      }}
      refreshControl={
        <RefreshControl refreshing={bookingQuery.isRefetching} onRefresh={onRefresh} tintColor={colors.tint} />
      }>
      <View style={styles.rowBetween}>
        <View style={{ flex: 1 }}>
          <Text style={[type.title, { color: colors.text }]}>{booking.service_name}</Text>
          <Text style={[type.caption, { color: colors.mutedText, marginTop: 2 }]}>
            {booking.reference}
          </Text>
        </View>
        <StatusBadge status={booking.status} />
      </View>

      <View style={{ height: spacing.lg }} />
      <BookingProgress status={booking.status} />

      {booking.booking_mode === 'on_demand' &&
      !isTerminalStatus(booking.status) &&
      booking.status !== 'completed' &&
      booking.status !== 'payment_captured' &&
      booking.status !== 'partner_payout_eligible' ? (
        <View style={{ marginTop: spacing.lg }}>
          <ArrivalCountdown createdAt={booking.created_at} status={booking.status} />
        </View>
      ) : null}

      {isCustomer && booking.status === 'completed' && booking.payment_state !== 'captured' ? (
        <View style={{ marginTop: spacing.lg }}>
          <SatisfactionGate
            bookingReference={booking.reference}
            evidence={evidenceQuery.data ?? []}
            onSatisfied={() => setPaymentOpen(true)}
          />
        </View>
      ) : null}

      <PaymentGatewayModal
        visible={paymentOpen}
        onClose={() => setPaymentOpen(false)}
        bookingReference={booking.reference}
        currency={booking.currency}
        items={[{ label: booking.service_name, amountMinor: booking.subtotal_minor }]}
        subtotalMinor={booking.subtotal_minor}
        taxAndFeeMinor={booking.tax_minor + booking.fee_minor}
        totalMinor={booking.total_minor}
      />

      {booking.cancelled_at ? (
        <Banner
          testID="cancelled-banner"
          tone="danger"
          title="This booking was cancelled"
          message={booking.cancel_reason || 'No reason recorded.'}
        />
      ) : null}

      {booking.is_arrival_late ? (
        <Banner
          testID="late-banner"
          tone="warning"
          title="Running late"
          message="Your partner is past the promised window. We have alerted our team."
        />
      ) : null}

      <Card>
        <PromiseWindow
          status={booking.status}
          promiseStart={booking.promise_window_start}
          promiseEnd={booking.promise_window_end}
          partnerName={booking.partner?.display_name ?? null}
        />
        <Divider />
        <DetailRow label="Vehicle" value={booking.vehicle.display_name} />
        <DetailRow label="Where" value={booking.address.line1} />
        <DetailRow label="Scheduled" value={formatWindow(booking.scheduled_start, booking.window_end)} />
        {booking.partner ? (
          <>
            <DetailRow
              label="Partner"
              value={`${booking.partner.display_name} (${booking.partner.rating_avg.toFixed(1)})`}
            />
            {/* The masked relay number is the only contact detail ever shown. */}
            <DetailRow label="Contact" value={booking.partner.masked_phone} />
          </>
        ) : null}
      </Card>

      <SectionTitle>Timeline</SectionTitle>
      <Card>
        <BookingTimeline steps={timelineSteps} />
      </Card>

      <SectionTitle>Photos</SectionTitle>
      {evidenceQuery.isLoading ? (
        <LoadingState label="Loading photos" />
      ) : (evidenceQuery.data ?? []).length === 0 ? (
        <EmptyState
          testID="no-evidence"
          title="No photos yet"
          message="Your partner photographs the car before and after the wash."
          icon="camera-outline"
        />
      ) : (
        <View style={styles.photoGrid}>
          {(evidenceQuery.data ?? []).map((evidence) => (
            <View key={evidence.id} style={styles.photoCell} testID={`evidence-${evidence.id}`}>
              {evidence.file_url ? (
                <Image
                  source={{ uri: `${process.env.EXPO_PUBLIC_API_URL ?? ''}${evidence.file_url}` }}
                  style={styles.photo}
                  accessibilityLabel={`${evidence.evidence_type_label} photo`}
                  resizeMode="cover"
                />
              ) : (
                <View style={[styles.photo, styles.photoPlaceholder]}>
                  <Ionicons name="image-outline" size={24} color={colors.icon} />
                </View>
              )}
              <Text style={[type.caption, { color: colors.mutedText, marginTop: 4 }]}>
                {evidence.evidence_type_label}
              </Text>
              {evidence.legal_hold ? (
                <Text style={[type.caption, { color: colors.warning }]}>Under review</Text>
              ) : null}
            </View>
          ))}
        </View>
      )}

      <SectionTitle>Payment</SectionTitle>
      <Card>
        <DetailRow
          label="Total"
          value={formatMoney(booking.total_minor, booking.currency)}
          emphasis
        />
        {booking.captured_minor ? (
          <DetailRow
            label="Paid"
            value={formatMoney(booking.captured_minor, booking.currency)}
            tone="success"
          />
        ) : null}
        {booking.refunded_minor ? (
          <DetailRow
            label="Refunded"
            value={`- ${formatMoney(booking.refunded_minor, booking.currency)}`}
            tone="danger"
          />
        ) : null}
        <DetailRow label="State" value={booking.payment_state_label} />
      </Card>

      <SectionTitle>Actions</SectionTitle>

      <View style={{ gap: spacing.sm }}>
        {isCustomer && booking.can_cancel ? (
          <Button
            testID="cancel-booking"
            label="Cancel this booking"
            variant="danger"
            onPress={() => cancel.mutate()}
            loading={cancel.isPending}
          />
        ) : null}

        {isCustomer ? (
          <Button
            testID="report-issue"
            label="Report an issue or damage"
            variant="secondary"
            onPress={() => router.push(`/booking/${reference}/report`)}
          />
        ) : null}

        <Button
          testID="open-chat"
          label={isCustomer ? 'Message my partner' : 'Open message thread'}
          variant="secondary"
          onPress={() => router.push(`/booking/${reference}/comms`)}
        />

        {isCustomer &&
        (booking.status === 'completed' || booking.status === 'payment_captured') &&
        booking.rating === null ? (
          <Card testID="rating-card">
            <Text style={[type.bodyStrong, { color: colors.text, marginBottom: spacing.sm }]}>
              How did we do?
            </Text>
            <View style={styles.rowBetween}>
              {[1, 2, 3, 4, 5].map((value) => (
                <Button
                  key={value}
                  testID={`rate-${value}`}
                  label={String(value)}
                  variant="secondary"
                  fullWidth={false}
                  onPress={() => rate.mutate(value)}
                  style={{ marginHorizontal: 2 }}
                />
              ))}
            </View>
          </Card>
        ) : null}

        {isCustomer && booking.rating !== null ? (
          <Text style={[type.caption, { color: colors.success, textAlign: 'center' }]}>
            You rated this booking {booking.rating}/5. Thank you.
          </Text>
        ) : null}
      </View>

      <SectionTitle>History</SectionTitle>
      <Card>
        {(eventsQuery.data ?? []).length === 0 ? (
          <Text style={[type.caption, { color: colors.mutedText }]}>No events recorded.</Text>
        ) : (
          (eventsQuery.data ?? [])
            // The API returns events oldest-first (ordered by seq). Take the last 12
            // *before* reversing, otherwise this shows the 12 oldest events and hides
            // the most recent ones.
            .slice(-12)
            .reverse()
            .map((event) => (
              <DetailRow
                key={`${event.seq}-${event.event_type}`}
                label={event.event_type.replace(/[._]/g, ' ')}
                value={formatDateTime(event.occurred_at)}
              />
            ))
        )}
      </Card>
    </ScrollView>
  );
}

function FullScreen({ children }: { children: React.ReactNode }) {
  const insets = useSafeAreaInsets();
  const { colors, spacing } = useTheme();
  return (
    <View
      style={{
        flex: 1,
        backgroundColor: colors.background,
        padding: spacing.lg,
        paddingTop: insets.top + spacing.md
      }}>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  rowBetween: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  photoGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  photoCell: { width: '47%' },
  photo: { width: '100%', aspectRatio: 1, borderRadius: 12 },
  photoPlaceholder: { alignItems: 'center', justifyContent: 'center' }
});

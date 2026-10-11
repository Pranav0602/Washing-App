/**
 * Customer home.
 *
 * Leads with the one thing that matters: if a job is running right now, its status
 * and arrival window are above everything else. When nothing is active, the next
 * booking takes that position.
 */

import { useCallback } from 'react';
import { useRouter } from 'expo-router';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { bookingApi } from '@/api/endpoints';
import { bookingKeys } from '@/query/keys';
import { usePolling } from '@/hooks';
import { useSession } from '@/auth/SessionProvider';
import { formatRelative, isTerminalStatus } from '@/lib/format';
import { PromiseWindow, StatusBadge } from '@/components/booking/BookingStatus';
import { PriceTotal } from '@/components/booking/PriceBreakdown';
import {
  Banner,
  Button,
  Card,
  EmptyState,
  ErrorState,
  SectionTitle,
  SkeletonList,
} from '@/components/ui';
import { useTheme } from '@/theme';

export default function CustomerHomeScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors, spacing, type } = useTheme();
  const { user } = useSession();

  const bookingsQuery = useQuery({
    queryKey: bookingKeys.list({ active: true }),
    queryFn: () => bookingApi.list({ active: true }),
  });

  // Poll only while something is genuinely in progress. Push covers the rest, and an
  // idle screen should not keep the radio on.
  const hasActive = (bookingsQuery.data?.results ?? []).some(
    (booking) => !isTerminalStatus(booking.status),
  );
  usePolling(
    useCallback(() => {
      void bookingsQuery.refetch();
    }, [bookingsQuery]),
    20_000,
    hasActive,
  );

  const bookings = bookingsQuery.data?.results ?? [];
  // The job furthest along its journey is the one the customer cares about.
  const liveBooking = bookings
    .filter((booking) => ['assigned', 'en_route', 'arrived', 'in_service'].includes(booking.status))
    .sort((a, b) => (a.scheduled_start ?? '').localeCompare(b.scheduled_start ?? ''))[0];
  const upcoming = bookings.filter((booking) => booking !== liveBooking);

  const onRefresh = useCallback(() => {
    void bookingsQuery.refetch();
  }, [bookingsQuery]);

  return (
    <ScrollView
      testID="customer-home"
      style={{ flex: 1, backgroundColor: colors.background }}
      contentContainerStyle={{
        padding: spacing.lg,
        paddingTop: insets.top + spacing.md,
        paddingBottom: insets.bottom + spacing.xl,
      }}
      refreshControl={
        <RefreshControl refreshing={bookingsQuery.isRefetching} onRefresh={onRefresh} tintColor={colors.tint} />
      }>
      <Text style={[type.title, { color: colors.text }]}>
        {user?.full_name ? `Hello, ${user.full_name.split(' ')[0]}` : 'Hello'}
      </Text>
      <Text style={[type.caption, { color: colors.mutedText, marginTop: 4 }]}>
        Now serving every address across Pune, India.
      </Text>

      <View style={{ height: spacing.lg }} />

      {bookingsQuery.isLoading ? (
        <SkeletonList count={2} />
      ) : bookingsQuery.isError ? (
        <ErrorState error={bookingsQuery.error} onRetry={onRefresh} title="Could not load your bookings" />
      ) : liveBooking ? (
        <LiveJobCard
          booking={liveBooking}
          onPress={() => router.push(`/booking/${liveBooking.reference}`)}
        />
      ) : (
        <>
          <Banner
            testID="no-active-booking"
            tone="info"
            title="No wash in progress"
            message="Book a wash and we will find a partner near you."
          />
          <Button
            testID="book-a-wash"
            label="Book a wash"
            icon="add-circle-outline"
            onPress={() => router.push('/booking/quote')}
          />
        </>
      )}

      {upcoming.length > 0 ? (
        <>
          <View style={{ height: spacing.lg }} />
          <SectionTitle>Your other bookings</SectionTitle>
          {upcoming.map((booking) => (
            <Card
              key={booking.reference}
              testID={`upcoming-${booking.reference}`}>
              <View style={styles.rowBetween}>
                <Text style={[type.bodyStrong, { color: colors.text, flex: 1 }]}>
                  {booking.service_name}
                </Text>
                <StatusBadge status={booking.status} />
              </View>
              <Text style={[type.caption, { color: colors.mutedText, marginTop: 4 }]}>
                {booking.reference} · {booking.vehicle_name}
              </Text>
              <View style={[styles.rowBetween, { marginTop: spacing.md }]}>
                <PriceTotal amountMinor={booking.total_minor} currency={booking.currency} />
                <Button
                  testID={`open-${booking.reference}`}
                  label="View"
                  variant="secondary"
                  fullWidth={false}
                  onPress={() => router.push(`/booking/${booking.reference}`)}
                />
              </View>
            </Card>
          ))}
        </>
      ) : null}

      {bookings.length === 0 && !bookingsQuery.isLoading && !bookingsQuery.isError ? (
        <EmptyState
          testID="empty-bookings"
          title="Nothing booked yet"
          message="Your bookings and their live status will appear here."
          icon="car-sport-outline"
          action={{ label: 'Book a wash', onPress: () => router.push('/booking/quote') }}
        />
      ) : null}
    </ScrollView>
  );
}

function LiveJobCard({
  booking,
  onPress,
}: {
  booking: {
    reference: string;
    status: Parameters<typeof StatusBadge>[0]['status'];
    service_name: string;
    partner_name: string | null;
    promise_window_start: string | null;
    promise_window_end: string | null;
    created_at: string;
    currency: string;
    total_minor: number;
  };
  onPress: () => void;
}) {
  const { colors, spacing, type } = useTheme();

  return (
    <Card testID="live-job">
      <View style={styles.rowBetween}>
        <Text style={[type.heading, { color: colors.text, flex: 1 }]}>Your wash is in progress</Text>
        <StatusBadge status={booking.status} />
      </View>

      <PromiseWindow
        status={booking.status}
        promiseStart={booking.promise_window_start}
        promiseEnd={booking.promise_window_end}
        partnerName={booking.partner_name}
      />

      <View style={[styles.rowBetween, { marginTop: spacing.sm }]}>
        <Text style={[type.caption, { color: colors.mutedText }]}>
          {booking.service_name} · booked {formatRelative(booking.created_at)}
        </Text>
      </View>

      <View style={{ marginTop: spacing.md }}>
        <Button
          testID="track-job"
          label="Track this wash"
          onPress={onPress}
          accessibilityHint="Opens the booking timeline"
        />
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  rowBetween: { flexDirection: 'row', alignItems: 'center', gap: 8 },
});

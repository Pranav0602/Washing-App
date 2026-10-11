/**
 * Booking list.
 *
 * Filterable by state, because the PDF's fulfilment metrics depend on customers being
 * able to distinguish "running now" from "finished" and "stopped".
 */

import { useCallback, useMemo, useState } from 'react';
import { useRouter } from 'expo-router';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { bookingApi } from '@/api/endpoints';
import { bookingKeys } from '@/query/keys';
import { formatDateTime, isTerminalStatus } from '@/lib/format';
import { StatusBadge } from '@/components/booking/BookingStatus';
import { PriceTotal } from '@/components/booking/PriceBreakdown';
import {
  Button,
  ChipGroup,
  EmptyState,
  ErrorState,
  PressableCard,
  SkeletonList,
} from '@/components/ui';
import { useTheme } from '@/theme';

type Filter = 'all' | 'active' | 'completed';

export default function BookingsScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors, spacing, type } = useTheme();
  const [filter, setFilter] = useState<Filter>('all');

  const queryKey = useMemo(() => {
    if (filter === 'active') return bookingKeys.list({ active: true });
    if (filter === 'completed') return bookingKeys.list({ status: 'completed' });
    return bookingKeys.list({});
  }, [filter]);

  const query = useQuery({
    queryKey,
    queryFn: () =>
      bookingApi.list(
        filter === 'active'
          ? { active: true }
          : filter === 'completed'
            ? { status: 'completed' }
            : {},
      ),
  });

  const onRefresh = useCallback(() => {
    void query.refetch();
  }, [query]);

  const bookings = query.data?.results ?? [];

  return (
    <ScrollView
      testID="bookings-screen"
      style={{ flex: 1, backgroundColor: colors.background }}
      contentContainerStyle={{
        padding: spacing.lg,
        paddingTop: insets.top + spacing.md,
        paddingBottom: insets.bottom + spacing.xl,
      }}
      refreshControl={
        <RefreshControl refreshing={query.isRefetching} onRefresh={onRefresh} tintColor={colors.tint} />
      }>
      <Text style={[type.title, { color: colors.text }]}>Your bookings</Text>
      <Text style={[type.body, { color: colors.mutedText, marginTop: spacing.xs }]}>
        Live status, arrival windows and photo evidence.
      </Text>

      <View style={{ height: spacing.lg }} />

      <ChipGroup
        options={[
          { value: 'all', label: 'All' },
          { value: 'active', label: 'Active' },
          { value: 'completed', label: 'Completed' },
        ]}
        value={filter}
        onChange={(value) => setFilter(value as Filter)}
        testID="booking-filter"
      />

      <View style={{ height: spacing.lg }} />

      {query.isLoading ? (
        <SkeletonList count={3} />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={onRefresh} title="Could not load your bookings" />
      ) : bookings.length === 0 ? (
        <EmptyState
          testID="no-bookings"
          title={filter === 'active' ? 'Nothing in progress' : 'No bookings yet'}
          message={
            filter === 'active'
              ? 'When you book a wash it will show here with live status.'
              : 'Book your first wash and it will appear here.'
          }
          icon="calendar-outline"
          action={{ label: 'Book a wash', onPress: () => router.push('/booking/quote') }}
        />
      ) : (
        bookings.map((booking) => (
          <PressableCard
            key={booking.reference}
            testID={`booking-${booking.reference}`}
            onPress={() => router.push(`/booking/${booking.reference}`)}
            accessibilityLabel={`${booking.service_name}, ${booking.status_label}`}
            accessibilityHint="Opens the booking timeline">
            <View style={styles.rowBetween}>
              <Text style={[type.bodyStrong, { color: colors.text, flex: 1 }]}>
                {booking.service_name}
              </Text>
              <StatusBadge status={booking.status} />
            </View>

            <Text style={[type.caption, { color: colors.mutedText, marginTop: 4 }]}>
              {booking.reference} · {booking.vehicle_name}
            </Text>

            <Text style={[type.caption, { color: colors.mutedText, marginTop: 2 }]}>
              {booking.scheduled_start
                ? `Scheduled ${formatDateTime(booking.scheduled_start)}`
                : isTerminalStatus(booking.status)
                  ? booking.status_label
                  : 'Scheduling'}
            </Text>

            <View style={[styles.rowBetween, { marginTop: spacing.md }]}>
              <PriceTotal amountMinor={booking.total_minor} currency={booking.currency} />
              <Text style={[type.caption, { color: colors.tint }]}>View details</Text>
            </View>
          </PressableCard>
        ))
      )}

      <Button
        testID="book-from-list"
        label="Book another wash"
        icon="add-circle-outline"
        variant="secondary"
        onPress={() => router.push('/booking/quote')}
        style={{ marginTop: spacing.lg }}
      />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  rowBetween: { flexDirection: 'row', alignItems: 'center', gap: 8 },
});

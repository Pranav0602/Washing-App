/**
 * Booking confirmation.
 *
 * Zero upfront charging: the customer commits with $0 charged now. Payment only
 * activates after the wash is completed and the customer confirms satisfaction.
 */

import { useState } from 'react';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { ScrollView, Text, View } from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { bookingApi, quoteApi } from '@/api/endpoints';
import { bookingKeys, quoteKeys } from '@/query/keys';
import { formatWindow } from '@/lib/format';
import { PriceBreakdown } from '@/components/booking/PriceBreakdown';
import {
  Banner,
  Button,
  Card,
  ErrorState,
  LoadingState,
  SectionTitle,
} from '@/components/ui';
import { useTheme } from '@/theme';

export default function BookingConfirmScreen() {
  const { quoteId } = useLocalSearchParams<{ quoteId: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors, spacing, type } = useTheme();
  const queryClient = useQueryClient();

  const [createError, setCreateError] = useState<unknown>(null);

  const quoteQuery = useQuery({
    queryKey: quoteKeys.detail(quoteId ?? ''),
    queryFn: () => quoteApi.get(quoteId!),
    enabled: Boolean(quoteId),
  });

  const createBooking = useMutation({
    mutationFn: () => bookingApi.create(quoteId!, true),
    onSuccess: (booking) => {
      void queryClient.invalidateQueries({ queryKey: bookingKeys.root });
      router.replace(`/booking/${booking.reference}`);
    },
    onError: setCreateError,
  });

  const quote = quoteQuery.data;
  const canProceed = quote ? !quote.is_expired : false;

  if (quoteQuery.isLoading) {
    return <FullScreen><LoadingState label="Loading your booking" /></FullScreen>;
  }

  if (quoteQuery.isError || !quote) {
    return (
      <FullScreen>
        <ErrorState
          error={quoteQuery.error}
          onRetry={() => void quoteQuery.refetch()}
          title="Could not load this quote"
        />
      </FullScreen>
    );
  }

  return (
    <ScrollView
      testID="booking-confirm-screen"
      style={{ flex: 1, backgroundColor: colors.background }}
      contentContainerStyle={{
        padding: spacing.lg,
        paddingTop: insets.top + spacing.md,
        paddingBottom: insets.bottom + spacing.xl,
      }}>
      <Text style={[type.title, { color: colors.text }]}>Book your wash</Text>

      <Banner
        testID="zero-upfront-notice"
        tone="info"
        title="No payment now"
        message="No upfront payment. You will only be charged after the wash is completed to your satisfaction."
      />

      <Card>
        <Text style={[type.bodyStrong, { color: colors.text }]}>{quote.service_name}</Text>
        <Text style={[type.caption, { color: colors.mutedText, marginTop: 2 }]}>
          {quote.vehicle_name} ·{' '}
          {quote.booking_mode === 'on_demand'
            ? 'On-demand · partner arrives within 10 minutes'
            : formatWindow(quote.window_start, quote.window_end)}
        </Text>
      </Card>

      <Card>
        <PriceBreakdown quote={quote} />
      </Card>

      <SectionTitle>How it works</SectionTitle>
      <Card>
        <Text style={[type.caption, { color: colors.mutedText }]}>
          We dispatch the nearest partner immediately and they aim to reach your car within
          10 minutes. After the wash, you inspect the result and only then pay for what you
          selected. If a partner does not arrive, you owe nothing.
        </Text>
      </Card>

      {createError ? (
        <ErrorState
          testID="create-booking-error"
          error={createError}
          onRetry={() => setCreateError(null)}
          title="Could not create the booking"
        />
      ) : null}

      <View style={{ marginTop: spacing.lg }}>
        <Button
          testID="create-booking"
          label="Confirm Booking (Arrives in 10 mins)"
          onPress={() => createBooking.mutate()}
          loading={createBooking.isPending}
          disabled={!canProceed}
        />
      </View>
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
        paddingTop: insets.top + spacing.md,
      }}>
      {children}
    </View>
  );
}

/**
 * Quote review.
 *
 * Shows the full itemisation, expected duration, inclusions, exclusions and the
 * expiry before any payment is authorised. The PDF requires all of this to be visible
 * before the customer commits.
 */

import { useState } from 'react';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { RefreshControl, ScrollView, Text, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { quoteApi } from '@/api/endpoints';
import { quoteKeys } from '@/query/keys';
import { formatDuration, formatRelative, formatWindow } from '@/lib/format';
import { PriceBreakdown } from '@/components/booking/PriceBreakdown';
import {
  Banner,
  BulletList,
  Button,
  Card,
  ErrorState,
  LoadingState,
  SectionTitle,
} from '@/components/ui';
import { useTheme } from '@/theme';

export default function QuoteReviewScreen() {
  const { quoteId } = useLocalSearchParams<{ quoteId: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors, spacing, type } = useTheme();
  const [acceptError, setAcceptError] = useState<unknown>(null);
  const [isAccepting, setIsAccepting] = useState(false);

  const quoteQuery = useQuery({
    queryKey: quoteKeys.detail(quoteId ?? ''),
    queryFn: () => quoteApi.get(quoteId!),
    enabled: Boolean(quoteId),
  });

  const quote = quoteQuery.data;

  const onAccept = async () => {
    if (!quote) return;
    setIsAccepting(true);
    setAcceptError(null);
    try {
      const accepted = await quoteApi.accept(quote.id, '2026-10-01');
      router.push({
        pathname: '/booking/confirm',
        params: { quoteId: accepted.id },
      });
    } catch (error) {
      setAcceptError(error);
    } finally {
      setIsAccepting(false);
    }
  };

  if (quoteQuery.isLoading) {
    return (
      <ScreenWrapper>
        <LoadingState label="Loading your price" />
      </ScreenWrapper>
    );
  }

  if (quoteQuery.isError || !quote) {
    return (
      <ScreenWrapper>
        <ErrorState
          error={quoteQuery.error}
          onRetry={() => void quoteQuery.refetch()}
          title="Could not load this quote"
        />
      </ScreenWrapper>
    );
  }

  return (
    <ScrollView
      testID="quote-review-screen"
      style={{ flex: 1, backgroundColor: colors.background }}
      contentContainerStyle={{
        padding: spacing.lg,
        paddingTop: insets.top + spacing.md,
        paddingBottom: insets.bottom + spacing.xl,
      }}
      refreshControl={
        <RefreshControl
          refreshing={quoteQuery.isRefetching}
          onRefresh={() => void quoteQuery.refetch()}
          tintColor={colors.tint}
        />
      }>
      <Text style={[type.title, { color: colors.text }]}>Your price</Text>

      {quote.is_expired || quote.status === 'expired' ? (
        <Banner
          testID="quote-expired-banner"
          tone="warning"
          title="This price has expired"
          message="Prices are held for a short window. Go back and request a fresh quote."
          action={{ label: 'Start again', onPress: () => router.replace('/booking/quote') }}
        />
      ) : (
        <Banner
          testID="quote-expiry"
          tone="info"
          message={`This price is held until it expires ${formatRelative(quote.expires_at)}.`}
        />
      )}

      <Card testID="quote-summary">
        <Text style={[type.bodyStrong, { color: colors.text }]}>{quote.service_name}</Text>
        <Text style={[type.caption, { color: colors.mutedText, marginTop: 2 }]}>
          {quote.vehicle_name} · {quote.zone_code}
        </Text>
        <Text style={[type.caption, { color: colors.mutedText, marginTop: 2 }]}>
          {quote.booking_mode === 'on_demand'
            ? 'On-demand · partner arrives within 10 minutes'
            : formatWindow(quote.window_start, quote.window_end)}
        </Text>
        <Text style={[type.caption, { color: colors.mutedText, marginTop: 2 }]}>
          Expected duration {formatDuration(quote.expected_duration_minutes)}
        </Text>
      </Card>

      <Card>
        <PriceBreakdown quote={quote} />
      </Card>

      <SectionTitle>What is included</SectionTitle>
      <Card>
        <BulletList title="Included" items={quote.inclusions} />
        <BulletList title="Not included" items={quote.exclusions} tone="muted" />
      </Card>

      <SectionTitle>Arrival</SectionTitle>
      <View style={{ marginBottom: spacing.lg }}>
        <Text style={[type.body, { color: colors.text }]}>
          On-demand service: the nearest available partner reaches your car within 10
          minutes of booking.
        </Text>
      </View>

      <Banner
        testID="no-upfront-notice"
        tone="info"
        title="No upfront payment"
        message="You will only be charged after the wash is completed to your satisfaction."
      />

      {acceptError ? (
        <ErrorState
          testID="accept-error"
          error={acceptError}
          onRetry={() => setAcceptError(null)}
          title="Could not accept this price"
        />
      ) : null}

      <Button
        testID="accept-quote"
        label="Book Wash (Partner arriving in 10 mins)"
        onPress={onAccept}
        loading={isAccepting}
        disabled={quote.is_expired}
        accessibilityHint="Accepts the terms and continues to booking"
      />

      <View style={{ marginTop: spacing.sm }}>
        <Button
          testID="decline-quote"
          label="Choose something else"
          variant="ghost"
          onPress={() => router.replace('/booking/quote')}
        />
      </View>
    </ScrollView>
  );
}

function ScreenWrapper({ children }: { children: React.ReactNode }) {
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

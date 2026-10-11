/**
 * Partner home: shift state, the live offer feed, and readiness blockers.
 *
 * The readiness panel and the visible on/off-duty location state are deliberate: the
 * PDF requires a partner to understand exactly why they are not receiving offers, and
 * requires precise location to be collected only in a declared context.
 */

import { useCallback, useState } from 'react';
import { useRouter } from 'expo-router';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { dispatchApi, partnerApi } from '@/api/endpoints';
import type { DispatchOffer } from '@/api/types';
import { bookingKeys, dispatchKeys, partnerKeys } from '@/query/keys';
import { formatCountdown, formatDistance, formatMoney } from '@/lib/format';
import { useCountdown } from '@/hooks';
import { Banner, Button, Card, EmptyState, ErrorState, SectionTitle, SkeletonList } from '@/components/ui';
import { useTheme } from '@/theme';

export default function PartnerHomeScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors, spacing, type } = useTheme();
  const queryClient = useQueryClient();
  const [actionError, setActionError] = useState<unknown>(null);

  const meQuery = useQuery({ queryKey: partnerKeys.me, queryFn: partnerApi.me });

  const offersQuery = useQuery({
    queryKey: dispatchKeys.offers,
    queryFn: () => dispatchApi.offers(),
    // Offers expire in about two minutes, so a live feed has to refresh often.
    refetchInterval: 15_000,
  });

  const availability = useMutation({
    mutationFn: (on: boolean) => partnerApi.setAvailability({ action: on ? 'start' : 'end' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: partnerKeys.me }),
    onError: setActionError,
  });

  const onRefresh = useCallback(() => {
    void meQuery.refetch();
    void offersQuery.refetch();
  }, [meQuery, offersQuery]);

  const me = meQuery.data;
  const offers = offersQuery.data?.results ?? [];
  const onShift = Boolean(me?.active_shift);

  const shiftEndsAt = me?.active_shift?.ends_at
    ? new Date(me.active_shift.ends_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : null;

  return (
    <ScrollView
      testID="partner-home"
      style={{ flex: 1, backgroundColor: colors.background }}
      contentContainerStyle={{
        padding: spacing.lg,
        paddingTop: insets.top + spacing.md,
        paddingBottom: insets.bottom + spacing.xl,
      }}
      refreshControl={
        <RefreshControl
          refreshing={meQuery.isRefetching || offersQuery.isRefetching}
          onRefresh={onRefresh}
          tintColor={colors.tint}
        />
      }>
      <Text style={[type.title, { color: colors.text }]}>Jobs</Text>

      {meQuery.isLoading ? (
        <View style={{ marginTop: spacing.lg }}>
          <SkeletonList count={2} />
        </View>
      ) : meQuery.isError ? (
        <ErrorState error={meQuery.error} onRetry={onRefresh} title="Could not load your account" />
      ) : me ? (
        <>
          {me.status !== 'approved' ? (
            <View style={{ marginTop: spacing.lg }}>
              <Banner
                testID="partner-status-banner"
                tone="info"
                title={`Application ${me.status.replace(/_/g, ' ')}`}
                message="Operations are reviewing your documents, kit and assessment."
              />
            </View>
          ) : null}

          {!me.readiness.eligible_for_offers ? (
            <View style={{ marginTop: spacing.lg }}>
              <Banner
                testID="readiness-blockers"
                tone="warning"
                title="Offers are switched off"
                message={me.readiness.summary}
                action={{ label: 'See what is needed', onPress: () => router.push('/(partner)/profile') }}
              />
            </View>
          ) : null}

          <Card testID="shift-card">
            <View style={styles.rowBetween}>
              <View style={{ flex: 1, paddingRight: spacing.md }}>
                <Text style={[type.heading, { color: colors.text }]}>
                  {onShift ? 'On shift' : 'Off shift'}
                </Text>
                <Text style={[type.caption, { color: colors.mutedText, marginTop: 2 }]}>
                  {onShift && shiftEndsAt
                    ? `Declared until ${shiftEndsAt}`
                    : 'Start a shift to receive job offers.'}
                </Text>
              </View>
              <Button
                testID="toggle-shift"
                label={onShift ? 'End shift' : 'Start shift'}
                variant={onShift ? 'secondary' : 'primary'}
                fullWidth={false}
                loading={availability.isPending}
                onPress={() => availability.mutate(!onShift)}
              />
            </View>

            <View style={{ marginTop: spacing.md }}>
              {/* A visible off-duty state is a privacy requirement, not a nicety. */}
              <Banner
                testID="location-state"
                tone={onShift ? 'info' : 'warning'}
                message={
                  onShift
                    ? 'Your location is shared while you are on shift or on a job, and stops when you go off duty.'
                    : 'Location sharing is off. Nothing is being collected.'
                }
              />
            </View>

            {actionError ? (
              <View style={{ marginTop: spacing.md }}>
                <ErrorState
                  error={actionError}
                  onRetry={() => setActionError(null)}
                  title="Could not update your shift"
                />
              </View>
            ) : null}
          </Card>
        </>
      ) : null}

      <SectionTitle>Live offers</SectionTitle>

      {offersQuery.isLoading ? (
        <SkeletonList count={2} />
      ) : offersQuery.isError ? (
        <ErrorState error={offersQuery.error} onRetry={onRefresh} title="Could not load offers" />
      ) : offers.length === 0 ? (
        <EmptyState
          testID="no-offers"
          title="No offers right now"
          message={
            onShift
              ? 'Offers appear here when a customer books near you. They expire quickly.'
              : 'Start a shift to start receiving offers.'
          }
          icon="briefcase-outline"
        />
      ) : (
        offers.map((offer) => (
          <OfferRow
            key={offer.id}
            offer={offer}
            onOpen={() => router.push(`/booking/${offer.booking_reference}`)}
            onChanged={() => {
              void queryClient.invalidateQueries({ queryKey: dispatchKeys.offers });
              void queryClient.invalidateQueries({ queryKey: bookingKeys.root });
            }}
            onAccepted={(reference) => router.replace(`/(partner)/job/${reference}`)}
          />
        ))
      )}
    </ScrollView>
  );
}

function OfferRow({
  offer,
  onOpen,
  onChanged,
  onAccepted,
}: {
  offer: DispatchOffer;
  onOpen: () => void;
  onChanged: () => void;
  /** Called with the booking reference once the offer is accepted. */
  onAccepted: (reference: string) => void;
}) {
  const { colors, spacing, type } = useTheme();
  const [error, setError] = useState<unknown>(null);
  const remaining = useCountdown(offer.seconds_remaining);
  const expiring = remaining <= 30;

  const accept = useMutation({
    mutationFn: () => dispatchApi.accept(offer.id),
    // Accepting commits the partner to the job, so hand the reference back to the
    // parent, which owns navigation, rather than making them find it again.
    onSuccess: (result) => {
      onChanged();
      onAccepted(result.booking.reference);
    },
    onError: setError,
  });

  const decline = useMutation({
    mutationFn: () => dispatchApi.decline(offer.id),
    onSuccess: onChanged,
    onError: setError,
  });

  return (
    <Card testID={`offer-${offer.id}`}>
      <View style={styles.rowBetween}>
        <Text style={[type.bodyStrong, { color: colors.text, flex: 1 }]}>{offer.service.name}</Text>
        <Text
          testID={`offer-timer-${offer.id}`}
          style={[type.bodyStrong, { color: expiring ? colors.danger : colors.tint }]}>
          {formatCountdown(remaining)}
        </Text>
      </View>

      <Text style={[type.caption, { color: colors.mutedText, marginTop: 4 }]}>
        {offer.vehicle.display_name} · {offer.location.line1}, {offer.location.city}
      </Text>

      {/* Labelled as an estimate, because straight-line data is not road travel. */}
      <Text style={[type.caption, { color: colors.mutedText, marginTop: 2 }]}>
        {offer.eta_seconds
          ? `About ${Math.round(offer.eta_seconds / 60)} min away (estimated)`
          : 'Travel time unknown'}{' '}
        · {formatDistance(offer.distance_km)}
      </Text>

      {offer.access_notes ? (
        <View style={{ marginTop: spacing.sm }}>
          <Text style={[type.captionStrong, { color: colors.text }]}>Access notes</Text>
          <Text style={[type.caption, { color: colors.mutedText }]}>{offer.access_notes}</Text>
        </View>
      ) : null}

      <Text style={[type.caption, { color: colors.mutedText, marginTop: spacing.sm }]}>
        Payout {formatMoney(offer.payout_estimate_minor, offer.currency)}
      </Text>

      {error ? (
        <Text style={[type.caption, { color: colors.danger, marginTop: spacing.sm }]}>
          {error instanceof Error ? error.message : 'Could not respond to this offer.'}
        </Text>
      ) : null}

      <View style={[styles.rowBetween, { marginTop: spacing.md }]}>
        <Button
          testID={`decline-${offer.id}`}
          label="Decline"
          variant="ghost"
          fullWidth={false}
          loading={decline.isPending}
          onPress={() => decline.mutate()}
        />
        <Button
          testID={`accept-${offer.id}`}
          label="Accept"
          fullWidth={false}
          loading={accept.isPending}
          disabled={remaining === 0}
          onPress={() => accept.mutate()}
        />
      </View>

      <View style={{ marginTop: spacing.sm }}>
        <Button testID={`view-${offer.id}`} label="View details" variant="secondary" onPress={onOpen} />
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  rowBetween: { flexDirection: 'row', alignItems: 'center', gap: 8 },
});

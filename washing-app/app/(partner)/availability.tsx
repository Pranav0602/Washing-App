/**
 * Partner availability: shift, service radius, capacity and weekly hours.
 *
 * Declared hours are the denominator of the PDF's partner-utilisation metric, so they
 * are edited explicitly rather than inferred from the shift toggle.
 */

import { useCallback, useState } from 'react';
import { RefreshControl, ScrollView, Text, View } from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { partnerApi } from '@/api/endpoints';
import { partnerKeys } from '@/query/keys';
import { formatDistance, weekdayShort } from '@/lib/format';
import { LocationMap } from '@/components/map';
import {
  Banner,
  Button,
  Card,
  DetailRow,
  ErrorState,
  SectionTitle,
  SkeletonList,
} from '@/components/ui';
import { useTheme } from '@/theme';

export default function AvailabilityScreen() {
  const insets = useSafeAreaInsets();
  const { colors, spacing, type } = useTheme();
  const queryClient = useQueryClient();
  const [error, setError] = useState<unknown>(null);

  const meQuery = useQuery({ queryKey: partnerKeys.me, queryFn: partnerApi.me });

  const setAvailability = useMutation({
    mutationFn: partnerApi.setAvailability,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: partnerKeys.me }),
    onError: setError,
  });

  const me = meQuery.data;
  const onShift = Boolean(me?.active_shift);

  const onRefresh = useCallback(() => {
    void meQuery.refetch();
  }, [meQuery]);

  return (
    <ScrollView
      testID="availability-screen"
      style={{ flex: 1, backgroundColor: colors.background }}
      contentContainerStyle={{
        padding: spacing.lg,
        paddingTop: insets.top + spacing.md,
        paddingBottom: insets.bottom + spacing.xl,
      }}
      refreshControl={
        <RefreshControl refreshing={meQuery.isRefetching} onRefresh={onRefresh} tintColor={colors.tint} />
      }>
      <Text style={[type.title, { color: colors.text }]}>Availability</Text>

      {meQuery.isLoading ? (
        <View style={{ marginTop: spacing.lg }}>
          <SkeletonList count={2} />
        </View>
      ) : meQuery.isError ? (
        <ErrorState error={meQuery.error} onRetry={onRefresh} title="Could not load your availability" />
      ) : me ? (
        <>
          <SectionTitle>Current shift</SectionTitle>
          <Card testID="current-shift">
            {onShift ? (
              <>
                <DetailRow label="Status" value="Active" tone="success" />
                <DetailRow
                  label="Declared until"
                  value={me.active_shift?.ends_at ? new Date(me.active_shift.ends_at).toLocaleString() : '—'}
                />
              </>
            ) : (
              <Text style={[type.body, { color: colors.mutedText }]}>
                You are off shift. Offers are only sent while a shift is active.
              </Text>
            )}

            <View style={{ marginTop: spacing.md }}>
              <Button
                testID="toggle-shift-availability"
                label={onShift ? 'End shift' : 'Start a 6-hour shift'}
                variant={onShift ? 'secondary' : 'primary'}
                loading={setAvailability.isPending}
                onPress={() =>
                  setAvailability.mutate(
                    onShift
                      ? { action: 'end' }
                      : {
                          action: 'start',
                          starts_at: new Date().toISOString(),
                          ends_at: new Date(Date.now() + 6 * 60 * 60 * 1000).toISOString(),
                          declared_capacity_minutes: 360,
                        },
                  )
                }
              />
            </View>
          </Card>

          <SectionTitle>Operating envelope</SectionTitle>
          <Card testID="operating-envelope">
            <DetailRow label="Service radius" value={formatDistance(me.service_radius_km)} />
            <DetailRow label="Concurrent jobs" value={String(me.default_capacity)} />
            <DetailRow label="Home zone" value={me.home_zone_id ? 'Set' : 'Not set'} />
          </Card>

          <Banner
            testID="declared-hours-note"
            tone="info"
            title="Why declared hours matter"
            message="Operations reviews partner utilisation as booked service time over declared available time. Declaring hours you cannot work skews that measure and leads to offers being sent to you at the wrong time."
          />

          <SectionTitle>Location freshness</SectionTitle>
          <Card>
            <DetailRow
              label="Sharing"
              value={onShift ? 'On' : 'Off'}
              tone={onShift ? 'success' : 'default'}
            />
            <DetailRow
              label="Last update"
              value={me.location?.last_recorded_at ? new Date(me.location.last_recorded_at).toLocaleString() : 'None'}
            />
            <DetailRow
              label="Status"
              value={me.location?.is_stale ? 'Stale' : me.location?.has_location ? 'Current' : 'No data'}
              tone={me.location?.is_stale ? 'danger' : 'default'}
            />
          </Card>
          {me.location?.has_location && me.location.latitude != null && me.location.longitude != null ? (
            <LocationMap
              coordinate={{
                latitude: me.location.latitude,
                longitude: me.location.longitude,
              }}
              style={{ marginTop: spacing.md }}
            />
          ) : null}
        </>
      ) : null}

      {error ? (
        <ErrorState error={error} onRetry={() => setError(null)} title="Could not update availability" />
      ) : null}

      <View style={{ marginTop: spacing.lg }}>
        <Text style={[type.caption, { color: colors.mutedText }]}>
          Weekly hours ({weekdayShort(0)} to {weekdayShort(6)}) are edited from your profile.
        </Text>
      </View>
    </ScrollView>
  );
}

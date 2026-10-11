/**
 * Profile and privacy controls.
 *
 * Includes the data export and deletion requests the PDF requires as a documented
 * privacy path, plus the precise-location disclosure for partners.
 */

import { useCallback } from 'react';
import { useRouter } from 'expo-router';
import { RefreshControl, ScrollView, Text, View } from 'react-native';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { meApi } from '@/api/endpoints';
import { sessionKeys } from '@/query/keys';
import { isApiError } from '@/lib/apiError';
import { useSession } from '@/auth/SessionProvider';
import { queryClient } from '@/query/queryClient';
import {
  Banner,
  Button,
  Card,
  DetailRow,
  ErrorState,
  SectionTitle,
  SkeletonList,
  ToggleRow,
} from '@/components/ui';
import { useTheme } from '@/theme';

export default function ProfileScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors, spacing, type } = useTheme();
  const { user, signOut, isPartner } = useSession();

  const preferencesQuery = useQuery({
    queryKey: sessionKeys.preferences,
    queryFn: meApi.getPreferences,
  });

  const consentsQuery = useQuery({
    queryKey: sessionKeys.consents,
    queryFn: meApi.getConsents,
  });

  const updatePreferences = useMutation({
    mutationFn: meApi.updatePreferences,
    // Invalidate rather than force a re-render: the query cache is the source of truth.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: sessionKeys.preferences }),
  });

  const dataRequest = useMutation({ mutationFn: meApi.submitDataRequest });

  const onRefresh = useCallback(() => {
    void preferencesQuery.refetch();
    void consentsQuery.refetch();
  }, [consentsQuery, preferencesQuery]);

  const preferences = preferencesQuery.data;

  return (
    <ScrollView
      testID="profile-screen"
      style={{ flex: 1, backgroundColor: colors.background }}
      contentContainerStyle={{
        padding: spacing.lg,
        paddingTop: insets.top + spacing.md,
        paddingBottom: insets.bottom + spacing.xl,
      }}
      refreshControl={
        <RefreshControl refreshing={preferencesQuery.isRefetching} onRefresh={onRefresh} tintColor={colors.tint} />
      }>
      <Text style={[type.title, { color: colors.text }]}>Profile</Text>

      <View style={{ height: spacing.lg }} />

      <Card testID="profile-card">
        <DetailRow label="Name" value={user?.full_name || '—'} />
        <DetailRow label="Phone" value={user?.phone || '—'} />
        <DetailRow label="Email" value={user?.email || 'Not set'} />
        <DetailRow label="Roles" value={(user?.roles ?? []).join(', ') || '—'} />
      </Card>

      <SectionTitle>Notifications</SectionTitle>

      {preferencesQuery.isLoading ? (
        <SkeletonList count={2} />
      ) : preferencesQuery.isError ? (
        <ErrorState
          error={preferencesQuery.error}
          onRetry={onRefresh}
          title="Could not load your preferences"
        />
      ) : preferences ? (
        <>
          <ToggleRow
            testID="pref-push"
            label="Push notifications"
            description="Booking updates, arrivals and delays."
            value={preferences.push_enabled}
            onValueChange={(push_enabled) => updatePreferences.mutate({ push_enabled })}
          />
          <ToggleRow
            testID="pref-booking-updates"
            label="Booking updates"
            description="Status changes for every booking."
            value={preferences.booking_updates}
            onValueChange={(booking_updates) => updatePreferences.mutate({ booking_updates })}
          />
          {isPartner ? (
            <ToggleRow
              testID="pref-offer-alerts"
              label="New job offers"
              description="Alerts when a job is offered to you."
              value={preferences.offer_alerts}
              onValueChange={(offer_alerts) => updatePreferences.mutate({ offer_alerts })}
            />
          ) : null}
          <ToggleRow
            testID="pref-marketing"
            label="Offers and news"
            description="Occasional messages about promotions."
            value={preferences.marketing}
            onValueChange={(marketing) => updatePreferences.mutate({ marketing })}
          />
        </>
      ) : null}

      <SectionTitle>Your consent</SectionTitle>

      <Card>
        {(consentsQuery.data ?? []).length === 0 ? (
          <Text style={[type.caption, { color: colors.mutedText }]}>No consent records found.</Text>
        ) : (
          (consentsQuery.data ?? []).map((consent) => (
            <DetailRow
              key={`${consent.consent_type}-${consent.version}`}
              label={consent.consent_type.replace(/_/g, ' ')}
              value={`${consent.granted ? 'Accepted' : 'Declined'} (v${consent.version})`}
              tone={consent.granted ? 'success' : 'danger'}
            />
          ))
        )}
      </Card>

      {isPartner ? (
        <>
          <SectionTitle>Location sharing</SectionTitle>
          <Banner
            testID="location-disclosure"
            tone="info"
            title="When your location is collected"
            message="Only while you have an active shift or an active job. Collection stops when you go off duty, and the app always shows whether it is on. Samples are deleted on a short retention cycle."
          />
        </>
      ) : null}

      <SectionTitle>Your data</SectionTitle>

      <Card>
        <Text style={[type.caption, { color: colors.mutedText, marginBottom: spacing.md }]}>
          Request a copy of your data, or ask for it to be deleted. Deletion is reviewed against
          legal hold, financial records and evidence retention before anything is removed.
        </Text>
        <View style={{ gap: spacing.sm }}>
          <Button
            testID="request-export"
            label="Request a copy of my data"
            variant="secondary"
            onPress={() => dataRequest.mutate('export')}
            loading={dataRequest.isPending}
          />
          <Button
            testID="request-delete"
            label="Request deletion of my data"
            variant="danger"
            onPress={() => dataRequest.mutate('delete')}
            loading={dataRequest.isPending}
          />
        </View>
        {dataRequest.isSuccess ? (
          <Text style={[type.caption, { color: colors.success, marginTop: spacing.md }]}>
            {dataRequest.data.note}
          </Text>
        ) : null}
        {dataRequest.isError ? (
          <Text style={[type.caption, { color: colors.danger, marginTop: spacing.md }]}>
            {isApiError(dataRequest.error)
              ? dataRequest.error.displayMessage
              : 'Could not submit the request.'}
          </Text>
        ) : null}
      </Card>

      <View style={{ marginTop: spacing.xl }}>
        <Button
          testID="sign-out"
          label="Sign out"
          variant="secondary"
          onPress={async () => {
            await signOut();
            router.replace('/(auth)/phone');
          }}
        />
      </View>
    </ScrollView>
  );
}


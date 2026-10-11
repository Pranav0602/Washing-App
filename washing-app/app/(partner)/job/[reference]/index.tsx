/**
 * The partner's active job.
 *
 * Everything needed on site lives here: navigate there, mark arrival, run the service
 * checklist, capture evidence, and complete. The action buttons are derived from the
 * server's `allowed_transitions`, so the app can never offer a step the backend would
 * reject, and the customer sees the same status.
 */
import { useMemo, useState } from 'react';

import { useLocalSearchParams, useRouter } from 'expo-router';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Linking, Platform, StyleSheet, Text, TextInput, View } from 'react-native';

import { bookingApi, dispatchApi } from '@/api/endpoints';
import { bookingKeys } from '@/query/keys';
import { formatWindow } from '@/lib/format';
import { toDisplayMessage } from '@/lib/apiError';
import {
  Badge,
  Banner,
  Button,
  Card,
  DetailRow,
  EmptyState,
  ErrorState,
  LoadingState,
  Screen,
  SectionTitle,
} from '@/components/ui';
import { BookingProgress, StatusBadge } from '@/components/booking/BookingStatus';
import { useTheme } from '@/theme';

/** Milestone the partner can self-report, mapped to the endpoint and button label. */
const MILESTONES = [
  { key: 'en_route', label: 'Start travelling', hint: 'Only when you are actually moving.' },
  { key: 'arrived', label: 'I have arrived', hint: 'Confirm you are at the address.' },
  { key: 'start', label: 'Start the wash', hint: 'Marks the service as started.' },
] as const;

export default function PartnerJobScreen() {
  const { reference } = useLocalSearchParams<{ reference: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { colors, radius, spacing, type } = useTheme();

  const [completionNotes, setCompletionNotes] = useState('');

  const jobQuery = useQuery({
    queryKey: bookingKeys.job(reference ?? ''),
    queryFn: () => dispatchApi.job(reference!),
    enabled: Boolean(reference),
    refetchInterval: 20_000,
  });

  const refreshJob = () => queryClient.invalidateQueries({ queryKey: bookingKeys.job(reference!) });

  const milestone = useMutation({
    mutationFn: (key: (typeof MILESTONES)[number]['key']) =>
      bookingApi.milestone(reference!, key, { source: 'partner_app' }),
    onSuccess: refreshJob,
  });

  const complete = useMutation({
    mutationFn: () => bookingApi.complete(reference!, completionNotes.trim()),
    onSuccess: () => {
      refreshJob();
      router.replace('/(partner)');
    },
  });

  const job = jobQuery.data;

  const allowed = useMemo(
    () => new Set((job?.allowed_transitions ?? []).map((item) => item.action)),
    [job?.allowed_transitions],
  );

  const openMaps = () => {
    if (!job?.navigation) return;
    const { latitude, longitude, address_lines: address } = job.navigation;
    const url = Platform.select({
      ios: `maps:0,0?q=${latitude},${longitude}`,
      default: `geo:0,0?q=${latitude},${longitude}(${encodeURIComponent(address)})`,
    });
    void Linking.openURL(url);
  };

  if (jobQuery.isLoading) return <Screen testID="partner-job-screen"><LoadingState /></Screen>;

  if (jobQuery.isError) {
    return (
      <Screen testID="partner-job-screen">
        <ErrorState error={jobQuery.error} onRetry={() => void jobQuery.refetch()} />
      </Screen>
    );
  }

  if (!job) {
    return (
      <Screen testID="partner-job-screen">
        <EmptyState title="Job unavailable" message="This job is no longer assigned to you." icon="alert-circle" />
      </Screen>
    );
  }

  const { booking, checklist, evidence, navigation, customer_contact: contact } = job;
  const requiredItems = checklist.filter((item) => item.is_required);
  const outstanding = requiredItems.filter((item) => !item.is_done);
  const canComplete = outstanding.length === 0 && allowed.has('complete');

  return (
    <Screen testID="partner-job-screen" onRefresh={refreshJob} refreshing={jobQuery.isRefetching}>
      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          <Text style={[type.caption, { color: colors.mutedText }]}>Booking</Text>
          <Text style={[type.title, { color: colors.text }]}>{booking.reference}</Text>
        </View>
        <StatusBadge status={booking.status} />
      </View>

      <Card style={{ marginTop: spacing.md }}>
        <BookingProgress status={booking.status} />
      </Card>

      <Card style={{ marginTop: spacing.md }}>
        <SectionTitle>Where</SectionTitle>
        <Text style={[type.bodyStrong, { color: colors.text }]}>
          {booking.address?.line1}
          {booking.address?.line2 ? `, ${booking.address.line2}` : ''}
        </Text>
        <Text style={[type.caption, { color: colors.mutedText, marginTop: 2 }]}>
          {booking.address?.city} - {formatWindow(booking.window_start, booking.window_end)}
        </Text>
        {booking.address?.access_notes ? (
          <Banner
            tone="warning"
            title="Access notes"
            message={booking.address.access_notes}
            testID="partner-access-notes"
          />
        ) : null}
        <Button
          label="Navigate"
          icon="navigate"
          testID="partner-job-navigate"
          style={{ marginTop: spacing.md }}
          onPress={openMaps}
        />
        <Text style={[type.caption, { color: colors.mutedText, marginTop: spacing.sm }]}>
          {navigation?.address_lines ?? 'Address hidden'}
        </Text>
      </Card>

      <Card style={{ marginTop: spacing.md }}>
        <SectionTitle>Customer</SectionTitle>
        <DetailRow label="Contact" value={contact?.masked_phone ?? 'Hidden'} testID="partner-contact" />
        {contact?.note ? (
          <Text style={[type.caption, { color: colors.mutedText, marginTop: spacing.xs }]}>
            {contact.note}
          </Text>
        ) : null}
      </Card>

      <Card style={{ marginTop: spacing.md }}>
        <SectionTitle
          action={
            <Button
              label="Open"
              variant="ghost"
              testID="partner-open-checklist"
              onPress={() => router.push(`/(partner)/job/${booking.reference}/checklist`)}
            />
          }
        >
          Checklist
        </SectionTitle>
        <Text style={[type.caption, { color: colors.mutedText }]}>
          {requiredItems.length - outstanding.length} of {requiredItems.length} required steps done
        </Text>
        {outstanding.length > 0 ? (
          <BulletPreview items={outstanding.slice(0, 3).map((item) => item.label)} />
        ) : (
          <Badge label="All required steps done" tone="success" icon="checkmark-circle" />
        )}
      </Card>

      <Card style={{ marginTop: spacing.md }}>
        <SectionTitle
          action={
            <Button
              label="Open"
              variant="ghost"
              testID="partner-open-evidence"
              onPress={() => router.push(`/(partner)/job/${booking.reference}/evidence`)}
            />
          }
        >
          Evidence
        </SectionTitle>
        <Text style={[type.caption, { color: colors.mutedText }]}>
          {evidence.length} photo{evidence.length === 1 ? '' : 's'} uploaded
        </Text>
      </Card>

      <Card style={{ marginTop: spacing.md }}>
        <SectionTitle>Progress</SectionTitle>
        {MILESTONES.map((item) => {
          const isNext = allowed.has(item.key);
          return (
            <Button
              key={item.key}
              label={item.label}
              testID={`partner-milestone-${item.key}`}
              disabled={!isNext || milestone.isPending}
              loading={milestone.isPending && milestone.variables === item.key}
              variant={isNext ? 'primary' : 'secondary'}
              style={{ marginTop: spacing.sm }}
              onPress={() => milestone.mutate(item.key)}
            />
          );
        })}
        {milestone.isError ? (
          <Text style={[type.caption, { color: colors.danger, marginTop: spacing.sm }]}>
            {toDisplayMessage(milestone.error)}
          </Text>
        ) : null}
      </Card>

      {canComplete ? (
        <Card style={{ marginTop: spacing.md }}>
          <SectionTitle>Finish the job</SectionTitle>
          <TextInput
            testID="partner-completion-notes"
            value={completionNotes}
            onChangeText={setCompletionNotes}
            placeholder="Notes for the customer (optional)"
            placeholderTextColor={colors.mutedText}
            multiline
            style={[
              {
                borderWidth: 1,
                borderRadius: radius.md,
                borderColor: colors.border,
                padding: spacing.md,
                minHeight: 80,
                color: colors.text,
              },
              type.body,
            ]}
          />
          <Button
            label="Complete job"
            testID="partner-complete"
            fullWidth
            style={{ marginTop: spacing.md }}
            loading={complete.isPending}
            disabled={!canComplete}
            onPress={() => complete.mutate()}
          />
          {complete.isError ? (
            <Text style={[type.caption, { color: colors.danger, marginTop: spacing.sm }]}>
              {toDisplayMessage(complete.error)}
            </Text>
          ) : null}
        </Card>
      ) : (
        <Banner
          tone="info"
          message={
            outstanding.length > 0
              ? `Finish the ${outstanding.length} outstanding checklist step(s) to unlock completion.`
              : 'Completion unlocks once every required checklist step is done.'
          }
          testID="partner-complete-locked"
        />
      )}
    </Screen>
  );
}

function BulletPreview({ items }: { items: string[] }) {
  const { colors, spacing, type } = useTheme();
  return (
    <View style={{ marginTop: spacing.sm }}>
      {items.map((item) => (
        <Text key={item} style={[type.caption, { color: colors.mutedText }]}>
          - {item}
        </Text>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: 'row', alignItems: 'center', gap: 12 },
});
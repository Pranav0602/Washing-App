/**
 * Operations job board.
 *
 * The PDF requires the loop to stay operable by hand during the pilot, so this is the
 * primary tool: every job, its state, and a route to manual assignment.
 */

import { useCallback, useState } from 'react';
import { useRouter } from 'expo-router';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { opsApi } from '@/api/endpoints';
import { opsKeys } from '@/query/keys';
import { formatDateTime } from '@/lib/format';
import { StatusBadge } from '@/components/booking/BookingStatus';
import { ChipGroup, EmptyState, ErrorState, PressableCard, SkeletonList } from '@/components/ui';
import { useTheme } from '@/theme';

type BoardFilter = 'all' | 'unassigned' | 'late';

export default function OpsJobsScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors, spacing, type } = useTheme();
  const [filter, setFilter] = useState<BoardFilter>('all');

  const query = useQuery({
    queryKey: opsKeys.jobs({ filter }),
    queryFn: () =>
      opsApi.jobs(
        filter === 'unassigned'
          ? { unassigned: true }
          : filter === 'late'
            ? { late: true }
            : {},
      ),
  });

  const onRefresh = useCallback(() => {
    void query.refetch();
  }, [query]);

  const jobs = query.data ?? [];

  return (
    <ScrollView
      testID="ops-jobs-screen"
      style={{ flex: 1, backgroundColor: colors.background }}
      contentContainerStyle={{
        padding: spacing.lg,
        paddingTop: insets.top + spacing.md,
        paddingBottom: insets.bottom + spacing.xl,
      }}
      refreshControl={
        <RefreshControl refreshing={query.isRefetching} onRefresh={onRefresh} tintColor={colors.tint} />
      }>
      <Text style={[type.title, { color: colors.text }]}>Job board</Text>

      <View style={{ height: spacing.lg }} />

      <ChipGroup
        options={[
          { value: 'all', label: 'All' },
          { value: 'unassigned', label: 'Unassigned' },
          { value: 'late', label: 'Late' },
        ]}
        value={filter}
        onChange={(value) => setFilter(value as BoardFilter)}
        testID="ops-board-filter"
      />

      <View style={{ height: spacing.lg }} />

      {query.isLoading ? (
        <SkeletonList count={4} />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={onRefresh} title="Could not load the job board" />
      ) : jobs.length === 0 ? (
        <EmptyState
          testID="no-jobs"
          title="Nothing to show"
          message="No jobs match this filter right now."
          icon="grid-outline"
        />
      ) : (
        jobs.map((job) => (
          <PressableCard
            key={job.reference}
            testID={`ops-job-${job.reference}`}
            onPress={() => router.push(`/booking/${job.reference}`)}
            accessibilityLabel={`${job.reference}, ${job.status_label}`}>
            <View style={styles.rowBetween}>
              <Text style={[type.bodyStrong, { color: colors.text, flex: 1 }]}>{job.reference}</Text>
              <StatusBadge status={job.status} />
            </View>
            <Text style={[type.caption, { color: colors.mutedText, marginTop: 4 }]}>
              {job.service_name} · {job.vehicle_name} · {job.zone_code}
            </Text>
            <Text style={[type.caption, { color: colors.mutedText, marginTop: 2 }]}>
              {job.partner_name ? `Partner: ${job.partner_name}` : 'No partner assigned'} ·{' '}
              {formatDateTime(job.scheduled_start ?? job.created_at)}
            </Text>
          </PressableCard>
        ))
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  rowBetween: { flexDirection: 'row', alignItems: 'center', gap: 8 },
});

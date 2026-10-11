/**
 * Operations exception queue.
 *
 * The PDF names these categories explicitly: unassigned, late, failed payment,
 * unsafe site and damage. Each row links straight to the job so an operator can
 * intervene immediately.
 */

import { useCallback, useState } from 'react';
import { useRouter } from 'expo-router';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { opsApi } from '@/api/endpoints';
import { opsKeys } from '@/query/keys';
import { formatAge } from '@/lib/format';
import { Badge, ChipGroup, EmptyState, ErrorState, PressableCard, SkeletonList } from '@/components/ui';
import { useTheme } from '@/theme';

const TYPES = [
  { value: 'all', label: 'All' },
  { value: 'unassigned', label: 'Unassigned' },
  { value: 'late', label: 'Late' },
  { value: 'stale_location', label: 'Stale GPS' },
  { value: 'failed_payment', label: 'Payment' },
  { value: 'unsafe_site', label: 'Unsafe' },
  { value: 'damage', label: 'Damage' },
  { value: 'sla_breached', label: 'SLA' },
];

export default function OpsExceptionsScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors, spacing, type } = useTheme();
  const [filter, setFilter] = useState('all');

  const query = useQuery({
    queryKey: opsKeys.exceptions(filter === 'all' ? undefined : filter),
    queryFn: () => opsApi.exceptions(filter === 'all' ? undefined : filter),
    // The queue is the live exception surface, so it refreshes on a short cycle.
    refetchInterval: 30_000,
  });

  const onRefresh = useCallback(() => {
    void query.refetch();
  }, [query]);

  const rows = query.data?.results ?? [];

  return (
    <ScrollView
      testID="ops-exceptions-screen"
      style={{ flex: 1, backgroundColor: colors.background }}
      contentContainerStyle={{
        padding: spacing.lg,
        paddingTop: insets.top + spacing.md,
        paddingBottom: insets.bottom + spacing.xl,
      }}
      refreshControl={
        <RefreshControl refreshing={query.isRefetching} onRefresh={onRefresh} tintColor={colors.tint} />
      }>
      <Text style={[type.title, { color: colors.text }]}>Exceptions</Text>
      <Text style={[type.caption, { color: colors.mutedText, marginTop: spacing.xs }]}>
        Jobs needing a human decision, oldest first.
      </Text>

      <View style={{ height: spacing.lg }} />

      <ChipGroup options={TYPES} value={filter} onChange={setFilter} testID="ops-exception-filter" />

      <View style={{ height: spacing.lg }} />

      {query.isLoading ? (
        <SkeletonList count={4} />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={onRefresh} title="Could not load the exception queue" />
      ) : rows.length === 0 ? (
        <EmptyState
          testID="no-exceptions"
          title="Queue is clear"
          message="No jobs are waiting on a human decision."
          icon="checkmark-done-outline"
        />
      ) : (
        rows.map((row) => (
          <PressableCard
            key={`${row.type}-${row.reference}`}
            testID={`exception-${row.type}-${row.reference}`}
            onPress={() => router.push(`/booking/${row.reference}`)}
            accessibilityLabel={`${row.type}, ${row.reference}, ${row.severity} severity`}>
            <View style={styles.rowBetween}>
              <Text style={[type.bodyStrong, { color: colors.text, flex: 1 }]}>{row.reference}</Text>
              <Badge
                label={row.severity}
                tone={row.severity === 'high' ? 'danger' : row.severity === 'medium' ? 'warning' : 'neutral'}
              />
            </View>
            <Text style={[type.caption, { color: colors.mutedText, marginTop: 4 }]}>
              {row.type.replace(/_/g, ' ')} · {row.zone} · {formatAge(row.age_seconds)} old
            </Text>
            {row.partner ? (
              <Text style={[type.caption, { color: colors.mutedText }]}>Partner: {row.partner}</Text>
            ) : null}
          </PressableCard>
        ))
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  rowBetween: { flexDirection: 'row', alignItems: 'center', gap: 8 },
});

/**
 * Pilot dashboard.
 *
 * Metrics and definitions come from the server so the numbers on screen match the
 * PDF's stated definitions exactly, including the numerator and denominator.
 */

import { useCallback } from 'react';
import { RefreshControl, ScrollView, Text, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { opsApi } from '@/api/endpoints';
import { opsKeys } from '@/query/keys';
import { formatMoney } from '@/lib/format';
import { Banner, Button, Card, ErrorState, SectionTitle, SkeletonList } from '@/components/ui';
import { useSession } from '@/auth/SessionProvider';
import { useTheme } from '@/theme';

export default function OpsDashboardScreen() {
  const insets = useSafeAreaInsets();
  const { colors, spacing, type } = useTheme();
  const { signOut } = useSession();

  const query = useQuery({
    queryKey: opsKeys.dashboard({}),
    queryFn: () => opsApi.dashboard(),
  });

  const onRefresh = useCallback(() => {
    void query.refetch();
  }, [query]);

  const dashboard = query.data;

  return (
    <ScrollView
      testID="ops-dashboard-screen"
      style={{ flex: 1, backgroundColor: colors.background }}
      contentContainerStyle={{
        padding: spacing.lg,
        paddingTop: insets.top + spacing.md,
        paddingBottom: insets.bottom + spacing.xl,
      }}
      refreshControl={
        <RefreshControl refreshing={query.isRefetching} onRefresh={onRefresh} tintColor={colors.tint} />
      }>
      <Text style={[type.title, { color: colors.text }]}>Pilot metrics</Text>

      {query.isLoading ? (
        <View style={{ marginTop: spacing.lg }}>
          <SkeletonList count={3} />
        </View>
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={onRefresh} title="Could not load the dashboard" />
      ) : dashboard ? (
        <>
          {dashboard.warnings.map((warning) => (
            <Banner key={warning} tone="warning" message={warning} />
          ))}

          <Card testID="contribution-card">
            <Text style={[type.caption, { color: colors.mutedText }]}>
              Contribution per completed wash
            </Text>
            <Text style={[type.display, { color: colors.text, marginTop: 4 }]}>
              {dashboard.contribution_per_wash_minor === null
                ? '—'
                : formatMoney(dashboard.contribution_per_wash_minor, dashboard.currency)}
            </Text>
          </Card>

          <SectionTitle>Measures</SectionTitle>
          {dashboard.metrics.map((metric) => (
            <Card key={metric.name} testID={`metric-${metric.name}`}>
              <Text style={[type.bodyStrong, { color: colors.text }]}>
                {metric.name.replace(/_/g, ' ')}
              </Text>
              <Text
                style={[
                  type.title,
                  { color: belowTarget(metric.value, metric.target) ? colors.danger : colors.text, marginTop: 4 },
                ]}>
                {formatMetric(metric)}
              </Text>
              <Text style={[type.caption, { color: colors.mutedText, marginTop: spacing.xs }]}>
                {metric.definition}
              </Text>
              <Text style={[type.caption, { color: colors.mutedText, marginTop: 4 }]}>
                {metric.numerator} / {metric.denominator}
                {metric.target !== undefined ? ` · target ${formatTarget(metric.target, metric.unit)}` : ''}
              </Text>
              {metric.note ? (
                <Text style={[type.caption, { color: colors.mutedText, marginTop: 2 }]}>{metric.note}</Text>
              ) : null}
            </Card>
          ))}
        </>
      ) : null}

      <View style={{ marginTop: spacing.xl }}>
        <Button testID="ops-sign-out" label="Sign out" variant="secondary" onPress={() => void signOut()} />
      </View>
    </ScrollView>
  );
}

function formatMetric(metric: { value: number | null; unit: string }): string {
  if (metric.value === null) return '—';
  if (metric.unit === 'ratio') return `${(metric.value * 100).toFixed(1)}%`;
  if (metric.unit === 'average_of_5') return `${metric.value.toFixed(2)} / 5`;
  if (metric.unit === 'minutes') return `${Math.round(metric.value)} min`;
  return String(Math.round(metric.value));
}

function formatTarget(target: number, unit: string): string {
  if (unit === 'ratio') return `${(target * 100).toFixed(0)}%`;
  if (unit === 'average_of_5') return `${target.toFixed(1)} / 5`;
  return String(target);
}

/** Lower is better for rework, count and safety metrics; higher for the rest. */
function belowTarget(value: number | null, target: number | undefined): boolean {
  if (value === null || target === undefined) return false;
  return value < target;
}


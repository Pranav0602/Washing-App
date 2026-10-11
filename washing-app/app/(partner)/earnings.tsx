/**
 * Partner earnings summary.
 *
 * Shows gross, commission, adjustments and net per payable, plus payout batches. All
 * figures come from the server's ledger so the partner's view reconciles with what
 * operations actually paid.
 */

import { useCallback } from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { partnerApi } from '@/api/endpoints';
import { partnerKeys } from '@/query/keys';
import { formatDate, formatMoney } from '@/lib/format';
import { Badge, Banner, Card, DetailRow, EmptyState, ErrorState, SectionTitle, SkeletonList } from '@/components/ui';
import { useTheme } from '@/theme';

export default function EarningsScreen() {
  const insets = useSafeAreaInsets();
  const { colors, spacing, type } = useTheme();

  const query = useQuery({ queryKey: partnerKeys.earnings(), queryFn: () => partnerApi.earnings() });

  const onRefresh = useCallback(() => {
    void query.refetch();
  }, [query]);

  const data = query.data;

  return (
    <ScrollView
      testID="earnings-screen"
      style={{ flex: 1, backgroundColor: colors.background }}
      contentContainerStyle={{
        padding: spacing.lg,
        paddingTop: insets.top + spacing.md,
        paddingBottom: insets.bottom + spacing.xl,
      }}
      refreshControl={
        <RefreshControl refreshing={query.isRefetching} onRefresh={onRefresh} tintColor={colors.tint} />
      }>
      <Text style={[type.title, { color: colors.text }]}>Earnings</Text>

      {query.isLoading ? (
        <View style={{ marginTop: spacing.lg }}>
          <SkeletonList count={2} />
        </View>
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={onRefresh} title="Could not load your earnings" />
      ) : data ? (
        <>
          <Card testID="earnings-summary">
            <Text style={[type.caption, { color: colors.mutedText }]}>Net earned</Text>
            <Text testID="earnings-net" style={[type.display, { color: colors.text, marginTop: 4 }]}>
              {formatMoney(data.summary.net_minor, data.currency)}
            </Text>
            <View style={{ height: spacing.md }} />
            <DetailRow label="Gross job value" value={formatMoney(data.summary.gross_minor, data.currency)} />
            <DetailRow
              label="Platform commission"
              value={`- ${formatMoney(data.summary.commission_minor, data.currency)}`}
            />
            {data.summary.adjustment_minor ? (
              <DetailRow
                label="Adjustments"
                value={formatMoney(data.summary.adjustment_minor, data.currency)}
                tone={data.summary.adjustment_minor >= 0 ? 'success' : 'danger'}
              />
            ) : null}
          </Card>

          <SectionTitle>Per job</SectionTitle>
          {data.payables.length === 0 ? (
            <EmptyState
              testID="no-payables"
              title="No completed jobs yet"
              message="Earnings appear here once a wash you completed has been paid for by the customer."
              icon="wallet-outline"
            />
          ) : (
            data.payables.map((payable) => (
              <Card key={payable.id} testID={`payable-${payable.id}`}>
                <View style={styles.rowBetween}>
                  <Text style={[type.bodyStrong, { color: colors.text, flex: 1 }]}>
                    {payable.booking_reference}
                  </Text>
                  <Badge
                    label={payable.status_label}
                    tone={
                      payable.status === 'paid'
                        ? 'success'
                        : payable.status === 'on_hold' || payable.status === 'reversed'
                          ? 'danger'
                          : 'info'
                    }
                  />
                </View>
                <Text style={[type.caption, { color: colors.mutedText, marginTop: 4 }]}>
                  {formatMoney(payable.net_minor, payable.currency)} net
                  {payable.commission_minor
                    ? ` · ${formatMoney(payable.commission_minor, payable.currency)} commission`
                    : ''}
                </Text>
                {payable.hold_reason ? (
                  <Text style={[type.caption, { color: colors.warning, marginTop: spacing.xs }]}>
                    {payable.hold_reason}
                  </Text>
                ) : null}
                {payable.payout_batch_reference ? (
                  <Text style={[type.caption, { color: colors.mutedText, marginTop: spacing.xs }]}>
                    Batch {payable.payout_batch_reference}
                  </Text>
                ) : null}
              </Card>
            ))
          )}

          <SectionTitle>Payout batches</SectionTitle>
          {data.payout_batches.length === 0 ? (
            <Text style={[type.caption, { color: colors.mutedText }]}>
              No payouts have been processed yet.
            </Text>
          ) : (
            data.payout_batches.map((batch) => (
              <Card key={batch.id} testID={`batch-${batch.id}`}>
                <View style={styles.rowBetween}>
                  <Text style={[type.bodyStrong, { color: colors.text, flex: 1 }]}>
                    {batch.reference}
                  </Text>
                  <Badge label={batch.status.replace(/_/g, ' ')} tone="info" />
                </View>
                <Text style={[type.caption, { color: colors.mutedText, marginTop: 4 }]}>
                  {formatMoney(batch.total_minor, batch.currency)} · {batch.payable_count} jobs
                </Text>
                <Text style={[type.caption, { color: colors.mutedText }]}>
                  Period ending {formatDate(batch.period_end)}
                </Text>
              </Card>
            ))
          )}

          <Banner
            testID="earnings-note"
            tone="info"
            message="Partner payout is created once the customer payment is captured. It then enters the next payout batch."
          />
        </>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  rowBetween: { flexDirection: 'row', alignItems: 'center', gap: 8 },
});

/**
 * Partner approvals for operations.
 *
 * Approve, suspend and reinstate always require a reason; the server writes an audit
 * entry in the same transaction, so this screen never accepts an un-audited action.
 */

import { useCallback, useState } from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { opsApi } from '@/api/endpoints';
import { opsKeys } from '@/query/keys';
import { Badge, Button, Card, ChipGroup, DetailRow, EmptyState, ErrorState, SkeletonList } from '@/components/ui';
import { useTheme } from '@/theme';

type Filter = 'all' | 'pending_verification' | 'approved' | 'suspended';

export default function OpsPartnersScreen() {
  const insets = useSafeAreaInsets();
  const { colors, spacing, type } = useTheme();
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<Filter>('all');
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [error, setError] = useState<unknown>(null);

  const query = useQuery({
    queryKey: opsKeys.partners({ status: filter }),
    queryFn: () => opsApi.partners(filter === 'all' ? {} : { status: filter }),
  });

  const decide = useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'approve' | 'suspend' | 'reinstate' }) =>
      opsApi.decidePartner(id, action, reasons[id] ?? ''),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: opsKeys.partners({}) }),
    onError: setError,
  });

  const onRefresh = useCallback(() => {
    void query.refetch();
  }, [query]);

  const partners = query.data ?? [];

  return (
    <ScrollView
      testID="ops-partners-screen"
      style={{ flex: 1, backgroundColor: colors.background }}
      contentContainerStyle={{
        padding: spacing.lg,
        paddingTop: insets.top + spacing.md,
        paddingBottom: insets.bottom + spacing.xl,
      }}
      refreshControl={
        <RefreshControl refreshing={query.isRefetching} onRefresh={onRefresh} tintColor={colors.tint} />
      }>
      <Text style={[type.title, { color: colors.text }]}>Partners</Text>

      <View style={{ height: spacing.lg }} />

      <ChipGroup
        options={[
          { value: 'all', label: 'All' },
          { value: 'pending_verification', label: 'Pending' },
          { value: 'approved', label: 'Approved' },
          { value: 'suspended', label: 'Suspended' },
        ]}
        value={filter}
        onChange={(value) => setFilter(value as Filter)}
        testID="ops-partner-filter"
      />

      <View style={{ height: spacing.lg }} />

      {query.isLoading ? (
        <SkeletonList count={3} />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={onRefresh} title="Could not load partners" />
      ) : partners.length === 0 ? (
        <EmptyState title="No partners here" message="Nothing matches this filter." icon="people-outline" />
      ) : (
        partners.map((partner) => (
          <Card key={partner.id} testID={`ops-partner-${partner.id}`}>
            <View style={styles.rowBetween}>
              <Text style={[type.bodyStrong, { color: colors.text, flex: 1 }]}>
                {partner.display_name}
              </Text>
              <Badge
                label={partner.status.replace(/_/g, ' ')}
                tone={
                  partner.status === 'approved'
                    ? 'success'
                    : partner.status === 'suspended' || partner.status === 'rejected'
                      ? 'danger'
                      : 'warning'
                }
              />
            </View>

            <DetailRow
              label="Ready for offers"
              value={partner.readiness.eligible_for_offers ? 'Yes' : 'No'}
              tone={partner.readiness.eligible_for_offers ? 'success' : 'danger'}
            />
            {partner.readiness.blockers.length > 0 ? (
              <Text style={[type.caption, { color: colors.mutedText, marginTop: 4 }]}>
                {partner.readiness.blockers.map((blocker) => blocker.message).join('; ')}
              </Text>
            ) : null}

            {/* A reason is required for every state change and is written to the audit log. */}
            <View style={{ marginTop: spacing.md }}>
              <ReasonInput
                value={reasons[partner.id] ?? ''}
                onChange={(value) => setReasons((current) => ({ ...current, [partner.id]: value }))}
                partnerId={partner.id}
              />
            </View>

            <View style={[styles.rowBetween, { marginTop: spacing.md }]}>
              {partner.status === 'pending_verification' ? (
                <Button
                  testID={`approve-${partner.id}`}
                  label="Approve"
                  fullWidth={false}
                  loading={decide.isPending}
                  onPress={() => decide.mutate({ id: partner.id, action: 'approve' })}
                />
              ) : null}
              {partner.status !== 'suspended' ? (
                <Button
                  testID={`suspend-${partner.id}`}
                  label="Suspend"
                  variant="danger"
                  fullWidth={false}
                  loading={decide.isPending}
                  onPress={() => decide.mutate({ id: partner.id, action: 'suspend' })}
                />
              ) : (
                <Button
                  testID={`reinstate-${partner.id}`}
                  label="Reinstate"
                  variant="secondary"
                  fullWidth={false}
                  loading={decide.isPending}
                  onPress={() => decide.mutate({ id: partner.id, action: 'reinstate' })}
                />
              )}
            </View>
          </Card>
        ))
      )}

      {error ? (
        <ErrorState
          testID="partner-decision-error"
          error={error}
          onRetry={() => setError(null)}
          title="Could not record that decision"
        />
      ) : null}
    </ScrollView>
  );
}

/** A plain reason input. A bound TextField would be overkill for one field. */
function ReasonInput({
  value,
  onChange,
  partnerId,
}: {
  value: string;
  onChange: (value: string) => void;
  partnerId: string;
}) {
  const { colors, radius, spacing, type } = useTheme();
  return (
    <View>
      <Text style={[type.caption, { color: colors.mutedText, marginBottom: 4 }]}>
        Reason (recorded in the audit log)
      </Text>
      <TextInput
        testID={`reason-${partnerId}`}
        value={value}
        onChangeText={onChange}
        placeholder="Required for suspend and reinstate"
        placeholderTextColor={colors.mutedText}
        accessibilityLabel="Reason for this decision"
        autoCapitalize="sentences"
        style={[
          {
            borderWidth: 1,
            borderColor: colors.border,
            borderRadius: radius.md,
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.md,
            minHeight: 44,
            color: colors.text,
          },
          type.body,
        ]}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  rowBetween: { flexDirection: 'row', alignItems: 'center', gap: 8 },
});

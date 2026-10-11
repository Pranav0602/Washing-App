/**
 * The partner's service checklist for a job.
 *
 * Every toggle is written through immediately rather than on a save button: the backend
 * treats a partially-complete job as incomplete, and the partner should never lose work
 * to a dropped connection or a backgrounded app.
 */
import { useCallback, useMemo, useRef, useState } from 'react';

import { useLocalSearchParams, useRouter } from 'expo-router';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, Text, View } from 'react-native';

import { bookingApi } from '@/api/endpoints';
import { bookingKeys } from '@/query/keys';
import { toDisplayMessage } from '@/lib/apiError';
import {
  Badge,
  Button,
  Card,
  Checkbox,
  EmptyState,
  ErrorState,
  LoadingState,
  Screen,
  SectionTitle,
} from '@/components/ui';
import { useTheme } from '@/theme';

export default function PartnerChecklistScreen() {
  const { reference } = useLocalSearchParams<{ reference: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { colors, spacing, type } = useTheme();

  // Optimistic state keyed by item code so a slow round trip never blocks the partner.
  const [overrides, setOverrides] = useState<Record<string, boolean>>({});
  // Snapshot for rolling the optimistic toggles back if the server rejects them.
  const snapshot = useRef<Record<string, boolean>>({});

  const checklistQuery = useQuery({
    queryKey: bookingKeys.checklist(reference ?? ''),
    queryFn: () => bookingApi.checklist(reference!),
    enabled: Boolean(reference),
  });

  const update = useMutation({
    mutationFn: (items: { code: string; done: boolean }[]) =>
      bookingApi.updateChecklist(reference!, items),
    onSuccess: (updated) => {
      queryClient.setQueryData(bookingKeys.checklist(reference!), updated);
      void queryClient.invalidateQueries({ queryKey: bookingKeys.job(reference!) });
    },
    onError: (error) => {
      // Roll the optimistic toggle back so the UI never claims work that was rejected.
      setOverrides(snapshot.current);
      Alert.alert('Could not save', toDisplayMessage(error));
    },
    onMutate: async (items) => {
      snapshot.current = overrides;
      setOverrides((current) => {
        const next = { ...current };
        for (const item of items) next[item.code] = item.done;
        return next;
      });
    },
  });

  const toggle = useCallback(
    (code: string, done: boolean) => update.mutate([{ code, done }]),
    [update],
  );

  // A fresh `?? []` would be a new array on every render, so the memo below would
  // never hit. Hold a stable empty list instead.
  const items = useMemo(() => checklistQuery.data ?? [], [checklistQuery.data]);
  const isDone = useCallback(
    (code: string, serverDone: boolean) => overrides[code] ?? serverDone,
    [overrides],
  );

  const { required, optional, outstanding } = useMemo(() => {
    const requiredItems = items.filter((item) => item.is_required);
    return {
      required: requiredItems,
      optional: items.filter((item) => !item.is_required),
      outstanding: requiredItems.filter((item) => !isDone(item.code, item.is_done)),
    };
  }, [items, isDone]);

  const allDone = outstanding.length === 0 && required.length > 0;

  if (checklistQuery.isLoading) {
    return (
      <Screen testID="partner-checklist-screen">
        <LoadingState />
      </Screen>
    );
  }

  if (checklistQuery.isError) {
    return (
      <Screen testID="partner-checklist-screen">
        <ErrorState error={checklistQuery.error} onRetry={() => void checklistQuery.refetch()} />
      </Screen>
    );
  }

  return (
    <Screen
      testID="partner-checklist-screen"
      onRefresh={() => void checklistQuery.refetch()}
      refreshing={checklistQuery.isRefetching}
      bottomInset={96}
    >
      <SectionTitle
        action={
          allDone ? (
            <Badge label="Ready to complete" tone="success" icon="checkmark-circle" />
          ) : (
            <Badge
              label={`${outstanding.length} left`}
              tone="warning"
              icon="alert-circle"
              testID="checklist-outstanding-badge"
            />
          )
        }
      >
        Service checklist
      </SectionTitle>
      <Text style={[type.caption, { color: colors.mutedText, marginBottom: spacing.md }]}>
        Each step saves as you tap it. Required steps must be done before the job can be
        completed.
      </Text>

      {items.length === 0 ? (
        <EmptyState
          title="No checklist"
          message="This service does not have a checklist configured."
          icon="list"
        />
      ) : null}

      {required.length > 0 ? (
        <Card>
          <Text style={[type.captionStrong, { color: colors.mutedText, marginBottom: spacing.xs }]}>
            Required
          </Text>
          {required.map((item) => (
            <View key={item.id}>
              <Checkbox
                testID={`checklist-${item.code}`}
                label={item.label}
                checked={isDone(item.code, item.is_done)}
                onToggle={() => toggle(item.code, !isDone(item.code, item.is_done))}
              />
              {item.notes ? (
                <Text style={[type.caption, { color: colors.mutedText, paddingLeft: 32 }]}>
                  {item.notes}
                </Text>
              ) : null}
            </View>
          ))}
        </Card>
      ) : null}

      {optional.length > 0 ? (
        <Card style={{ marginTop: spacing.md }}>
          <Text style={[type.captionStrong, { color: colors.mutedText, marginBottom: spacing.xs }]}>
            Optional
          </Text>
          {optional.map((item) => (
            <Checkbox
              key={item.id}
              testID={`checklist-${item.code}`}
              label={item.label}
              checked={isDone(item.code, item.is_done)}
              onToggle={() => toggle(item.code, !isDone(item.code, item.is_done))}
            />
          ))}
        </Card>
      ) : null}

      <Button
        label="Back to job"
        fullWidth
        style={{ marginTop: spacing.lg }}
        testID="checklist-back"
        onPress={() => router.back()}
      />
    </Screen>
  );
}
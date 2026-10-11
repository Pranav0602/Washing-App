/**
 * Masked chat for a booking.
 *
 * Phone numbers are never exchanged. The thread carries a masked contact handle and a
 * request-call action, so coordination happens without either party leaking a number.
 */
import { useCallback, useRef, useState } from 'react';

import { useLocalSearchParams } from 'expo-router';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  FlatList,
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { commsApi } from '@/api/endpoints';
import { commsKeys } from '@/query/keys';
import { formatDateTime } from '@/lib/format';
import { toDisplayMessage } from '@/lib/apiError';
import { Banner, Button, EmptyState, ErrorState, LoadingState, Screen } from '@/components/ui';
import { useTheme } from '@/theme';

export default function BookingCommsScreen() {
  const { reference } = useLocalSearchParams<{ reference: string }>();
  const queryClient = useQueryClient();
  const { colors, radius, spacing, type } = useTheme();

  const [draft, setDraft] = useState('');
  const listRef = useRef<FlatList>(null);

  const threadQuery = useQuery({
    queryKey: commsKeys.messages(reference ?? ''),
    queryFn: () => commsApi.messages(reference!),
    enabled: Boolean(reference),
    // A partner reply mid-wash matters, so poll gently rather than leaving the
    // customer staring at a stale thread.
    refetchInterval: 15_000,
  });

  const send = useMutation({
    mutationFn: () => commsApi.send(reference!, draft.trim()),
    onSuccess: () => {
      setDraft('');
      void queryClient.invalidateQueries({ queryKey: commsKeys.messages(reference!) });
      requestAnimationFrame(() => listRef.current?.scrollToEnd({ animated: true }));
    },
  });

  const requestCall = useMutation({
    mutationFn: () => commsApi.startCall(reference!),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: commsKeys.messages(reference!) });
    },
  });

  const onSend = useCallback(() => {
    if (draft.trim().length === 0 || send.isPending) return;
    send.mutate();
  }, [draft, send]);

  const messages = threadQuery.data ?? [];

  return (
    <Screen testID="booking-comms-screen" scrollable={false}>
      <Banner
        tone="info"
        title="Keep it here"
        message="Phone numbers are hidden. Use this thread so support can help if something goes wrong."
        testID="comms-masking-banner"
      />

      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 90 : 0}
      >
        {threadQuery.isLoading ? (
          <LoadingState />
        ) : threadQuery.isError ? (
          <ErrorState error={threadQuery.error} onRetry={() => void threadQuery.refetch()} />
        ) : messages.length === 0 ? (
          <EmptyState
            title="No messages yet"
            message="Say hello, share access details, or confirm the arrival window."
            icon="chatbubbles"
          />
        ) : (
          <FlatList
            ref={listRef}
            testID="comms-message-list"
            data={messages}
            keyExtractor={(item) => item.id}
            onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: false })}
            contentContainerStyle={{ paddingVertical: spacing.md }}
            renderItem={({ item }) => (
              <View style={{ alignItems: item.is_mine ? 'flex-end' : 'flex-start', marginBottom: spacing.sm }}>
                <View
                  style={[
                    styles.bubble,
                    {
                      backgroundColor: item.is_mine ? colors.tint : colors.surfaceAlt,
                      borderColor: item.is_mine ? colors.tint : colors.border,
                      maxWidth: '85%',
                    },
                  ]}
                >
                  <Text style={[type.body, { color: item.is_mine ? colors.surface : colors.text }]}>
                    {item.body}
                  </Text>
                  <Text
                    style={[
                      type.micro,
                      {
                        color: item.is_mine ? colors.surface : colors.mutedText,
                        marginTop: 2,
                        opacity: 0.8,
                      },
                    ]}
                  >
                    {item.sender} - {formatDateTime(item.created_at)}
                  </Text>
                </View>
              </View>
            )}
          />
        )}

        {requestCall.isError ? (
          <Text style={[type.caption, { color: colors.danger, paddingHorizontal: spacing.md }]}>
            {toDisplayMessage(requestCall.error)}
          </Text>
        ) : null}

        <View style={[styles.composer, { borderColor: colors.border, backgroundColor: colors.surface }]}>
          <TextInput
            testID="comms-input"
            value={draft}
            onChangeText={setDraft}
            placeholder="Type a message"
            placeholderTextColor={colors.mutedText}
            accessibilityLabel="Message"
            multiline
            style={[
              styles.input,
              { color: colors.text, borderRadius: radius.md, backgroundColor: colors.background },
              type.body,
            ]}
          />
          <Button
            label="Send"
            testID="comms-send"
            loading={send.isPending}
            disabled={draft.trim().length === 0}
            onPress={onSend}
          />
          <Button
            label="Call"
            variant="secondary"
            testID="comms-request-call"
            loading={requestCall.isPending}
            onPress={() => requestCall.mutate()}
          />
        </View>
      </KeyboardAvoidingView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  bubble: {
    borderWidth: 1,
    borderRadius: 14,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  composer: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: 8,
    borderTopWidth: 1,
    padding: 12,
  },
  input: {
    flex: 1,
    minHeight: 44,
    maxHeight: 120,
    borderWidth: 1,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
});
/**
 * In-app notification centre.
 *
 * Doubles as the polling fallback when push is unavailable, which the PDF requires:
 * every booking state change also writes an in-app notification.
 */

import { useCallback } from 'react';
import { useRouter } from 'expo-router';
import { FlatList, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';

import { notificationApi } from '@/api/endpoints';
import type { AppNotification } from '@/api/types';
import { notificationKeys } from '@/query/keys';
import { formatRelative } from '@/lib/format';
import { Badge, Button, EmptyState, ErrorState, SkeletonList } from '@/components/ui';
import { useTheme } from '@/theme';

export default function NotificationsScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors, spacing, type } = useTheme();
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: notificationKeys.all,
    queryFn: () => notificationApi.list({ limit: 50 }),
  });

  const markAllRead = useMutation({
    mutationFn: notificationApi.markAllRead,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: notificationKeys.all }),
  });

  const onRefresh = useCallback(() => {
    void query.refetch();
  }, [query]);

  const unread = query.data?.unread_count ?? 0;

  return (
    <View testID="notifications-screen" style={{ flex: 1, backgroundColor: colors.background }}>
      <FlatList
        data={query.data?.results ?? []}
        keyExtractor={(item) => item.id}
        contentContainerStyle={{
          padding: spacing.lg,
          paddingTop: insets.top + spacing.md,
          paddingBottom: insets.bottom + spacing.xl,
        }}
        refreshControl={
          <RefreshControl refreshing={query.isRefetching} onRefresh={onRefresh} tintColor={colors.tint} />
        }
        ListHeaderComponent={
          <View style={{ marginBottom: spacing.lg }}>
            <View style={styles.rowBetween}>
              <Text style={[type.title, { color: colors.text, flex: 1 }]}>Updates</Text>
              {unread > 0 ? <Badge label={`${unread} new`} tone="accent" /> : null}
            </View>
            {unread > 0 ? (
              <View style={{ marginTop: spacing.sm }}>
                <Button
                  testID="mark-all-read"
                  label="Mark all as read"
                  variant="ghost"
                  fullWidth={false}
                  onPress={() => markAllRead.mutate()}
                />
              </View>
            ) : null}
          </View>
        }
        renderItem={({ item }) => (
          <NotificationRow
            notification={item}
            onPress={() => {
              const reference = item.data?.booking_reference;
              if (typeof reference === 'string') router.push(`/booking/${reference}`);
            }}
          />
        )}
        ListEmptyComponent={
          query.isLoading ? (
            <SkeletonList count={3} />
          ) : query.isError ? (
            <ErrorState error={query.error} onRetry={onRefresh} title="Could not load your updates" />
          ) : (
            <EmptyState
              testID="no-notifications"
              title="No updates yet"
              message="Booking updates, arrivals and delays will appear here."
              icon="notifications-outline"
            />
          )
        }
      />
    </View>
  );
}

function NotificationRow({
  notification,
  onPress,
}: {
  notification: AppNotification;
  onPress: () => void;
}) {
  const { colors, spacing, type } = useTheme();
  const unread = !notification.is_read;

  const icon = (() => {
    switch (notification.kind) {
      case 'assignment':
        return 'person-outline' as const;
      case 'offer':
        return 'briefcase-outline' as const;
      case 'arrival':
        return 'car-outline' as const;
      case 'payment':
        return 'card-outline' as const;
      case 'support':
        return 'help-circle-outline' as const;
      case 'evidence':
        return 'camera-outline' as const;
      default:
        return 'notifications-outline' as const;
    }
  })();

  return (
    <View
      testID={`notification-${notification.id}`}
      style={[
        styles.row,
        {
          backgroundColor: unread ? colors.surfaceAlt : colors.surface,
          borderColor: colors.border,
          borderRadius: 12,
          padding: spacing.md,
          marginBottom: spacing.sm,
        },
      ]}>
      <Ionicons name={icon} size={20} color={unread ? colors.tint : colors.icon} />
      <View style={{ flex: 1, marginLeft: spacing.md }}>
        <Text style={[type.bodyStrong, { color: colors.text }]}>{notification.title}</Text>
        {notification.body ? (
          <Text style={[type.caption, { color: colors.mutedText, marginTop: 2 }]}>
            {notification.body}
          </Text>
        ) : null}
        <Text style={[type.caption, { color: colors.mutedText, marginTop: 4 }]}>
          {formatRelative(notification.created_at)}
        </Text>
      </View>
      {notification.data?.booking_reference ? (
        <Ionicons name="chevron-forward" size={16} color={colors.icon} onPress={onPress} />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  rowBetween: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  row: { flexDirection: 'row', alignItems: 'flex-start' },
});

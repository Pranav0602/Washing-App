/**
 * Partner profile: readiness blockers, kit checklist, skills and documents.
 *
 * The blockers list is the screen's main job: a partner who is not receiving offers
 * needs to know exactly which gate is closed and how to close it.
 */

import { useCallback, useState } from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { partnerApi } from '@/api/endpoints';
import { partnerKeys } from '@/query/keys';
import { formatDate } from '@/lib/format';
import { useSession } from '@/auth/SessionProvider';
import {
  Badge,
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

export default function PartnerProfileScreen() {
  const insets = useSafeAreaInsets();
  const { colors, spacing, type } = useTheme();
  const queryClient = useQueryClient();
  const { signOut, user } = useSession();
  const [actionError, setActionError] = useState<unknown>(null);

  const meQuery = useQuery({ queryKey: partnerKeys.me, queryFn: partnerApi.me });
  const equipmentQuery = useQuery({ queryKey: partnerKeys.equipment, queryFn: partnerApi.equipment });
  const documentsQuery = useQuery({ queryKey: partnerKeys.documents, queryFn: partnerApi.documents });

  const toggleEquipment = useMutation({
    mutationFn: (payload: { item_code: string; status: string }) => partnerApi.setEquipment([payload]),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: partnerKeys.equipment });
      void queryClient.invalidateQueries({ queryKey: partnerKeys.me });
    },
    onError: setActionError,
  });

  const me = meQuery.data;

  const onRefresh = useCallback(() => {
    void meQuery.refetch();
    void equipmentQuery.refetch();
    void documentsQuery.refetch();
  }, [documentsQuery, equipmentQuery, meQuery]);

  return (
    <ScrollView
      testID="partner-profile-screen"
      style={{ flex: 1, backgroundColor: colors.background }}
      contentContainerStyle={{
        padding: spacing.lg,
        paddingTop: insets.top + spacing.md,
        paddingBottom: insets.bottom + spacing.xl,
      }}
      refreshControl={
        <RefreshControl
          refreshing={meQuery.isRefetching || equipmentQuery.isRefetching}
          onRefresh={onRefresh}
          tintColor={colors.tint}
        />
      }>
      <Text style={[type.title, { color: colors.text }]}>Profile</Text>

      {meQuery.isLoading ? (
        <View style={{ marginTop: spacing.lg }}>
          <SkeletonList count={2} />
        </View>
      ) : meQuery.isError ? (
        <ErrorState error={meQuery.error} onRetry={onRefresh} title="Could not load your profile" />
      ) : me ? (
        <>
          <Card testID="partner-identity">
            <DetailRow label="Name" value={me.display_name} />
            <DetailRow label="Phone" value={me.masked_phone} />
            <DetailRow label="Account" value={user?.phone ?? '—'} />
            <View style={styles.rowBetween}>
              <DetailRow label="Status" value={me.status_label} />
            </View>
            <View style={[styles.rowBetween, { marginTop: spacing.sm }]}>
              <Badge
                label={me.readiness.eligible_for_offers ? 'Ready for offers' : 'Not ready'}
                tone={me.readiness.eligible_for_offers ? 'success' : 'warning'}
              />
            </View>
          </Card>

          <SectionTitle>What is blocking offers</SectionTitle>
          {me.readiness.blockers.length === 0 ? (
            <Banner
              testID="no-blockers"
              tone="success"
              message="Everything is in order. You will receive offers while on shift."
            />
          ) : (
            <Card testID="blocker-list">
              {me.readiness.blockers.map((blocker, index) => (
                <View key={`${blocker.code}-${index}`} style={{ marginBottom: spacing.md }}>
                  <View style={styles.rowBetween}>
                    <Text style={[type.bodyStrong, { color: colors.text, flex: 1 }]}>
                      {blocker.message}
                    </Text>
                  </View>
                  {blocker.detail ? (
                    <Text style={[type.caption, { color: colors.mutedText, marginTop: 2 }]}>
                      {blocker.detail}
                    </Text>
                  ) : null}
                </View>
              ))}
            </Card>
          )}

          <SectionTitle>Compliance dates</SectionTitle>
          <Card>
            <DetailRow
              label="Insurance expires"
              value={me.insurance_expires_at ? formatDate(me.insurance_expires_at) : 'Not on file'}
              tone={me.insurance_expires_at ? 'default' : 'danger'}
            />
            <DetailRow
              label="Certification expires"
              value={me.certification_expires_at ? formatDate(me.certification_expires_at) : 'Not recorded'}
            />
            <DetailRow
              label="Assessment"
              value={me.assessment_passed_at ? formatDate(me.assessment_passed_at) : 'Not completed'}
            />
          </Card>

          <SectionTitle>Kit checklist</SectionTitle>
          {equipmentQuery.isLoading ? (
            <SkeletonList count={2} />
          ) : (equipmentQuery.data ?? []).length === 0 ? (
            <Text style={[type.caption, { color: colors.mutedText }]}>No kit items issued yet.</Text>
          ) : (
            (equipmentQuery.data ?? []).map((item) => (
              <ToggleRow
                key={item.id}
                testID={`kit-${item.item_code}`}
                label={item.name}
                description={item.required ? 'Required before you can take work.' : 'Recommended.'}
                value={item.status === 'present'}
                onValueChange={(next) =>
                  toggleEquipment.mutate({ item_code: item.item_code, status: next ? 'present' : 'missing' })
                }
              />
            ))
          )}

          <SectionTitle>Documents</SectionTitle>
          {documentsQuery.isLoading ? (
            <SkeletonList count={1} />
          ) : (documentsQuery.data ?? []).length === 0 ? (
            <Text style={[type.caption, { color: colors.mutedText }]}>
              No documents uploaded. Operations will ask for these.
            </Text>
          ) : (
            (documentsQuery.data ?? []).map((document) => (
              <Card key={document.id} testID={`document-${document.id}`}>
                <View style={styles.rowBetween}>
                  <Text style={[type.bodyStrong, { color: colors.text, flex: 1 }]}>
                    {document.doc_type_label}
                  </Text>
                  <Badge
                    label={document.verification_status}
                    tone={
                      document.verification_status === 'verified'
                        ? 'success'
                        : document.verification_status === 'rejected'
                          ? 'danger'
                          : 'warning'
                    }
                  />
                </View>
                {document.expires_at ? (
                  <Text style={[type.caption, { color: document.is_expired ? colors.danger : colors.mutedText, marginTop: 4 }]}>
                    Expires {formatDate(document.expires_at)}
                  </Text>
                ) : null}
              </Card>
            ))
          )}

          {actionError ? (
            <ErrorState error={actionError} onRetry={() => setActionError(null)} title="Could not update your kit" />
          ) : null}

          <View style={{ marginTop: spacing.xl }}>
            <Button testID="partner-sign-out" label="Sign out" variant="secondary" onPress={() => void signOut()} />
          </View>
        </>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  rowBetween: { flexDirection: 'row', alignItems: 'center', gap: 8 },
});

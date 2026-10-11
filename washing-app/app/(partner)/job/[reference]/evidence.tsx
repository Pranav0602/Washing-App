/**
 * Evidence capture for a job.
 *
 * Photos are the record that protects both sides in a dispute, so the screen is built
 * around capture, not upload: each photo is taken with the camera, uploaded immediately,
 * and listed with its server-side upload status. A failed upload stays visible and
 * retryable rather than silently disappearing.
 */
import { useCallback, useState } from 'react';

import { useLocalSearchParams } from 'expo-router';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import * as ImagePicker from 'expo-image-picker';
import { Alert, Image, Text, View } from 'react-native';

import { dispatchApi, evidenceApi, type EvidenceUpload } from '@/api/endpoints';
import { bookingKeys } from '@/query/keys';
import { toDisplayMessage } from '@/lib/apiError';
import { formatDateTime } from '@/lib/format';
import {
  Badge,
  Banner,
  Button,
  Card,
  ChipGroup,
  DetailRow,
  EmptyState,
  ErrorState,
  LoadingState,
  Screen,
  SectionTitle,
} from '@/components/ui';
import { useTheme } from '@/theme';

const EVIDENCE_TYPES = [
  { value: 'pre_condition', label: 'Before' },
  { value: 'post_service', label: 'After' },
  { value: 'damage', label: 'Damage' },
  { value: 'other', label: 'Other' },
];

/** Stable-enough client id; the server uses it to de-duplicate retried uploads. */
function clientPhotoId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export default function PartnerEvidenceScreen() {
  const { reference } = useLocalSearchParams<{ reference: string }>();
  const queryClient = useQueryClient();
  const { colors, radius, spacing, type } = useTheme();

  const [evidenceType, setEvidenceType] = useState('pre_condition');

  // The job carries the server's own required-evidence map, so the UI reflects policy
  // rather than a hardcoded guess about what this service needs.
  const jobQuery = useQuery({
    queryKey: bookingKeys.job(reference ?? ''),
    queryFn: () => dispatchApi.job(reference!),
    enabled: Boolean(reference),
  });

  const evidenceQuery = useQuery({
    queryKey: bookingKeys.evidence(reference ?? ''),
    queryFn: () => evidenceApi.list(reference!),
    enabled: Boolean(reference),
    refetchInterval: 10_000,
  });

  const upload = useMutation({
    mutationFn: (payload: EvidenceUpload) => evidenceApi.upload(reference!, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: bookingKeys.evidence(reference!) });
      void queryClient.invalidateQueries({ queryKey: bookingKeys.job(reference!) });
    },
  });

  const [pending, setPending] = useState<{ id: string; uri: string }[]>([]);

  const capture = useCallback(async () => {
    const permission = await ImagePicker.requestCameraPermissionsAsync();
    if (!permission.granted) {
      Alert.alert('Camera needed', 'Allow camera access to capture job evidence.');
      return;
    }

    const result = await ImagePicker.launchCameraAsync({
      quality: 0.6,
      exif: false,
      mediaTypes: ['images'],
    });
    if (result.canceled || result.assets.length === 0) return;

    const asset = result.assets[0];
    const id = clientPhotoId();
    setPending((current) => [...current, { id, uri: asset.uri }]);

    const existing = evidenceQuery.data?.length ?? 0;
    upload.mutate(
      {
        evidence_type: evidenceType as EvidenceUpload['evidence_type'],
        captured_at: new Date().toISOString(),
        client_photo_id: id,
        sequence: existing + pending.length + 1,
        checks: {},
        file: {
          uri: asset.uri,
          name: asset.fileName ?? `${id}.jpg`,
          type: asset.mimeType ?? 'image/jpeg',
        },
      },
      {
        onSettled: () => setPending((current) => current.filter((item) => item.id !== id)),
      },
    );
  }, [evidenceType, evidenceQuery.data?.length, pending.length, upload]);

  const checklist = jobQuery.data?.checklist ?? [];
  const requiredTypes = Object.keys(jobQuery.data?.required_evidence ?? {});
  const evidence = evidenceQuery.data ?? [];
  const capturedTypes = new Set(evidence.map((item) => item.evidence_type));
  const missingRequired = requiredTypes.filter((type) => !capturedTypes.has(type as never));

  return (
    <Screen
      testID="partner-evidence-screen"
      onRefresh={() => void evidenceQuery.refetch()}
      refreshing={evidenceQuery.isRefetching}
      bottomInset={112}
    >
      <SectionTitle>Photo evidence</SectionTitle>
      <Text style={[type.caption, { color: colors.mutedText, marginBottom: spacing.md }]}>
        Photos are timestamped and attached to this job. Capture the vehicle before you start
        and again when you finish.
      </Text>

      {missingRequired.length > 0 ? (
        <Banner
          tone="warning"
          title="Photos still needed"
          message={`This service requires: ${missingRequired.join(', ').replace(/_/g, ' ')}.`}
          testID="evidence-required-banner"
        />
      ) : (
        <Banner
          tone="success"
          title="Required photos captured"
          message="You can finish the job once the checklist is done."
          testID="evidence-complete-banner"
        />
      )}

      <Card style={{ marginTop: spacing.md }}>
        <Text style={[type.captionStrong, { color: colors.mutedText, marginBottom: spacing.sm }]}>
          What are you photographing?
        </Text>
        <ChipGroup
          options={EVIDENCE_TYPES}
          value={evidenceType}
          onChange={setEvidenceType}
          testID="evidence-type"
        />
      </Card>

      {checklist.length > 0 ? (
        <Card style={{ marginTop: spacing.md }}>
          <Text style={[type.captionStrong, { color: colors.mutedText, marginBottom: spacing.xs }]}>
            Checklist progress
          </Text>
          {checklist.slice(0, 4).map((item) => (
            <DetailRow
              key={item.id}
              label={item.label}
              value={item.is_done ? 'Done' : 'Pending'}
              tone={item.is_done ? 'success' : 'default'}
              testID={`evidence-check-${item.code}`}
            />
          ))}
        </Card>
      ) : null}

      <SectionTitle>Captured</SectionTitle>

      {evidenceQuery.isLoading ? (
        <LoadingState />
      ) : evidenceQuery.isError ? (
        <ErrorState error={evidenceQuery.error} onRetry={() => void evidenceQuery.refetch()} />
      ) : evidence.length === 0 && pending.length === 0 ? (
        <EmptyState
          title="No photos yet"
          message="Capture the vehicle condition before you start."
          icon="camera"
          action={{ label: 'Take a photo', onPress: () => void capture() }}
        />
      ) : (
        <View>
          {pending.map((item) => (
            <Card key={item.id} style={{ marginBottom: spacing.sm }} testID={`evidence-pending-${item.id}`}>
              <Text style={[type.captionStrong, { color: colors.mutedText }]}>Uploading</Text>
              <Image
                source={{ uri: item.uri }}
                style={{ width: '100%', height: 160, borderRadius: radius.md, marginTop: spacing.sm }}
                resizeMode="cover"
              />
            </Card>
          ))}

          {evidence.map((item) => (
            <Card key={item.id} style={{ marginBottom: spacing.sm }} testID={`evidence-${item.id}`}>
              <View style={styles.row}>
                <Text style={[type.bodyStrong, { color: colors.text, flex: 1 }]}>
                  {item.evidence_type_label}
                </Text>
                <Badge
                  label={item.upload_status}
                  tone={item.upload_status === 'ready' ? 'success' : 'warning'}
                />
              </View>
              <Text style={[type.caption, { color: colors.mutedText, marginTop: 2 }]}>
                {formatDateTime(item.captured_at)}
              </Text>
              {item.legal_hold ? (
                <Text style={[type.caption, { color: colors.warning, marginTop: 2 }]}>
                  Retained under legal hold
                </Text>
              ) : null}
            </Card>
          ))}
        </View>
      )}

      {upload.isError ? (
        <Banner
          tone="danger"
          title="Upload failed"
          message={toDisplayMessage(upload.error)}
          testID="evidence-upload-error"
        />
      ) : null}

      <Button
        label={upload.isPending ? 'Uploading' : 'Take a photo'}
        icon="camera"
        testID="evidence-capture"
        fullWidth
        style={{ marginTop: spacing.lg }}
        loading={upload.isPending}
        disabled={upload.isPending || !reference}
        onPress={() => void capture()}
      />
    </Screen>
  );
}

const styles = {
  row: { flexDirection: 'row' as const, alignItems: 'center' as const, gap: 8 },
};

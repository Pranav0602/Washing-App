/**
 * Report a problem with a job.
 *
 * Creates a support case against the booking and can attach photos the customer has
 * already uploaded, so ops can adjudicate without going back for more evidence.
 */
import { useState } from 'react';

import { useLocalSearchParams, useRouter } from 'expo-router';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Text, TextInput } from 'react-native';

import { bookingApi, evidenceApi } from '@/api/endpoints';
import {
  Button,
  Card,
  Checkbox,
  ChipGroup,
  LoadingState,
  Screen,
  SectionTitle,
} from '@/components/ui';
import { toDisplayMessage } from '@/lib/apiError';
import { formatDateTime } from '@/lib/format';
import { reportCategoryOptions, type ReportCategory } from '@/lib/schemas';
import { bookingKeys } from '@/query/keys';
import { useTheme } from '@/theme';

const CATEGORIES = reportCategoryOptions;

const MIN_LENGTH = 10;

export default function ReportIssueScreen() {
  const { reference } = useLocalSearchParams<{ reference: string }>();
  const router = useRouter();
  const { colors, radius, spacing, type } = useTheme();

  const [category, setCategory] = useState<ReportCategory>('damage');
  const [description, setDescription] = useState('');
  const [evidenceIds, setEvidenceIds] = useState<string[]>([]);
  const [touched, setTouched] = useState(false);

  const evidenceQuery = useQuery({
    queryKey: bookingKeys.evidence(reference ?? ''),
    queryFn: () => evidenceApi.list(reference!),
    enabled: Boolean(reference),
  });

  const tooShort = description.trim().length < MIN_LENGTH;
  const descriptionError = touched && tooShort ? 'Please describe the issue a little more.' : undefined;

  const submit = useMutation({
    mutationFn: () =>
      bookingApi.reportIssue(reference!, {
        category,
        description: description.trim(),
        ...(evidenceIds.length > 0 ? { evidence_ids: evidenceIds } : {}),
      }),
    onSuccess: () => router.replace(`/booking/${reference}`),
  });

  const toggleEvidence = (id: string) => {
    setEvidenceIds((current) =>
      current.includes(id) ? current.filter((value) => value !== id) : [...current, id],
    );
  };

  const evidence = evidenceQuery.data ?? [];

  return (
    <Screen testID="report-issue-screen">
      <SectionTitle>Report a problem</SectionTitle>
      <Text style={[type.caption, { color: colors.mutedText, marginBottom: spacing.md }]}>
        Support reviews every report. If something is damaged, attach photos you already
        uploaded so we can act faster.
      </Text>

      <Card>
        <Text style={[type.captionStrong, { color: colors.mutedText, marginBottom: spacing.sm }]}>
          What went wrong?
        </Text>
        <ChipGroup
          options={CATEGORIES}
          value={category}
          onChange={setCategory}
          testID="report-category"
        />
      </Card>

      <Card style={{ marginTop: spacing.md }}>
        <Text style={[type.captionStrong, { color: colors.mutedText, marginBottom: spacing.sm }]}>
          Describe the issue
        </Text>
        <TextInput
          testID="report-description"
          value={description}
          onChangeText={setDescription}
          onBlur={() => setTouched(true)}
          placeholder="What happened, and where on the vehicle?"
          placeholderTextColor={colors.mutedText}
          multiline
          textAlignVertical="top"
          accessibilityLabel="Description of the problem"
          style={[
            {
              borderWidth: 1,
              borderRadius: radius.md,
              borderColor: descriptionError ? colors.danger : colors.border,
              padding: spacing.md,
              minHeight: 110,
              color: colors.text,
            },
            type.body,
          ]}
        />
        {descriptionError ? (
          <Text style={[type.caption, { color: colors.danger, marginTop: spacing.xs }]}>
            {descriptionError}
          </Text>
        ) : null}
      </Card>

      <Card style={{ marginTop: spacing.md }}>
        <Text style={[type.captionStrong, { color: colors.mutedText, marginBottom: spacing.xs }]}>
          Attach photos (optional)
        </Text>
        {evidenceQuery.isLoading ? (
          <LoadingState />
        ) : evidence.length === 0 ? (
          <Text style={[type.caption, { color: colors.mutedText }]}>
            No photos have been uploaded for this job yet.
          </Text>
        ) : (
          evidence.map((item) => (
            <Checkbox
              key={item.id}
              testID={`report-evidence-${item.id}`}
              label={`${item.evidence_type_label} - ${formatDateTime(item.captured_at)}`}
              checked={evidenceIds.includes(item.id)}
              onToggle={() => toggleEvidence(item.id)}
            />
          ))
        )}
      </Card>

      {submit.isError ? (
        <Card style={{ marginTop: spacing.md, borderColor: colors.danger }}>
          <Text style={[type.body, { color: colors.danger }]}>{toDisplayMessage(submit.error)}</Text>
        </Card>
      ) : null}

      <Button
        label="Submit report"
        testID="report-submit"
        fullWidth
        style={{ marginTop: spacing.lg }}
        loading={submit.isPending}
        disabled={tooShort}
        onPress={() => {
          setTouched(true);
          if (!tooShort) submit.mutate();
        }}
      />
      <Button
        label="Cancel"
        variant="ghost"
        testID="report-cancel"
        style={{ marginTop: spacing.sm }}
        onPress={() => router.back()}
      />
    </Screen>
  );
}

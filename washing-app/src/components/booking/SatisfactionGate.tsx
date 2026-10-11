/**
 * Post-wash satisfaction gate.
 *
 * Shown once the partner marks the wash completed. The customer inspects the
 * evidence photos; paying is unlocked only after they confirm satisfaction.
 */

import { useState } from 'react';
import { Image, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useMutation } from '@tanstack/react-query';

import { bookingApi } from '@/api/endpoints';
import type { Evidence } from '@/api/types';
import {
  Banner,
  Button,
  Card,
  ErrorState,
  SectionTitle,
} from '@/components/ui';
import { useTheme } from '@/theme';

const DISPUTE_AREAS = [
  { id: 'rims', label: 'Rims' },
  { id: 'interior_windows', label: 'Interior windows' },
  { id: 'rear_bumper', label: 'Rear bumper' },
  { id: 'exterior_paint', label: 'Exterior paint' },
  { id: 'interior_seats', label: 'Interior seats' },
];

export function SatisfactionGate({
  bookingReference,
  evidence,
  onSatisfied,
}: {
  bookingReference: string;
  evidence: Evidence[];
  onSatisfied: () => void;
}) {
  const { colors, spacing, type } = useTheme();
  const [disputeOpen, setDisputeOpen] = useState(false);
  const [areas, setAreas] = useState<string[]>([]);
  const [notes, setNotes] = useState('');
  const [reported, setReported] = useState(false);

  const report = useMutation({
    mutationFn: () =>
      bookingApi.reportIssue(bookingReference, {
        category: 'touch_up_request',
        description: `Areas needing attention: ${areas.join(', ') || 'general'}. ${notes}`.trim(),
      }),
    onSuccess: () => {
      setReported(true);
      setDisputeOpen(false);
    },
  });

  const postWash = evidence.filter((e) => e.evidence_type === 'post_service');
  const preWash = evidence.filter((e) => e.evidence_type === 'pre_condition');

  return (
    <>
      <Card testID="satisfaction-gate">
        <Text style={[type.heading, { color: colors.text }]}>Your Car Wash is Finished!</Text>
        <Text style={[type.caption, { color: colors.mutedText, marginTop: spacing.xs }]}>
          Inspect the photos below, then confirm how it went.
        </Text>

        <SectionTitle>Evidence photos</SectionTitle>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} testID="evidence-carousel">
          {[...preWash, ...postWash].map((item) => (
            <View key={item.id} style={{ marginRight: spacing.sm }}>
              {item.file_url ? (
                <Image
                  source={{ uri: `${process.env.EXPO_PUBLIC_API_URL ?? ''}${item.file_url}` }}
                  style={styles.photo}
                />
              ) : (
                <View style={[styles.photo, styles.photoPlaceholder]}>
                  <Text>📷</Text>
                </View>
              )}
              <Text style={[type.caption, { color: colors.mutedText, marginTop: 4 }]}>
                {item.evidence_type_label}
              </Text>
            </View>
          ))}
          {[...preWash, ...postWash].length === 0 ? (
            <Text style={[type.caption, { color: colors.mutedText }]}>
              No evidence photos available yet.
            </Text>
          ) : null}
        </ScrollView>

        {reported ? (
          <Banner
            testID="dispute-filed-banner"
            tone="warning"
            title="Touch-up requested"
            message="Payment is held while our team reviews your case."
          />
        ) : null}

        {report.isError ? (
          <ErrorState
            testID="dispute-error"
            error={report.error}
            onRetry={() => report.reset()}
            title="Could not file the report"
          />
        ) : null}

        <View style={{ gap: spacing.sm, marginTop: spacing.md }}>
          <Button
            testID="satisfied-button"
            label="I am Satisfied — Proceed to Payment"
            onPress={onSatisfied}
            disabled={reported}
          />
          <Button
            testID="not-satisfied-button"
            label="I'm Not Satisfied / Need Touch-Up"
            variant="secondary"
            onPress={() => setDisputeOpen(true)}
          />
        </View>
      </Card>

      {disputeOpen ? (
      <View testID="dispute-modal" style={{ flex: 1, backgroundColor: colors.background, padding: spacing.lg }}>
          <Text style={[type.title, { color: colors.text }]}>Tell us what to fix</Text>
          <Text style={[type.body, { color: colors.mutedText, marginVertical: spacing.sm }]}>
            Select the areas that need attention. Payment is held until it is resolved.
          </Text>

          <SectionTitle>Areas</SectionTitle>
          <View style={styles.chipRow}>
            {DISPUTE_AREAS.map((area) => {
              const selected = areas.includes(area.id);
              return (
                <Button
                  key={area.id}
                  testID={`dispute-area-${area.id}`}
                  label={area.label}
                  variant={selected ? 'primary' : 'secondary'}
                  fullWidth={false}
                  onPress={() =>
                    setAreas((current) =>
                      current.includes(area.id)
                        ? current.filter((id) => id !== area.id)
                        : [...current, area.id],
                    )
                  }
                  style={{ marginRight: spacing.xs }}
                />
              );
            })}
          </View>

          <SectionTitle>Notes</SectionTitle>
          <TextInput
            testID="dispute-notes"
            value={notes}
            onChangeText={setNotes}
            placeholder="Add details for the partner or ops"
            multiline
            style={{
              borderWidth: 1,
              borderColor: colors.border,
              borderRadius: 8,
              padding: spacing.md,
              color: colors.text,
              minHeight: 100,
            }}
          />

          <View style={{ gap: spacing.sm, marginTop: spacing.lg }}>
            <Button
              testID="submit-dispute"
              label="Submit touch-up request"
              onPress={() => report.mutate()}
              loading={report.isPending}
            />
            <Button
              testID="cancel-dispute"
              label="Back"
              variant="ghost"
              onPress={() => setDisputeOpen(false)}
            />
          </View>
        </View>
      ) : null}
    </>
  );
}

const styles = StyleSheet.create({
  photo: { width: 120, height: 120, borderRadius: 12 },
  photoPlaceholder: { alignItems: 'center', justifyContent: 'center' },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
});

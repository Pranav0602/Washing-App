/**
 * Partner application.
 *
 * A partner application is deliberately light on the form: the PDF treats verification,
 * insurance, kit and a practical assessment as *separate, audited* gates, so asking for
 * documents here would imply they can be self-certified. What is collected here is
 * intent and declared capability; everything else is verified by operations.
 */

import { useState } from 'react';
import { useRouter } from 'expo-router';
import { Controller, useForm, type Control, type FieldValues, type Path } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { StyleSheet, Switch, Text, View } from 'react-native';

import { authApi, catalogApi } from '@/api/endpoints';
import { useQuery } from '@tanstack/react-query';
import { queryClient } from '@/query/queryClient';
import { catalogKeys } from '@/query/keys';
import {
  partnerRegistrationSchema,
  type PartnerRegistrationValues,
} from '@/lib/schemas';
import { useSession } from '@/auth/SessionProvider';
import { Banner, Button, ErrorState, LoadingState, Screen, TextField } from '@/components/ui';
import { useTheme } from '@/theme';

export default function PartnerRegistrationScreen() {
  const router = useRouter();
  const { colors, spacing, type } = useTheme();
  const { refreshUser } = useSession();

  const [submitError, setSubmitError] = useState<unknown>(null);
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);

  const { control, handleSubmit, formState, setValue } = useForm<PartnerRegistrationValues>({
    resolver: zodResolver(partnerRegistrationSchema),
    mode: 'onBlur',
    defaultValues: {
      display_name: '',
      bio: '',
      skills: [],
      payout_account_ref: '',
      terms: false,
      privacy: false,
      location: false,
      evidence: true,
    },
  });

  const servicesQuery = useQuery({
    queryKey: catalogKeys.services(),
    queryFn: () => catalogApi.services(),
  });

  const onSubmit = handleSubmit(async (values) => {
    setSubmitError(null);
    try {
      await authApi.registerPartner({
        display_name: values.display_name,
        bio: values.bio ?? '',
        skills: selectedSkills,
        equipment: [],
        payout_account_ref: values.payout_account_ref ?? '',
        consent: {
          terms: values.terms,
          privacy: values.privacy,
          location: values.location,
          evidence: values.evidence,
        },
      });

      await refreshUser();
      queryClient.clear();
      router.replace('/(partner)');
    } catch (error) {
      setSubmitError(error);
    }
  });

  const errors = formState.errors;

  const toggleSkill = (code: string) => {
    const next = selectedSkills.includes(code)
      ? selectedSkills.filter((item) => item !== code)
      : [...selectedSkills, code];
    setSelectedSkills(next);
    setValue('skills', next, { shouldValidate: true });
  };

  return (
    <Screen testID="register-partner-screen">
      <View style={{ marginBottom: spacing.xl }}>
        <Text style={[type.title, { color: colors.text }]}>Apply to wash cars</Text>
        <Text style={[type.body, { color: colors.mutedText, marginTop: spacing.sm }]}>
          You will verify your identity, documents and kit before you can receive jobs.
        </Text>
      </View>

      {submitError ? (
        <ErrorState
          testID="partner-register-error"
          error={submitError}
          onRetry={() => setSubmitError(null)}
          title="Could not submit your application"
        />
      ) : null}

      <TextField
        control={control}
        name="display_name"
        label="Name customers will see"
        placeholder="Rapid Wash Services"
        required
      />
      <Gap />
      <TextField
        control={control}
        name="bio"
        label="About you (optional)"
        placeholder="What you specialise in, areas you cover."
        multiline
      />

      <Gap />
      <Text
        accessibilityRole="header"
        style={[type.heading, { color: colors.text, marginBottom: spacing.sm }]}>
        What can you wash?
      </Text>

      {servicesQuery.isLoading ? (
        <LoadingState label="Loading services" />
      ) : servicesQuery.isError ? (
        <ErrorState error={servicesQuery.error} onRetry={() => void servicesQuery.refetch()} />
      ) : (
        <View style={[styles.chipWrap, { gap: spacing.sm }]}>
          {servicesQuery.data?.map((service) => {
            const selected = selectedSkills.includes(service.code);
            return (
              <Button
                key={service.code}
                testID={`skill-${service.code}`}
                label={service.name}
                variant={selected ? 'primary' : 'secondary'}
                fullWidth={false}
                onPress={() => toggleSkill(service.code)}
                style={{ marginBottom: spacing.sm }}
              />
            );
          })}
        </View>
      )}
      <Text style={[type.caption, { color: colors.mutedText, marginTop: spacing.sm }]}>
        You can add more skills later. Operations verifies each one before you take that work.
      </Text>

      <Gap />
      <TextField
        control={control}
        name="payout_account_ref"
        label="Payout account reference (optional)"
        placeholder="Provider payout token"
        hint="A reference from your payout provider, not your bank details. We never store bank account numbers."
        autoCapitalize="none"
      />

      <View style={{ height: spacing.lg }} />

      <ConsentRow
        testID="partner-consent-terms"
        control={control}
        name="terms"
        label="I accept the partner terms"
        description="Payout terms, service standards and the cancellation policy."
        error={errors.terms?.message as string | undefined}
      />
      <ConsentRow
        testID="partner-consent-privacy"
        control={control}
        name="privacy"
        label="I accept the privacy notice"
        description="How your location and documents are handled."
        error={errors.privacy?.message as string | undefined}
      />
      <ConsentRow
        testID="partner-consent-location"
        control={control}
        name="location"
        label="I agree to location sharing while on shift or on a job"
        description="Precise location is collected only during a declared shift or an active job, and is deleted on a short retention cycle. You will always see whether it is on."
        error={errors.location?.message as string | undefined}
      />
      <ConsentRow
        testID="partner-consent-evidence"
        control={control}
        name="evidence"
        label="Photo evidence"
        description="You photograph the vehicle before and after the wash."
        optional
      />

      <View style={{ marginTop: spacing.lg }}>
        <Banner
          testID="partner-readiness-notice"
          tone="info"
          title="What happens next"
          message="Operations verifies your documents and kit, then you complete a short practical assessment. Offers stay switched off until all three are done."
        />
      </View>

      <Button
        testID="register-partner-submit"
        label="Submit application"
        onPress={onSubmit}
        loading={formState.isSubmitting}
      />

      <View style={{ marginTop: spacing.sm }}>
        <Button
          testID="switch-to-customer"
          label="I want to book a wash instead"
          variant="ghost"
          onPress={() => router.replace('/(auth)/register/customer')}
        />
      </View>
    </Screen>
  );
}

function Gap() {
  const { spacing } = useTheme();
  return <View style={{ height: spacing.md }} />;
}

function ConsentRow<T extends FieldValues>({
  control,
  name,
  label,
  description,
  error,
  optional = false,
  testID,
}: {
  control: Control<T>;
  name: Path<T>;
  label: string;
  description: string;
  error?: string;
  optional?: boolean;
  testID?: string;
}) {
  const { colors, spacing, type } = useTheme();

  return (
    <View style={{ marginBottom: spacing.sm }}>
      <View style={[styles.consentRow, { borderColor: colors.border }]}>
        <View style={{ flex: 1, paddingRight: spacing.md }}>
          <Text style={[type.body, { color: colors.text }]}>
            {label}
            {optional ? '' : ' *'}
          </Text>
          <Text style={[type.caption, { color: colors.mutedText, marginTop: 2 }]}>
            {description}
          </Text>
        </View>
        <Controller
          control={control}
          name={name}
          render={({ field: { onChange, value } }) => (
            <Switch
              testID={testID}
              value={Boolean(value)}
              onValueChange={onChange}
              trackColor={{ true: colors.tint, false: colors.border }}
            />
          )}
        />
      </View>
      {error ? (
        <Text style={[type.caption, { color: colors.danger, marginTop: spacing.xs }]}>{error}</Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  chipWrap: { flexDirection: 'row', flexWrap: 'wrap' },
  consentRow: { flexDirection: 'row', alignItems: 'center', borderWidth: 1, padding: 12, borderRadius: 12 },
});

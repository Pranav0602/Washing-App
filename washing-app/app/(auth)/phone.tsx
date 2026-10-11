/**
 * Step 1: phone entry.
 */

import { useState } from 'react';
import { useRouter } from 'expo-router';
import { Controller, useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { StyleSheet, Text, View } from 'react-native';

import { authApi } from '@/api/endpoints';
import { toDisplayMessage } from '@/lib/apiError';
import { phoneSchemaForm, type PhoneFormValues } from '@/lib/schemas';
import { Button, ErrorState, Screen, TextField } from '@/components/ui';
import { useTheme } from '@/theme';

export default function PhoneScreen() {
  const router = useRouter();
  const { colors, spacing, type } = useTheme();
  const [requestError, setRequestError] = useState<unknown>(null);
  const [isLoading, setIsLoading] = useState(false);

  const { control, handleSubmit, formState } = useForm<PhoneFormValues>({
    resolver: zodResolver(phoneSchemaForm),
    defaultValues: { phone: '' },
    mode: 'onSubmit',
  });

  const onSubmit = handleSubmit(async ({ phone }) => {
    setIsLoading(true);
    setRequestError(null);
    try {
      const result = await authApi.requestOtp(phone);
      router.push({
        pathname: '/(auth)/otp',
        params: { challengeId: result.challenge_id, phone },
      });
    } catch (error) {
      setRequestError(error);
    } finally {
      setIsLoading(false);
    }
  });

  return (
    <Screen testID="phone-screen">
      <View style={[styles.header, { marginBottom: spacing.xl }]}>
        <Text style={[type.display, { color: colors.text }]}>Car wash, booked in minutes</Text>
        <Text style={[type.body, { color: colors.mutedText, marginTop: spacing.sm }]}>
          Enter your phone number and we will send a verification code.
        </Text>
      </View>

      {requestError ? (
        <ErrorState error={requestError} onRetry={() => setRequestError(null)} title="Could not send code" />
      ) : null}

      <Controller
        control={control}
        name="phone"
        render={({ field: { onChange, onBlur, value } }) => (
          <TextField
            control={control}
            name="phone"
            label="Phone number"
            placeholder="9876543210"
            keyboardType="phone-pad"
            autoComplete="tel"
            textContentType="telephoneNumber"
            autoCapitalize="none"
            required
            hint="We only use this to verify your account and for job updates."
            value={value}
            onChange={onChange}
            onBlur={onBlur}
          />
        )}
      />

      <View style={{ marginTop: spacing.xl }}>
        <Button
          testID="request-code-button"
          label="Send verification code"
          onPress={onSubmit}
          loading={isLoading || formState.isSubmitting}
          accessibilityHint="Sends a one-time code to your phone"
        />
      </View>

      {formState.errors.root ? (
        <Text style={[type.caption, { color: colors.danger, marginTop: spacing.md }]}>
          {formState.errors.root.message}
        </Text>
      ) : null}

      <Text style={[type.caption, { color: colors.mutedText, marginTop: spacing.xl }]}>
        By continuing you agree to our terms and privacy notice. This service is available in
        selected areas only.
      </Text>
    </Screen>
  );
}

const styles = StyleSheet.create({
  header: {},
});

export { toDisplayMessage };

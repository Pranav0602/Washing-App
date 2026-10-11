/**
 * Step 2: verify the one-time code.
 *
 * Handles the cooldown the API enforces on resend, and the attempt limit, so the
 * customer sees an accurate countdown rather than an unexplained rejection.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { Controller, useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { Text, View } from 'react-native';

import { authApi } from '@/api/endpoints';
import { ApiError, isApiError } from '@/lib/apiError';
import { otpSchemaForm, type OtpFormValues } from '@/lib/schemas';
import { useCountdown } from '@/hooks';
import { useSession } from '@/auth/SessionProvider';
import { Banner, Button, ErrorState, Screen, TextField } from '@/components/ui';
import { useTheme } from '@/theme';

export default function OtpScreen() {
  const { challengeId, phone } = useLocalSearchParams<{ challengeId: string; phone: string }>();
  const router = useRouter();
  const { colors, spacing, type } = useTheme();
  const { signInWithOtp, isPartner } = useSession();

  const [verifyError, setVerifyError] = useState<unknown>(null);
  const [attemptsRemaining, setAttemptsRemaining] = useState<number | null>(null);
  const [resendCooldown, setResendCooldown] = useState(60);
  const [isResending, setIsResending] = useState(false);
  const [isLocked, setIsLocked] = useState(false);

  const cooldown = useCountdown(resendCooldown, !isLocked);
  const inputRef = useRef<View>(null);

  const { control, handleSubmit, formState, setFocus, reset } = useForm<OtpFormValues>({
    resolver: zodResolver(otpSchemaForm),
    defaultValues: { code: '' },
    mode: 'onSubmit',
  });

  // Focus the field on mount: on a six-digit code there is nothing to decide first.
  useEffect(() => {
    const timer = setTimeout(() => setFocus('code'), 250);
    return () => clearTimeout(timer);
  }, [setFocus]);

  const onSubmit = handleSubmit(async ({ code }) => {
    if (!challengeId) return;
    setVerifyError(null);
    try {
      const session = await signInWithOtp(challengeId, code);
      // The root gate handles the rest of the routing, including the registration
      // step, so this screen never has to know which path applies.
      if (session.next === 'register_customer') router.replace('/(auth)/register/customer');
      else if (session.next === 'register_partner') router.replace('/(auth)/register/partner');
      else if (isPartner) router.replace('/(partner)');
      else router.replace('/(customer)');
    } catch (error) {
      setVerifyError(error);
      if (isApiError(error)) {
        const remaining = error.details?.attempts_remaining;
        if (typeof remaining === 'number') setAttemptsRemaining(remaining);
        if (error.code === 'otp_locked') setIsLocked(true);
        reset({ code: '' });
      }
    }
  });

  const onResend = useCallback(async () => {
    if (!challengeId || cooldown > 0) return;
    setIsResending(true);
    setVerifyError(null);
    try {
      const result = await authApi.resendOtp(challengeId);
      setResendCooldown(result.retry_after_seconds ?? 60);
    } catch (error) {
      setVerifyError(error);
    } finally {
      setIsResending(false);
    }
  }, [challengeId, cooldown]);

  const expired = verifyError instanceof ApiError && verifyError.code === 'otp_expired';

  return (
    <Screen testID="otp-screen">
      <View style={{ marginBottom: spacing.xl }}>
        <Text style={[type.title, { color: colors.text }]}>Enter your code</Text>
        <Text style={[type.body, { color: colors.mutedText, marginTop: spacing.sm }]}>
          We sent a code to {phone ?? 'your phone'}.
        </Text>
      </View>

      {isLocked ? (
        <Banner
          testID="otp-locked"
          tone="danger"
          title="Too many attempts"
          message="This code cannot be used any more. Request a new one to continue."
        />
      ) : null}

      {expired ? (
        <Banner
          testID="otp-expired"
          tone="warning"
          title="Code expired"
          message="Request a new code to continue."
        />
      ) : null}

      {verifyError && !expired && !isLocked ? (
        <ErrorState
          error={verifyError}
          onRetry={() => setVerifyError(null)}
          title="That code did not work"
        />
      ) : null}

      {attemptsRemaining !== null && !isLocked ? (
        <Text style={[type.caption, { color: colors.mutedText, marginBottom: spacing.md }]}>
          {attemptsRemaining} attempt{attemptsRemaining === 1 ? '' : 's'} remaining.
        </Text>
      ) : null}

      <Controller
        control={control}
        name="code"
        render={({ field: { onChange, onBlur, value } }) => (
          <View ref={inputRef}>
            <TextField
              control={control}
              name="code"
              label="Verification code"
              placeholder="123456"
              keyboardType="number-pad"
              autoComplete="sms-otp"
              textContentType="oneTimeCode"
              autoCapitalize="none"
              maxLength={10}
              required
              editable={!isLocked}
              value={value}
              onChange={onChange}
              onBlur={onBlur}
            />
          </View>
        )}
      />

      <View style={{ marginTop: spacing.xl, gap: spacing.md }}>
        <Button
          testID="verify-button"
          label="Verify and continue"
          onPress={onSubmit}
          loading={formState.isSubmitting}
          disabled={isLocked}
        />

        <Button
          testID="resend-button"
          label={cooldown > 0 ? `Resend in ${cooldown}s` : 'Resend code'}
          variant="ghost"
          onPress={onResend}
          loading={isResending}
          disabled={cooldown > 0 || isLocked}
        />

        <Button
          testID="change-phone-button"
          label="Use a different number"
          variant="ghost"
          onPress={() => router.replace('/(auth)/phone')}
        />
      </View>
    </Screen>
  );
}


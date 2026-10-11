/**
 * Customer registration.
 *
 * Collects everything the PDF requires at booking time in one pass: profile, a map
 * pin with site type and access notes, and the first vehicle. Collecting access notes
 * up front is deliberate: the partner relies on them on arrival, so asking at the door
 * would mean jobs failing for avoidable reasons.
 */

import { useState } from 'react';
import { useRouter } from 'expo-router';
import { Controller, useForm, useWatch, type Control, type FieldValues, type Path } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { StyleSheet, Switch, Text, View } from 'react-native';

import { authApi } from '@/api/endpoints';
import { queryClient } from '@/query/queryClient';
import {
  customerRegistrationSchema,
  siteTypeOptions,
  vehicleTypeOptions,
  type CustomerRegistrationValues,
} from '@/lib/schemas';
import { useSession } from '@/auth/SessionProvider';
import { Button, ChipGroup, ErrorState, Screen, TextField } from '@/components/ui';
import { useTheme } from '@/theme';

/** Fallback pin used before the customer shares or drops their location. All service is within Pune, India. */
const DEFAULT_PIN = { latitude: 18.5204, longitude: 73.8567 };

export default function CustomerRegistrationScreen() {
  const router = useRouter();
  const { colors, spacing, type } = useTheme();
  const { refreshUser } = useSession();

  const [pin, setPin] = useState(DEFAULT_PIN);
  const [pinNotice, setPinNotice] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<unknown>(null);

  const { control, handleSubmit, formState, setValue } = useForm<CustomerRegistrationValues>({
    resolver: zodResolver(customerRegistrationSchema),
    mode: 'onBlur',
    defaultValues: {
      full_name: '',
      line1: '',
      line2: '',
      city: 'Pune',
      state: 'Maharashtra',
      postal_code: '',
      site_type: 'standalone_house',
      access_notes: '',
      parking_details: '',
      property_approval: false,
      vehicle_type: 'car',
      make: '',
      model: '',
      color: '',
      registration_number: '',
      terms: false,
      privacy: false,
      evidence: true,
    },
  });

  // Subscribing to the two chip-backed fields keeps them in step with validation
  // without reaching into React Hook Form's internals.
  const siteType = useWatch({ control, name: 'site_type' });
  const vehicleType = useWatch({ control, name: 'vehicle_type' });

  const onUseMyLocation = async () => {
    setPinNotice(null);
    try {
      const Location = await import('expo-location');
      const permission = await Location.requestForegroundPermissionsAsync();
      if (permission.status !== 'granted') {
        setPinNotice('Location permission was declined. The current pin will be used instead.');
        return;
      }
      const position = await Location.getCurrentPositionAsync({});
      setPin({ latitude: position.coords.latitude, longitude: position.coords.longitude });
    } catch {
      setPinNotice('Could not read your location. The current pin will be used instead.');
    }
  };

  const onSubmit = handleSubmit(async (values) => {
    setSubmitError(null);
    try {
      await authApi.registerCustomer({
        full_name: values.full_name,
        address: {
          label: 'Home',
          line1: values.line1,
          line2: values.line2 ?? '',
          city: values.city,
          state: values.state ?? '',
          postal_code: values.postal_code ?? '',
          country: 'IN',
          latitude: pin.latitude,
          longitude: pin.longitude,
          site_type: values.site_type,
          access_notes: values.access_notes,
          parking_details: values.parking_details ?? '',
          property_approval: values.property_approval,
        },
        vehicle: {
          vehicle_type: values.vehicle_type,
          make: values.make,
          model: values.model,
          year: values.year || null,
          color: values.color ?? '',
          registration_number: values.registration_number ?? '',
        },
        consent: {
          terms: values.terms,
          privacy: values.privacy,
          evidence: values.evidence,
        },
      });

      await refreshUser();
      queryClient.clear();
      router.replace('/(customer)');
    } catch (error) {
      setSubmitError(error);
    }
  });

  const errors = formState.errors;

  return (
    <Screen testID="register-customer-screen">
      <View style={{ marginBottom: spacing.xl }}>
        <Text style={[type.title, { color: colors.text }]}>Complete your profile</Text>
        <Text style={[type.body, { color: colors.mutedText, marginTop: spacing.sm }]}>
          We need your car and where it is parked so a partner can reach it.
        </Text>
      </View>

      {submitError ? (
        <ErrorState
          testID="register-error"
          error={submitError}
          onRetry={() => setSubmitError(null)}
          title="Could not save your profile"
        />
      ) : null}

      <SectionLabel>Your details</SectionLabel>
      <TextField
        control={control}
        name="full_name"
        label="Full name"
        placeholder="Asha Rao"
        autoComplete="name"
        required
      />

      <SectionLabel>Vehicle</SectionLabel>
      <ChipGroup
        label="Vehicle type"
        options={vehicleTypeOptions}
        value={vehicleType}
        onChange={(value) => setValue('vehicle_type', value, { shouldValidate: true })}
        error={errors.vehicle_type?.message as string | undefined}
        testID="vehicle-type"
      />
      <TextField control={control} name="make" label="Make" placeholder="Maruti" required />
      <Gap />
      <TextField control={control} name="model" label="Model" placeholder="Swift" required />
      <Gap />
      <TextField
        control={control}
        name="year"
        label="Year (optional)"
        placeholder="2019"
        keyboardType="number-pad"
      />
      <Gap />
      <TextField
        control={control}
        name="registration_number"
        label="Registration number (optional)"
        placeholder="MH12AB1234"
        autoCapitalize="characters"
      />

      <SectionLabel>Where we wash</SectionLabel>
      <ChipGroup
        label="Where is the car?"
        options={siteTypeOptions}
        value={siteType}
        onChange={(value) => setValue('site_type', value, { shouldValidate: true })}
        error={errors.site_type?.message as string | undefined}
        testID="site-type"
      />

      <View
        style={[
          styles.pinCard,
          { backgroundColor: colors.surfaceAlt, borderColor: colors.border },
        ]}>
        <Text style={[type.bodyStrong, { color: colors.text }]}>Location pin</Text>
        <Text style={[type.caption, { color: colors.mutedText, marginTop: 4 }]}>
          {pin.latitude.toFixed(5)}, {pin.longitude.toFixed(5)}
        </Text>
        <View style={{ marginTop: 12 }}>
          <Button
            testID="use-my-location"
            label="Use my current location"
            variant="secondary"
            fullWidth={false}
            onPress={onUseMyLocation}
          />
        </View>
        {pinNotice ? (
          <Text style={[type.caption, { color: colors.warning, marginTop: spacing.sm }]}>
            {pinNotice}
          </Text>
        ) : null}
      </View>

      <Gap />
      <TextField
        control={control}
        name="line1"
        label="Street address"
        placeholder="12 Residency Road"
        autoComplete="street-address"
        required
      />
      <Gap />
      <TextField control={control} name="line2" label="Apartment, floor (optional)" />
      <Gap />
      <TextField control={control} name="city" label="City" placeholder="Pune" required />
      <Gap />
      <TextField control={control} name="state" label="State (optional)" placeholder="Maharashtra" />
      <Gap />
      <TextField
        control={control}
        name="postal_code"
        label="Postal code (optional)"
        keyboardType="number-pad"
      />

      <Gap />
      <TextField
        control={control}
        name="access_notes"
        label="Access and parking notes"
        placeholder="Gate code 4821. Park under the carport."
        multiline
        required
        hint="Gate codes, floor, water point, where to park. Your partner relies on this on arrival."
      />

      <Gap />
      <Controller
        control={control}
        name="property_approval"
        render={({ field: { onChange, value } }) => (
          <View style={[styles.approvalRow, { borderColor: colors.border }]}>
            <View style={{ flex: 1, paddingRight: spacing.md }}>
              <Text style={[type.body, { color: colors.text }]}>Society approval obtained</Text>
              <Text style={[type.caption, { color: colors.mutedText, marginTop: 2 }]}>
                Turn this on if your society or building management has approved washing here.
              </Text>
            </View>
            <Switch
              testID="property-approval"
              value={Boolean(value)}
              onValueChange={onChange}
              trackColor={{ true: colors.tint, false: colors.border }}
            />
          </View>
        )}
      />

      <SectionLabel>Consent</SectionLabel>

      <ConsentRow
        testID="consent-terms"
        control={control}
        name="terms"
        label="I accept the customer terms"
        description="Including the cancellation policy."
        error={errors.terms?.message as string | undefined}
      />
      <ConsentRow
        testID="consent-privacy"
        control={control}
        name="privacy"
        label="I accept the privacy notice"
        description="How your location, vehicle details and photos are handled."
        error={errors.privacy?.message as string | undefined}
      />
      <ConsentRow
        testID="consent-evidence"
        control={control}
        name="evidence"
        label="Photo evidence"
        description="Your partner photographs the car before and after the wash."
        optional
      />

      <View style={{ marginTop: spacing.xl }}>
        <Button
          testID="register-customer-submit"
          label="Create my account"
          onPress={onSubmit}
          loading={formState.isSubmitting}
        />
      </View>

      <View style={{ marginTop: spacing.sm }}>
        <Button
          testID="switch-to-partner"
          label="I want to wash cars instead"
          variant="ghost"
          onPress={() => router.replace('/(auth)/register/partner')}
        />
      </View>
    </Screen>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  const { colors, spacing, type } = useTheme();
  return (
    <Text
      accessibilityRole="header"
      style={[type.heading, { color: colors.text, marginTop: spacing.lg, marginBottom: spacing.sm }]}>
      {children}
    </Text>
  );
}

function Gap() {
  const { spacing } = useTheme();
  return <View style={{ height: spacing.md }} />;
}

/** A consent switch bound to the form, with its own inline error. */
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
  pinCard: { borderWidth: 1, padding: 16, borderRadius: 12, marginTop: 4 },
  approvalRow: { flexDirection: 'row', alignItems: 'center', borderWidth: 1, padding: 12, borderRadius: 12 },
  consentRow: { flexDirection: 'row', alignItems: 'center', borderWidth: 1, padding: 12, borderRadius: 12 },
});

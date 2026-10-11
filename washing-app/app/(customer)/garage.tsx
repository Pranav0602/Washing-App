/**
 * Garage and saved addresses.
 *
 * The vehicle and address a customer picks here are what the quote is priced from, so
 * the screen is deliberately explicit about what a vehicle size tier affects.
 */

import { useCallback, useState } from 'react';
import { useRouter } from 'expo-router';
import { RefreshControl, ScrollView, StyleSheet, Switch, Text, View } from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useForm, useWatch } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { addressApi, vehicleApi } from '@/api/endpoints';
import { addressKeys, vehicleKeys } from '@/query/keys';
import { isApiError } from '@/lib/apiError';
import {
  addressSchema,
  vehicleSchema,
  vehicleTypeOptions,
  type AddressValues,
  type VehicleValues,
} from '@/lib/schemas';
import { SIZE_TIER_LABELS } from '@/lib/format';
import { LocationMap } from '@/components/map';
import {
  Badge,
  Button,
  Card,
  ChipGroup,
  EmptyState,
  ErrorState,
  SectionTitle,
  SkeletonList,
  TextField,
} from '@/components/ui';
import { useTheme } from '@/theme';

export default function GarageScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors, spacing, type } = useTheme();
  const queryClient = useQueryClient();

  const [panel, setPanel] = useState<'none' | 'vehicle' | 'address'>('none');

  const vehiclesQuery = useQuery({ queryKey: vehicleKeys.all, queryFn: vehicleApi.list });
  const addressesQuery = useQuery({ queryKey: addressKeys.all, queryFn: addressApi.list });

  const refresh = useCallback(() => {
    void vehiclesQuery.refetch();
    void addressesQuery.refetch();
  }, [addressesQuery, vehiclesQuery]);

  const vehicles = vehiclesQuery.data ?? [];
  const addresses = addressesQuery.data ?? [];

  return (
    <ScrollView
      testID="garage-screen"
      style={{ flex: 1, backgroundColor: colors.background }}
      contentContainerStyle={{
        padding: spacing.lg,
        paddingTop: insets.top + spacing.md,
        paddingBottom: insets.bottom + spacing.xl,
      }}
      refreshControl={
        <RefreshControl
          refreshing={vehiclesQuery.isRefetching || addressesQuery.isRefetching}
          onRefresh={refresh}
          tintColor={colors.tint}
        />
      }>
      <Text style={[type.title, { color: colors.text }]}>Garage and addresses</Text>

      <SectionTitle action={null}>Vehicles</SectionTitle>

      {vehiclesQuery.isLoading ? (
        <SkeletonList count={2} />
      ) : vehiclesQuery.isError ? (
        <ErrorState error={vehiclesQuery.error} onRetry={refresh} title="Could not load your vehicles" />
      ) : vehicles.length === 0 ? (
        <EmptyState
          title="No vehicles added"
          message="Add your car so we can price a wash for it."
          icon="car-sport-outline"
          action={{ label: 'Add a vehicle', onPress: () => setPanel('vehicle') }}
        />
      ) : (
        <>
          {vehicles.map((vehicle) => (
            <Card key={vehicle.id} testID={`vehicle-${vehicle.id}`}>
              <View style={styles.rowBetween}>
                <Text style={[type.bodyStrong, { color: colors.text, flex: 1 }]}>
                  {vehicle.display_name}
                </Text>
                <Badge
                  label={SIZE_TIER_LABELS[vehicle.size_tier]}
                  tone="info"
                />
              </View>
              <Text style={[type.caption, { color: colors.mutedText, marginTop: 4 }]}>
                {vehicle.vehicle_type_label}
                {vehicle.registration_number ? ` · ${vehicle.registration_number}` : ''}
              </Text>
              <Text style={[type.caption, { color: colors.mutedText, marginTop: spacing.sm }]}>
                The size tier sets the vehicle adjustment in your price.
              </Text>
            </Card>
          ))}
          <Button
            testID="add-vehicle"
            label="Add a vehicle"
            variant="secondary"
            icon="add-circle-outline"
            onPress={() => setPanel('vehicle')}
          />
        </>
      )}

      <SectionTitle>Saved addresses</SectionTitle>

      {addressesQuery.isError ? (
        <ErrorState error={addressesQuery.error} onRetry={refresh} title="Could not load your addresses" />
      ) : addresses.length === 0 ? (
        <EmptyState
          title="No addresses saved"
          message="Save where your car is parked, including access notes."
          icon="location-outline"
          action={{ label: 'Add an address', onPress: () => setPanel('address') }}
        />
      ) : (
        <>
          {addresses.map((address) => (
            <Card key={address.id} testID={`address-${address.id}`}>
              <View style={styles.rowBetween}>
                <Text style={[type.bodyStrong, { color: colors.text, flex: 1 }]}>
                  {address.label || address.line1}
                </Text>
                {address.is_default ? <Badge label="Default" tone="success" /> : null}
              </View>
              <Text style={[type.caption, { color: colors.mutedText, marginTop: 4 }]}>
                {address.summary}
              </Text>
              <Text style={[type.caption, { color: colors.mutedText, marginTop: spacing.xs }]}>
                {address.site_type_label}
              </Text>
              {address.access_notes ? (
                <Text style={[type.caption, { color: colors.mutedText, marginTop: spacing.sm }]}>
                  Access: {address.access_notes}
                </Text>
              ) : null}
              {address.property_approval ? (
                <Badge label="Property approval recorded" tone="info" />
              ) : null}
            </Card>
          ))}
          <Button
            testID="add-address"
            label="Add an address"
            variant="secondary"
            icon="add-circle-outline"
            onPress={() => setPanel('address')}
          />
        </>
      )}

      {panel === 'vehicle' ? (
        <VehicleForm
          onDone={() => {
            setPanel('none');
            void queryClient.invalidateQueries({ queryKey: vehicleKeys.all });
          }}
        />
      ) : null}

      {panel === 'address' ? (
        <AddressForm
          onDone={() => {
            setPanel('none');
            void queryClient.invalidateQueries({ queryKey: addressKeys.all });
          }}
        />
      ) : null}

      {panel === 'none' ? (
        <View style={{ marginTop: spacing.xl }}>
          <Button
            testID="book-from-garage"
            label="Book a wash"
            onPress={() => router.push('/booking/quote')}
          />
        </View>
      ) : null}
    </ScrollView>
  );
}

function VehicleForm({ onDone }: { onDone: () => void }) {
  const { colors, spacing, type } = useTheme();

  const { control, handleSubmit, formState, setValue } = useForm<VehicleValues>({
    resolver: zodResolver(vehicleSchema),
    defaultValues: { vehicle_type: 'car', make: '', model: '', color: '', registration_number: '' },
  });

  const create = useMutation({
    mutationFn: vehicleApi.create,
    onSuccess: onDone,
  });

  const vehicleType = useWatch({ control, name: 'vehicle_type' });

  return (
    <Card testID="vehicle-form" style={{ marginTop: spacing.lg }}>
      <Text style={[type.heading, { color: colors.text, marginBottom: spacing.md }]}>
        Add a vehicle
      </Text>

      <ChipGroup
        label="Vehicle type"
        options={vehicleTypeOptions}
        value={vehicleType}
        onChange={(value) => setValue('vehicle_type', value, { shouldValidate: true })}
        error={formState.errors.vehicle_type?.message as string | undefined}
      />

      <TextField control={control} name="make" label="Make" required />
      <Gap />
      <TextField control={control} name="model" label="Model" required />
      <Gap />
      <TextField control={control} name="year" label="Year (optional)" keyboardType="number-pad" />
      <Gap />
      <TextField control={control} name="color" label="Colour (optional)" />
      <Gap />
      <TextField
        control={control}
        name="registration_number"
        label="Registration number (optional)"
        autoCapitalize="characters"
      />

      {create.isError ? (
        <Text style={[type.caption, { color: colors.danger, marginTop: spacing.sm }]}>
          {isApiError(create.error) ? create.error.displayMessage : 'Could not save the vehicle.'}
        </Text>
      ) : null}

      <View style={{ marginTop: spacing.lg, gap: spacing.sm }}>
        <Button
          testID="save-vehicle"
          label="Save vehicle"
          onPress={handleSubmit((values) =>
            create.mutate({
              ...values,
              year: values.year || null,
              color: values.color ?? '',
              registration_number: values.registration_number ?? '',
            } as never),
          )}
          loading={create.isPending || formState.isSubmitting}
        />
        <Button testID="cancel-vehicle" label="Cancel" variant="ghost" onPress={onDone} />
      </View>
    </Card>
  );
}

function AddressForm({ onDone }: { onDone: () => void }) {
  const { colors, spacing, type } = useTheme();
  const [pin, setPin] = useState({ latitude: 18.5204, longitude: 73.8567 });

  const { control, handleSubmit, formState, setValue } = useForm<AddressValues>({
    resolver: zodResolver(addressSchema),
    defaultValues: {
      label: '',
      line1: '',
      line2: '',
      city: 'Pune',
      state: 'Maharashtra',
      postal_code: '',
      site_type: 'standalone_house',
      access_notes: '',
      parking_details: '',
      property_approval: false,
    },
  });

  const create = useMutation({ mutationFn: addressApi.create, onSuccess: onDone });

  const siteType = useWatch({ control, name: 'site_type' });
  const approval = useWatch({ control, name: 'property_approval' });

  const useMyLocation = async () => {
    try {
      const Location = await import('expo-location');
      const permission = await Location.requestForegroundPermissionsAsync();
      if (permission.status !== 'granted') return;
      const position = await Location.getCurrentPositionAsync({});
      setPin({ latitude: position.coords.latitude, longitude: position.coords.longitude });
    } catch {
      // Keep the current pin; the customer can still save the address.
    }
  };

  return (
    <Card testID="address-form" style={{ marginTop: spacing.lg }}>
      <Text style={[type.heading, { color: colors.text, marginBottom: spacing.md }]}>
        Add an address
      </Text>

      <ChipGroup
        label="Site type"
        options={[
          { value: 'standalone_house', label: 'House' },
          { value: 'apartment', label: 'Apartment' },
          { value: 'basement', label: 'Basement' },
          { value: 'society', label: 'Society' },
          { value: 'commercial', label: 'Commercial' },
        ]}
        value={siteType}
        onChange={(value) => setValue('site_type', value, { shouldValidate: true })}
        error={formState.errors.site_type?.message as string | undefined}
      />

      <Button
        testID="address-use-location"
        label="Use my current location"
        variant="secondary"
        fullWidth={false}
        onPress={useMyLocation}
      />
      <Text style={[type.caption, { color: colors.mutedText, marginTop: spacing.sm }]}>
        {pin.latitude.toFixed(4)}, {pin.longitude.toFixed(4)}
      </Text>

      <LocationMap
        coordinate={pin}
        draggable
        onPress={setPin}
        onDragEnd={setPin}
        style={{ marginTop: spacing.md }}
      />

      <Gap />
      <TextField control={control} name="label" label="Label (optional)" placeholder="Home" />
      <Gap />
      <TextField control={control} name="line1" label="Street address" required />
      <Gap />
      <TextField control={control} name="line2" label="Apartment, floor (optional)" />
      <Gap />
      <TextField control={control} name="city" label="City" placeholder="Pune" required />
      <Gap />
      <TextField control={control} name="state" label="State (optional)" placeholder="Maharashtra" />
      <Gap />
      <TextField
        control={control}
        name="access_notes"
        label="Access and parking notes"
        multiline
        required
        hint="Gate codes, floor, water point, where to park."
      />

      <View style={[styles.rowBetween, { marginTop: spacing.md }]}>
        <Text style={[type.body, { color: colors.text, flex: 1, paddingRight: spacing.md }]}>
          Society approval obtained
        </Text>
        <Switch
          testID="address-property-approval"
          value={Boolean(approval)}
          onValueChange={(next) => setValue('property_approval', next)}
          trackColor={{ true: colors.tint, false: colors.border }}
        />
      </View>

      {create.isError ? (
        <Text style={[type.caption, { color: colors.danger, marginTop: spacing.sm }]}>
          {isApiError(create.error) ? create.error.displayMessage : 'Could not save the address.'}
        </Text>
      ) : null}

      <View style={{ marginTop: spacing.lg, gap: spacing.sm }}>
        <Button
          testID="save-address"
          label="Save address"
          onPress={handleSubmit((values) =>
            create.mutate({
              ...values,
              latitude: pin.latitude,
              longitude: pin.longitude,
              country: 'IN',
            } as never),
          )}
          loading={create.isPending || formState.isSubmitting}
        />
        <Button testID="cancel-address" label="Cancel" variant="ghost" onPress={onDone} />
      </View>
    </Card>
  );
}

function Gap() {
  const { spacing } = useTheme();
  return <View style={{ height: spacing.md }} />;
}

const styles = StyleSheet.create({
  rowBetween: { flexDirection: 'row', alignItems: 'center', gap: 8 },
});

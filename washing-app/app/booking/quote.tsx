/**
 * Quote builder: choose vehicle, address, service and add-ons for on-demand service.
 *
 * The server prices the quote; this screen never computes a price. It only collects
 * the inputs and shows what the server returned, so a client-side price could never
 * disagree with what the customer is charged.
 */

import { useMemo, useState } from 'react';
import { useRouter } from 'expo-router';
import { ScrollView, Text, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { addressApi, catalogApi, quoteApi, vehicleApi } from '@/api/endpoints';
import { addressKeys, catalogKeys, vehicleKeys } from '@/query/keys';
import { isApiError, toDisplayMessage } from '@/lib/apiError';
import { SITE_TYPE_LABELS, formatMoney } from '@/lib/format';
import {
  Banner,
  Button,
  EmptyState,
  ErrorState,
  SectionTitle,
  SkeletonList,
} from '@/components/ui';
import { useTheme } from '@/theme';

export default function QuoteBuilderScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors, spacing, type } = useTheme();

  const [vehicleId, setVehicleId] = useState<string | null>(null);
  const [addressId, setAddressId] = useState<string | null>(null);
  const [serviceCode, setServiceCode] = useState<string | null>(null);
  const [addonCodes, setAddonCodes] = useState<string[]>([]);
  const [quoteError, setQuoteError] = useState<unknown>(null);
  const [isQuoting, setIsQuoting] = useState(false);

  const vehiclesQuery = useQuery({ queryKey: vehicleKeys.all, queryFn: vehicleApi.list });
  const addressesQuery = useQuery({ queryKey: addressKeys.all, queryFn: addressApi.list });

  // Smart defaults: pre-select the default vehicle and address so booking takes two taps.
  const defaultVehicle = useMemo(
    () => (vehiclesQuery.data ?? []).find((v) => v.is_default) ?? (vehiclesQuery.data ?? [])[0] ?? null,
    [vehiclesQuery.data],
  );
  const defaultAddress = useMemo(
    () => (addressesQuery.data ?? []).find((a) => a.is_default) ?? (addressesQuery.data ?? [])[0] ?? null,
    [addressesQuery.data],
  );
  const effectiveVehicleId = vehicleId ?? defaultVehicle?.id ?? null;
  const effectiveAddressId = addressId ?? defaultAddress?.id ?? null;

  const address = useMemo(
    () => (addressesQuery.data ?? []).find((item) => item.id === effectiveAddressId) ?? null,
    [effectiveAddressId, addressesQuery.data],
  );

  // Services are filtered by site type, so a method the site cannot support never
  // appears rather than appearing and failing at quote time.
  const servicesQuery = useQuery({
    queryKey: catalogKeys.services({ site_type: address?.site_type }),
    queryFn: () => catalogApi.services({ site_type: address?.site_type }),
    enabled: Boolean(effectiveAddressId),
  });

  const service = useMemo(
    () => (servicesQuery.data ?? []).find((item) => item.code === serviceCode) ?? null,
    [serviceCode, servicesQuery.data],
  );

  const addonsQuery = useQuery({
    queryKey: catalogKeys.addons(serviceCode ?? undefined),
    queryFn: () => catalogApi.addons(serviceCode ?? undefined),
    enabled: Boolean(serviceCode),
  });

  const selectedAddons = useMemo(
    () => (addonsQuery.data ?? []).filter((addon) => addonCodes.includes(addon.code)),
    [addonCodes, addonsQuery.data],
  );

  // Optimistic estimate for the dynamic price bar; the server remains the source of
  // truth for the locked quote.
  const estimatedTotalMinor = useMemo(() => {
    const base = service?.base_price_minor ?? 0;
    const extras = selectedAddons.reduce((sum, a) => sum + a.price_minor, 0);
    return base + extras;
  }, [service, selectedAddons]);

  const canQuote = Boolean(effectiveVehicleId && effectiveAddressId && serviceCode);

  const onGetQuote = async () => {
    if (!effectiveVehicleId || !effectiveAddressId || !serviceCode) return;
    setIsQuoting(true);
    setQuoteError(null);
    try {
      const quote = await quoteApi.create({
        vehicle_id: effectiveVehicleId,
        address_id: effectiveAddressId,
        service_code: serviceCode,
        addon_codes: addonCodes,
        booking_mode: 'on_demand',
      });
      router.push({ pathname: '/booking/quote-review', params: { quoteId: quote.id } });
    } catch (error) {
      setQuoteError(error);
    } finally {
      setIsQuoting(false);
    }
  };

  return (
    <ScrollView
      testID="quote-builder-screen"
      style={{ flex: 1, backgroundColor: colors.background }}
      contentContainerStyle={{
        padding: spacing.lg,
        paddingTop: insets.top + spacing.md,
        paddingBottom: insets.bottom + spacing.xl,
      }}>
      <Text style={[type.title, { color: colors.text }]}>Book a wash</Text>

      <SectionTitle>1. Choose your vehicle</SectionTitle>
      {vehiclesQuery.isLoading ? (
        <SkeletonList count={2} />
      ) : vehiclesQuery.isError ? (
        <ErrorState error={vehiclesQuery.error} onRetry={() => void vehiclesQuery.refetch()} />
      ) : (vehiclesQuery.data ?? []).length === 0 ? (
        <EmptyState
          title="No vehicles yet"
          message="Add your car first so we can price the right size."
          action={{ label: 'Go to garage', onPress: () => router.push('/(customer)/garage') }}
        />
      ) : (
        (vehiclesQuery.data ?? []).map((vehicle) => (
          <OptionRow
            key={vehicle.id}
            testID={`pick-vehicle-${vehicle.id}`}
            title={vehicle.display_name}
            subtitle={`${vehicle.vehicle_type_label} · size tier ${vehicle.size_tier}`}
            selected={effectiveVehicleId === vehicle.id}
            onPress={() => setVehicleId(vehicle.id)}
          />
        ))
      )}

      <SectionTitle>2. Where is the car?</SectionTitle>
      {addressesQuery.isLoading ? (
        <SkeletonList count={1} />
      ) : (addressesQuery.data ?? []).length === 0 ? (
        <EmptyState
          title="No addresses yet"
          message="Save where your car is parked, including access notes."
          action={{ label: 'Go to garage', onPress: () => router.push('/(customer)/garage') }}
        />
      ) : (
        (addressesQuery.data ?? []).map((item) => (
          <OptionRow
            key={item.id}
            testID={`pick-address-${item.id}`}
            title={item.label || item.line1}
            subtitle={`${item.summary} · ${SITE_TYPE_LABELS[item.site_type] ?? item.site_type}`}
            selected={effectiveAddressId === item.id}
            onPress={() => {
              setAddressId(item.id);
              // Changing the site invalidates the service choice.
              setServiceCode(null);
              setAddonCodes([]);
            }}
          />
        ))
      )}

      {address ? (
        <>
          <SectionTitle>3. Choose a service</SectionTitle>
          {servicesQuery.isLoading ? (
            <SkeletonList count={2} />
          ) : servicesQuery.isError ? (
            <ErrorState error={servicesQuery.error} onRetry={() => void servicesQuery.refetch()} />
          ) : (
            (servicesQuery.data ?? []).map((item) => (
              <OptionRow
                key={item.code}
                testID={`pick-service-${item.code}`}
                title={item.name}
                subtitle={item.description}
                selected={serviceCode === item.code}
                onPress={() => {
                  setServiceCode(item.code);
                  setAddonCodes([]);
                }}
              />
            ))
          )}
        </>
      ) : null}

      {service ? (
        <>
          <SectionTitle>4. Add options</SectionTitle>
          {(addonsQuery.data ?? []).length === 0 ? (
            <Text style={[type.caption, { color: colors.mutedText }]}>
              No optional extras for this service.
            </Text>
          ) : (
            (addonsQuery.data ?? []).map((addon) => (
              <OptionRow
                key={addon.code}
                testID={`pick-addon-${addon.code}`}
                title={addon.name}
                subtitle={addon.description}
                selected={addonCodes.includes(addon.code)}
                onPress={() =>
                  setAddonCodes((current) =>
                    current.includes(addon.code)
                      ? current.filter((code) => code !== addon.code)
                      : [...current, addon.code],
                  )
                }
              />
            ))
          )}

        </>
      ) : null}

      <Banner
        testID="on-demand-banner"
        tone="info"
        title="On-demand service"
        message="Partner reaches your car within 10 minutes."
      />

      {quoteError ? (
        <View style={{ marginTop: spacing.lg }}>
          <ErrorState
            testID="quote-error"
            error={quoteError}
            onRetry={() => setQuoteError(null)}
            title="Could not price that"
          />
          {isApiError(quoteError) ? (
            <Text style={[type.caption, { color: colors.mutedText, textAlign: 'center' }]}>
              {toDisplayMessage(quoteError)}
            </Text>
          ) : null}
        </View>
      ) : null}

      {service ? (
        <View
          testID="price-bar"
          style={{
            marginTop: spacing.lg,
            padding: spacing.md,
            borderRadius: 12,
            backgroundColor: colors.surfaceAlt,
            borderWidth: 1,
            borderColor: colors.border,
          }}>
          <Text style={[type.bodyStrong, { color: colors.text }]}>{service.name}</Text>
          <Text style={[type.caption, { color: colors.mutedText, marginTop: 2 }]}>
            {addonCodes.length} add-on{addonCodes.length === 1 ? '' : 's'} · estimated{' '}
            {formatMoney(estimatedTotalMinor, service.currency)}
          </Text>
        </View>
      ) : null}

      <View style={{ marginTop: spacing.xl }}>
        <Button
          testID="get-quote"
          label="Get instant price"
          onPress={onGetQuote}
          loading={isQuoting}
          disabled={!canQuote}
          accessibilityHint={
            canQuote ? 'Requests a price' : 'Choose a vehicle, address and service first'
          }
        />
      </View>
    </ScrollView>
  );
}

function OptionRow({
  title,
  subtitle,
  selected,
  onPress,
  testID,
}: {
  title: string;
  subtitle?: string;
  selected: boolean;
  onPress: () => void;
  testID?: string;
}) {
  const { colors, spacing, type, radius } = useTheme();

  return (
    <View
      testID={testID}
      accessibilityRole="radio"
      accessibilityState={{ selected }}
      accessibilityLabel={title}
      onTouchEnd={onPress}
      style={{
        borderWidth: selected ? 2 : 1,
        borderColor: selected ? colors.tint : colors.border,
        backgroundColor: selected ? colors.surfaceAlt : colors.surface,
        borderRadius: radius.md,
        padding: spacing.md,
        marginBottom: spacing.sm,
      }}>
      <Text style={[type.bodyStrong, { color: colors.text }]}>{title}</Text>
      {subtitle ? (
        <Text style={[type.caption, { color: colors.mutedText, marginTop: 2 }]}>{subtitle}</Text>
      ) : null}
    </View>
  );
}


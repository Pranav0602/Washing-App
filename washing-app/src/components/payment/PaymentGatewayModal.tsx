/**
 * Post-wash payment gateway checkout.
 *
 * Opens only after the customer confirms satisfaction. Renders an itemized bill
 * matching the exact wash selections, lets the customer pick a payment method,
 * and captures payment exactly once via an idempotency key.
 */

import { useMemo, useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { paymentApi } from '@/api/endpoints';
import type { Quote } from '@/api/types';
import { bookingKeys } from '@/query/keys';
import { formatMoney } from '@/lib/format';
import { Banner, Button, Card, ErrorState } from '@/components/ui';
import { useTheme } from '@/theme';

export type PaymentMethodKind = 'upi' | 'card' | 'netbanking' | 'wallet';

export const PAYMENT_METHODS: { id: PaymentMethodKind; label: string; detail: string }[] = [
  { id: 'upi', label: 'UPI', detail: 'Google Pay / PhonePe / Paytm / UPI ID' },
  { id: 'card', label: 'Credit / Debit Card', detail: 'Visa, Mastercard, RuPay' },
  { id: 'netbanking', label: 'Net Banking / Digital Wallets', detail: 'All major banks' },
  { id: 'wallet', label: 'Apple Pay / Google Pay', detail: 'Express checkout' },
];

export interface PaymentItem {
  label: string;
  amountMinor: number;
}

export function buildPaymentItems(quote: Pick<Quote, 'lines' | 'subtotal_minor' | 'tax_minor' | 'fee_minor'>): {
  items: PaymentItem[];
  subtotalMinor: number;
  taxAndFeeMinor: number;
  totalMinor: number;
} {
  const items = [...quote.lines]
    .sort((a, b) => a.sort_order - b.sort_order)
    .map((line) => ({
      label:
        line.line_type === 'addon'
          ? `Add-on: ${line.description}`
          : line.line_type === 'vehicle_tier'
            ? `${line.description}`
            : line.description,
      amountMinor: line.amount_minor,
    }));
  const subtotalMinor = quote.subtotal_minor;
  const taxAndFeeMinor = quote.tax_minor + quote.fee_minor;
  return {
    items,
    subtotalMinor,
    taxAndFeeMinor,
    totalMinor: subtotalMinor + taxAndFeeMinor,
  };
}

export function PaymentGatewayModal({
  visible,
  onClose,
  bookingReference,
  currency,
  items,
  subtotalMinor,
  taxAndFeeMinor,
  totalMinor,
}: {
  visible: boolean;
  onClose: () => void;
  bookingReference: string;
  currency: string;
  items: PaymentItem[];
  subtotalMinor: number;
  taxAndFeeMinor: number;
  totalMinor: number;
}) {
  const { colors, spacing, type } = useTheme();
  const queryClient = useQueryClient();
  const [method, setMethod] = useState<PaymentMethodKind>('upi');
  const [paid, setPaid] = useState(false);

  const pay = useMutation({
    mutationFn: () =>
      paymentApi.pay(bookingReference, {
        payment_method_kind: method,
        amount_minor: totalMinor,
        currency,
      }),
    onSuccess: () => {
      setPaid(true);
      void queryClient.invalidateQueries({ queryKey: bookingKeys.root });
    },
  });

  const totalLabel = useMemo(() => formatMoney(totalMinor, currency), [totalMinor, currency]);

  if (!visible) return null;

  return (
    <View testID="payment-gateway-modal" style={{ flex: 1, backgroundColor: colors.background }}>
      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={{ padding: spacing.lg }}>
        <Text style={[type.title, { color: colors.text }]}>Complete Wash Payment</Text>

        {paid ? (
          <View style={{ marginTop: spacing.lg }} testID="payment-success">
            <Banner
              tone="success"
              title="Payment successful"
              message={`Paid ${totalLabel}. Your digital receipt is now available.`}
            />
            <View style={{ marginTop: spacing.lg }}>
              <Button testID="payment-done" label="Done" onPress={onClose} />
            </View>
          </View>
        ) : (
          <>
            <Card testID="payment-items" >
              <View style={{ marginTop: spacing.xs }}>
                {items.map((item, index) => (
                  <View key={`${item.label}-${index}`} style={styles.row} testID={`payment-item-${index}`}>
                    <Text style={[type.body, { color: colors.text, flex: 1 }]}>{item.label}</Text>
                    <Text style={[type.bodyStrong, { color: colors.text }]}>
                      {formatMoney(item.amountMinor, currency)}
                    </Text>
                  </View>
                ))}
                <View style={[styles.row, styles.divider, { borderTopColor: colors.border }]}>
                  <Text style={[type.bodyStrong, { color: colors.text, flex: 1 }]}>Subtotal</Text>
                  <Text style={[type.bodyStrong, { color: colors.text }]}>
                    {formatMoney(subtotalMinor, currency)}
                  </Text>
                </View>
                <View style={styles.row}>
                  <Text style={[type.body, { color: colors.mutedText, flex: 1 }]}>
                    Taxes & Service Fee
                  </Text>
                  <Text style={[type.body, { color: colors.text }]}>
                    {formatMoney(taxAndFeeMinor, currency)}
                  </Text>
                </View>
                <View style={styles.row}>
                  <Text style={[type.title, { color: colors.text, flex: 1 }]}>Total Charged</Text>
                  <Text testID="payment-total" style={[type.title, { color: colors.text }]}>
                    {totalLabel}
                  </Text>
                </View>
              </View>
            </Card>

            <Text style={[type.bodyStrong, { color: colors.text, marginTop: spacing.lg }]}>
              Select Payment Method
            </Text>
            {PAYMENT_METHODS.map((option) => {
              const selected = method === option.id;
              return (
                <Card
                  key={option.id}
                  testID={`payment-method-${option.id}`}
                >
                  <View style={styles.row}>
                    <View style={{ flex: 1 }}>
                      <Text style={[type.bodyStrong, { color: colors.text }]}>{option.label}</Text>
                      <Text style={[type.caption, { color: colors.mutedText }]}>{option.detail}</Text>
                    </View>
                    <Button
                      testID={`select-method-${option.id}`}
                      label={selected ? 'Selected' : 'Select'}
                      variant={selected ? 'primary' : 'secondary'}
                      fullWidth={false}
                      onPress={() => setMethod(option.id)}
                    />
                  </View>
                </Card>
              );
            })}

            {pay.isError ? (
              <ErrorState
                testID="payment-error"
                error={pay.error}
                onRetry={() => pay.reset()}
                title="Payment could not be completed"
              />
            ) : null}

            <View style={{ marginTop: spacing.lg, gap: spacing.sm }}>
              <Button
                testID="pay-now"
                label={`Pay ${totalLabel} Securely`}
                onPress={() => pay.mutate()}
                loading={pay.isPending}
              />
              <Text style={[type.caption, { color: colors.mutedText, textAlign: 'center' }]}>
                256-bit encrypted. Charged only on satisfaction.
              </Text>
              <Button testID="payment-cancel" label="Not now" variant="ghost" onPress={onClose} />
            </View>
          </>
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 8 },
  divider: { borderTopWidth: 1, paddingTop: 8, marginTop: 12 },
});

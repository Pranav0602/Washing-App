/**
 * The transparent price breakdown.
 *
 * Renders the server's itemised lines rather than a single total, because the PDF
 * requires the customer to see what they are paying for before authorising. The
 * server recomputes every line, so nothing here is computed client-side.
 */

import { StyleSheet, Text, View } from 'react-native';

import type { Quote } from '@/api/types';
import { formatMoney } from '@/lib/format';
import { useTheme } from '@/theme';

import { DetailRow } from '@/components/ui';

const LINE_LABELS: Record<string, string> = {
  service_base: 'Service',
  vehicle_tier: 'Vehicle size',
  addon: 'Add-ons',
  zone_travel: 'Zone and travel',
  tax: 'Tax',
  fee: 'Service fee',
  discount: 'Discount',
};

export function PriceBreakdown({
  quote,
  showTotal = true,
}: {
  quote: Quote;
  showTotal?: boolean;
}) {
  const { colors, spacing, type } = useTheme();

  const lines = [...quote.lines].sort((a, b) => a.sort_order - b.sort_order);

  return (
    <View testID="price-breakdown">
      <Text
        accessibilityRole="header"
        style={[type.heading, { color: colors.text, marginBottom: spacing.sm }]}>
        Price
      </Text>

      {lines.map((line) => {
        // Negative amounts are discounts; label them by type rather than sign alone.
        const label = LINE_LABELS[line.line_type] ?? line.line_type_label;
        const amount = formatMoney(Math.abs(line.amount_minor), quote.currency);
        const isDiscount = line.line_type === 'discount';

        return (
          <DetailRow
            key={line.id}
            testID={`price-line-${line.line_type}`}
            label={line.quantity > 1 ? `${label} ×${line.quantity}` : label}
            value={isDiscount ? `− ${amount}` : amount}
            tone={isDiscount ? 'success' : 'default'}
          />
        );
      })}

      {showTotal ? (
        <View
          style={[
            styles.totalRow,
            {
              borderTopColor: colors.border,
              borderTopWidth: 1,
              marginTop: spacing.sm,
              paddingTop: spacing.md,
            },
          ]}>
          <Text style={[type.bodyStrong, { color: colors.text, flex: 1 }]}>Total</Text>
          <Text testID="price-total" style={[type.title, { color: colors.text }]}>
            {formatMoney(quote.total_minor, quote.currency)}
          </Text>
        </View>
      ) : null}

      {quote.discount_minor > 0 ? (
        <Text style={[type.caption, { color: colors.success, marginTop: spacing.xs }]}>
          Promotion applied.
        </Text>
      ) : null}

      <Text style={[type.caption, { color: colors.mutedText, marginTop: spacing.sm }]}>
        Priced with ruleset {quote.price_rule_version_label}.
      </Text>
    </View>
  );
}

/** A compact total for list rows and summaries. */
export function PriceTotal({
  amountMinor,
  currency,
  label,
}: {
  amountMinor: number;
  currency: string;
  label?: string;
}) {
  const { colors, spacing, type } = useTheme();
  return (
    <View style={{ flexDirection: 'row', alignItems: 'baseline', gap: spacing.sm }}>
      {label ? <Text style={[type.caption, { color: colors.mutedText }]}>{label}</Text> : null}
      <Text style={[type.bodyStrong, { color: colors.text }]}>
        {formatMoney(amountMinor, currency)}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  totalRow: { flexDirection: 'row', alignItems: 'center' },
});

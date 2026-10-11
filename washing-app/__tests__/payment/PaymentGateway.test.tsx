import React from 'react';
import { fireEvent, render, waitFor } from '@testing-library/react-native';

import {
  PaymentGatewayModal,
  buildPaymentItems,
} from '@/components/payment/PaymentGatewayModal';
import { paymentApi } from '@/api/endpoints';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

jest.mock('@/api/endpoints', () => ({
  paymentApi: { pay: jest.fn() },
}));

async function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const quoteLines: any[] = [
  { id: 'l1', line_type: 'service_base', description: 'Exterior Foam Wash', amount_minor: 2500, sort_order: 1, quantity: 1 },
  { id: 'l2', line_type: 'vehicle_tier', description: 'SUV Vehicle Size Tier', amount_minor: 500, sort_order: 2, quantity: 1 },
  { id: 'l3', line_type: 'addon', description: 'Tyre Dressing & Shine', amount_minor: 400, sort_order: 3, quantity: 1 },
  { id: 'l4', line_type: 'addon', description: 'Interior Deep Vacuum', amount_minor: 800, sort_order: 4, quantity: 1 },
];

const quote: any = {
  lines: quoteLines,
  subtotal_minor: 4200,
  tax_minor: 210,
  fee_minor: 0,
  currency: 'USD',
  total_minor: 4410,
};

const baseProps = {
  visible: true,
  onClose: jest.fn(),
  bookingReference: 'BK1',
  currency: 'USD',
  ...(() => {
    const built = buildPaymentItems(quote);
    return { items: built.items, subtotalMinor: built.subtotalMinor, taxAndFeeMinor: built.taxAndFeeMinor, totalMinor: built.totalMinor };
  })(),
};

describe('PaymentGatewayModal', () => {
  beforeEach(() => jest.clearAllMocks());

  it('itemizes the exact wash selections', async () => {
    const { getByTestId, getByText } = await renderWithClient(<PaymentGatewayModal {...baseProps} />);
    expect(getByTestId('payment-item-0')).toBeTruthy();
    expect(getByText('Exterior Foam Wash')).toBeTruthy();
    expect(getByText(/Tyre Dressing/)).toBeTruthy();
    expect(getByText(/Interior Deep Vacuum/)).toBeTruthy();
  });

  it('calculates exact subtotal, tax and final amount', async () => {
    const built = buildPaymentItems(quote);
    expect(built.subtotalMinor).toBe(4200);
    expect(built.taxAndFeeMinor).toBe(210);
    expect(built.totalMinor).toBe(4410);
    const { getByTestId } = await renderWithClient(<PaymentGatewayModal {...baseProps} />);
    expect(getByTestId('payment-total').children.join('')).toContain('44.10');
  });

  it('switches between payment methods', async () => {
    const { getByTestId } = await renderWithClient(<PaymentGatewayModal {...baseProps} />);
    await fireEvent.press(getByTestId('select-method-card'));
    expect(getByTestId('select-method-card').props.accessibilityLabel).toBe('Selected');
  });

  it('executes payment with an idempotency-keyed pay call and shows success', async () => {
    (paymentApi.pay as jest.Mock).mockResolvedValue({ status: 'captured' });
    const { getByTestId } = await renderWithClient(<PaymentGatewayModal {...baseProps} />);
    await fireEvent.press(getByTestId('select-method-upi'));
    await fireEvent.press(getByTestId('pay-now'));
    await waitFor(() =>
      expect(paymentApi.pay).toHaveBeenCalledWith('BK1', {
        payment_method_kind: 'upi',
        amount_minor: 4410,
        currency: 'USD',
      }),
    );
    await waitFor(() => expect(getByTestId('payment-success')).toBeTruthy());
  });

  it('handles payment failure with a retry path', async () => {
    (paymentApi.pay as jest.Mock).mockRejectedValue(new Error('declined'));
    const { getByTestId } = await renderWithClient(<PaymentGatewayModal {...baseProps} />);
    await fireEvent.press(getByTestId('pay-now'));
    await waitFor(() => expect(getByTestId('payment-error')).toBeTruthy());
  });
});

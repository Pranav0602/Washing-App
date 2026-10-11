import React from 'react';
import { fireEvent, render, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import QuoteBuilderScreen from '@app/booking/quote';
import BookingConfirmScreen from '@app/booking/confirm';
import { PaymentGatewayModal, buildPaymentItems } from '@/components/payment/PaymentGatewayModal';
import { quoteApi, bookingApi, paymentApi, vehicleApi, addressApi, catalogApi } from '@/api/endpoints';

const mockPush = jest.fn();
const mockReplace = jest.fn();

jest.mock('expo-router', () => ({
  useRouter: () => ({ push: mockPush, replace: mockReplace }),
  useLocalSearchParams: () => ({ quoteId: 'q_1' }),
}));

jest.mock('react-native-safe-area-context', () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));

jest.mock('@/api/endpoints', () => ({
  vehicleApi: { list: jest.fn() },
  addressApi: { list: jest.fn() },
  catalogApi: { services: jest.fn(), addons: jest.fn() },
  quoteApi: { create: jest.fn(), get: jest.fn(), accept: jest.fn() },
  bookingApi: { create: jest.fn() },
  paymentApi: { pay: jest.fn() },
}));

jest.mock('@tanstack/react-query', () => {
  const actual = jest.requireActual('@tanstack/react-query');
  return {
    ...actual,
    useQuery: (opts: any) => {
      const key = JSON.stringify(opts.queryKey);
      let data: any = undefined;
      if (key.includes('vehicles')) data = [{ id: 'v1', display_name: 'My Car', vehicle_type_label: 'Car', size_tier: 'M', is_default: true }];
      else if (key.includes('addresses')) data = [{ id: 'a1', label: 'Home', line1: '1 Main St', summary: 'Apt', site_type: 'apartment', is_default: true }];
      else if (key.includes('"addons"')) data = [{ code: 'tyre', name: 'Tyre Dressing', description: '', price_minor: 400 }];
      else if (key.includes('services')) data = [{ code: 'foam', name: 'Foam Wash', description: '', base_price_minor: 2500, currency: 'USD', expected_duration_minutes: 30 }];
      else if (key.includes('quote')) data = mockQuote;
      return { data, isLoading: false, isError: false, isRefetching: false, refetch: jest.fn() };
    },
  };
});

const mockQuote: any = {
  id: 'q_1',
  service_name: 'Exterior Foam Wash',
  service_code: 'foam',
  vehicle_name: 'My Car',
  zone_code: 'Z1',
  booking_mode: 'on_demand',
  window_start: null,
  window_end: null,
  status: 'accepted',
  is_expired: false,
  currency: 'USD',
  subtotal_minor: 2900,
  tax_minor: 145,
  fee_minor: 0,
  discount_minor: 0,
  total_minor: 3045,
  price_rule_version_label: 'v1',
  expected_duration_minutes: 30,
  inclusions: [],
  exclusions: [],
  lines: [
    { id: 'l1', line_type: 'service_base', description: 'Exterior Foam Wash', amount_minor: 2500, sort_order: 1, quantity: 1 },
    { id: 'l2', line_type: 'addon', description: 'Tyre Dressing', amount_minor: 400, sort_order: 2, quantity: 1 },
  ],
  expires_at: new Date(Date.now() + 3600e3).toISOString(),
  created_at: new Date().toISOString(),
};

const mockBooking: any = { reference: 'BK_1', status: 'dispatching' };

describe('End-to-end wash booking flow', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (quoteApi.create as jest.Mock).mockResolvedValue(mockQuote);
    (quoteApi.get as jest.Mock).mockResolvedValue(mockQuote);
    (bookingApi.create as jest.Mock).mockResolvedValue(mockBooking);
    (paymentApi.pay as jest.Mock).mockResolvedValue({ status: 'captured' });
  });

  it('books on-demand with $0 upfront, then charges the exact amount post-wash', async () => {
    // 1. Customer picks car/address/service and requests a price — no slot picker.
    const screen1 = await render(
      <QueryClientProvider client={new QueryClient()}>
        <QuoteBuilderScreen />
      </QueryClientProvider>,
    );
    await fireEvent(screen1.getByTestId('pick-service-foam'), 'touchEnd');
    await fireEvent.press(screen1.getByTestId('get-quote'));
    await waitFor(() =>
      expect(quoteApi.create).toHaveBeenCalledWith(expect.objectContaining({ booking_mode: 'on_demand' })),
    );

    // 2. Booking is created directly — no upfront authorization step.
    const screen2 = await render(
      <QueryClientProvider client={new QueryClient()}>
        <BookingConfirmScreen />
      </QueryClientProvider>,
    );
    await fireEvent.press(screen2.getByTestId('create-booking'));
    await waitFor(() => expect(bookingApi.create).toHaveBeenCalledWith('q_1', true));
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/booking/BK_1'));

    // 3. Post-wash, satisfaction confirmed → payment gateway charges the exact total.
    const built = buildPaymentItems(mockQuote);
    const screen3 = await render(
      <QueryClientProvider client={new QueryClient()}>
        <PaymentGatewayModal
          visible
          onClose={jest.fn()}
          bookingReference="BK_1"
          currency={mockQuote.currency}
          items={built.items}
          subtotalMinor={built.subtotalMinor}
          taxAndFeeMinor={built.taxAndFeeMinor}
          totalMinor={built.totalMinor}
        />
      </QueryClientProvider>,
    );
    await fireEvent.press(screen3.getByTestId('pay-now'));
    await waitFor(() =>
      expect(paymentApi.pay).toHaveBeenCalledWith('BK_1', {
        payment_method_kind: 'upi',
        amount_minor: 3045,
        currency: 'USD',
      }),
    );
    await waitFor(() => expect(screen3.getByTestId('payment-success')).toBeTruthy());
  });
});

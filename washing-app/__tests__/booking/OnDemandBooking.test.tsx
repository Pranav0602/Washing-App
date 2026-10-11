import React from 'react';
import { fireEvent, render, waitFor } from '@testing-library/react-native';

import QuoteBuilderScreen from '@app/booking/quote';
import { quoteApi } from '@/api/endpoints';

const mockPush = jest.fn();

jest.mock('expo-router', () => ({
  useRouter: () => ({ push: mockPush, replace: jest.fn() }),
}));

jest.mock('react-native-safe-area-context', () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));

jest.mock('@/api/endpoints', () => ({
  vehicleApi: { list: jest.fn() },
  addressApi: { list: jest.fn() },
  catalogApi: { services: jest.fn(), addons: jest.fn() },
  quoteApi: { create: jest.fn() },
}));

const vehicles = [
  {
    id: 'v1',
    display_name: 'My Sedan',
    vehicle_type_label: 'Car',
    size_tier: 'M',
    is_default: true,
  },
];
const addresses = [
  {
    id: 'a1',
    label: 'Home',
    line1: '1 Main St',
    summary: 'Apartment block',
    site_type: 'apartment',
    is_default: true,
  },
];
const services = [
  {
    code: 'foam',
    name: 'Exterior Foam Wash',
    description: 'Foam exterior clean',
    base_price_minor: 2500,
    currency: 'USD',
    expected_duration_minutes: 30,
  },
];
const addons = [
  { code: 'tyre', name: 'Tyre Dressing', description: 'Shine tyres', price_minor: 400 },
];

const mockUseQuery = jest.fn((opts: any) => {
  const key = JSON.stringify(opts.queryKey);
  let data: any = undefined;
  if (key.includes('vehicles')) data = vehicles;
  else if (key.includes('addresses')) data = addresses;
  else if (key.includes('services')) data = services;
  else if (key.includes('"addons"')) data = addons;
  return { data, isLoading: false, isError: false, isRefetching: false, refetch: jest.fn() };
});

jest.mock('@tanstack/react-query', () => ({
  useQuery: (opts: any) => mockUseQuery(opts),
  useMutation: () => ({ mutate: jest.fn(), isPending: false, isError: false, error: undefined, reset: jest.fn() }),
  useQueryClient: () => ({ invalidateQueries: jest.fn() }),
}));

import { vehicleApi, addressApi, catalogApi } from '@/api/endpoints';

describe('On-demand booking quote builder', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (vehicleApi.list as jest.Mock).mockResolvedValue(vehicles);
    (addressApi.list as jest.Mock).mockResolvedValue(addresses);
    (catalogApi.services as jest.Mock).mockResolvedValue(services);
    (catalogApi.addons as jest.Mock).mockResolvedValue(addons);
    (quoteApi.create as jest.Mock).mockResolvedValue({ id: 'q_1' });
  });

  it('renders vehicle, address and service selectors but no time slot picker', async () => {
    const screen = await render(<QuoteBuilderScreen />);
    expect(screen.getByText('1. Choose your vehicle')).toBeTruthy();
    expect(screen.getByText('2. Where is the car?')).toBeTruthy();
    expect(screen.getByText('3. Choose a service')).toBeTruthy();
    expect(screen.queryByText(/choose a time/i)).toBeNull();
    expect(screen.queryByTestId('slot-picker')).toBeNull();
  });

  it('auto-selects default vehicle and address', async () => {
    const screen = await render(<QuoteBuilderScreen />);
    expect(screen.getByTestId('pick-vehicle-v1').props.accessibilityState).toEqual({ selected: true });
    expect(screen.getByTestId('pick-address-a1').props.accessibilityState).toEqual({ selected: true });
  });

  it('toggles add-ons and includes them in the estimate', async () => {
    const screen = await render(<QuoteBuilderScreen />);
    await fireEvent(screen.getByTestId('pick-service-foam'), 'touchEnd');
    await fireEvent(screen.getByTestId('pick-addon-tyre'), 'touchEnd');
    await waitFor(() => expect(screen.getByText(/1 add-on/)).toBeTruthy());
    expect(screen.getByTestId('price-bar')).toBeTruthy();
  });

  it('creates the quote with booking_mode on_demand and no time slot', async () => {
    const screen = await render(<QuoteBuilderScreen />);
    await fireEvent(screen.getByTestId('pick-service-foam'), 'touchEnd');
    await fireEvent.press(screen.getByTestId('get-quote'));
    await waitFor(() =>
      expect(quoteApi.create).toHaveBeenCalledWith(
        expect.objectContaining({ booking_mode: 'on_demand', service_code: 'foam' }),
      ),
    );
    const payload = (quoteApi.create as jest.Mock).mock.calls[0][0];
    expect(payload.window_start).toBeUndefined();
    expect(mockPush).toHaveBeenCalledWith({
      pathname: '/booking/quote-review',
      params: { quoteId: 'q_1' },
    });
  });
});

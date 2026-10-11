import React from 'react';
import { fireEvent, render, waitFor } from '@testing-library/react-native';

import { SatisfactionGate } from '@/components/booking/SatisfactionGate';
import { bookingApi } from '@/api/endpoints';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

jest.mock('@/api/endpoints', () => ({
  bookingApi: { reportIssue: jest.fn() },
}));

async function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const evidence: any[] = [
  { id: 'e1', evidence_type: 'pre_condition', evidence_type_label: 'Before', file_url: null },
  { id: 'e2', evidence_type: 'post_service', evidence_type_label: 'After', file_url: null },
];

describe('SatisfactionGate', () => {
  beforeEach(() => jest.clearAllMocks());

  it('renders inspection header and post-wash evidence photos', async () => {
    const { getByText, getByTestId } = await renderWithClient(
      <SatisfactionGate bookingReference="BK1" evidence={evidence} onSatisfied={jest.fn()} />,
    );
    expect(getByText('Your Car Wash is Finished!')).toBeTruthy();
    expect(getByTestId('evidence-carousel')).toBeTruthy();
    expect(getByText('After')).toBeTruthy();
  });

  it('triggers the payment modal callback when the customer is satisfied', async () => {
    const onSatisfied = jest.fn();
    const { getByTestId } = await renderWithClient(
      <SatisfactionGate bookingReference="BK1" evidence={evidence} onSatisfied={onSatisfied} />,
    );
    await fireEvent.press(getByTestId('satisfied-button'));
    expect(onSatisfied).toHaveBeenCalledTimes(1);
  });

  it('opens dispute flow and halts payment when not satisfied', async () => {
    (bookingApi.reportIssue as jest.Mock).mockResolvedValue({ status: 'open' });
    const onSatisfied = jest.fn();
    const { getByTestId, queryByTestId } = await renderWithClient(
      <SatisfactionGate bookingReference="BK1" evidence={evidence} onSatisfied={onSatisfied} />,
    );
    expect(queryByTestId('dispute-modal')).toBeNull();
    await fireEvent.press(getByTestId('not-satisfied-button'));
    expect(getByTestId('dispute-modal')).toBeTruthy();

    await fireEvent.press(getByTestId('dispute-area-rims'));
    await fireEvent(getByTestId('dispute-notes'), 'changeText', 'Rear rim still dirty');
    await fireEvent.press(getByTestId('submit-dispute'));

    await waitFor(() =>
      expect(bookingApi.reportIssue).toHaveBeenCalledWith(
        'BK1',
        expect.objectContaining({ category: 'touch_up_request' }),
      ),
    );
    expect(onSatisfied).not.toHaveBeenCalled();
    await waitFor(() => expect(getByTestId('dispute-filed-banner')).toBeTruthy());
  });
});

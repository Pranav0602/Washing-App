import React from 'react';
import { act, render } from '@testing-library/react-native';

import {
  ArrivalCountdown,
  computeArrivalDeadlineMs,
  formatRemaining,
  phaseFor,
  remainingSeconds,
} from '@/components/booking/ArrivalCountdown';

jest.mock('expo-haptics', () => ({
  notificationAsync: jest.fn(),
  NotificationFeedbackType: { Success: 'success' },
}));

describe('10-minute arrival SLA countdown', () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it('computes the arrival deadline as created_at + 10 minutes', () => {
    const created = '2026-10-08T10:00:00.000Z';
    expect(computeArrivalDeadlineMs(created)).toBe(
      new Date(created).getTime() + 10 * 60 * 1000,
    );
  });

  it('formats remaining time as MM:SS', () => {
    expect(formatRemaining(599)).toBe('09:59');
    expect(formatRemaining(60)).toBe('01:00');
    expect(formatRemaining(0)).toBe('00:00');
  });

  it('handles timer expiration gracefully', () => {
    const deadline = Date.now();
    expect(remainingSeconds(deadline, Date.now() + 5000)).toBe(0);
    expect(formatRemaining(remainingSeconds(deadline, Date.now() + 5000))).toBe('00:00');
  });

  it('shows appropriate status phases during the countdown', () => {
    expect(phaseFor(599)).toBe('searching');
    expect(phaseFor(400)).toBe('en_route');
    expect(phaseFor(100)).toBe('arriving');
    expect(phaseFor(0)).toBe('overdue');
    expect(phaseFor(300, 'arrived')).toBe('arrived');
  });

  it('renders the countdown pill and live status', async () => {
    const createdAt = new Date().toISOString();
    const screen = await render(<ArrivalCountdown createdAt={createdAt} />);
    expect(screen.getByTestId('countdown-time').children.join('')).toBe('10:00');
    expect(screen.getByTestId('countdown-status').children.join('')).toContain('Searching');
    await act(async () => {
      jest.advanceTimersByTime(3000);
    });
    expect(screen.getByTestId('countdown-time').children.join('')).toMatch(/^09:5\d$/);
  });
});

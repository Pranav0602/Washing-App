/**
 * Presentation formatting.
 *
 * The wire format is fixed by the backend contract: integer minor units, ISO-8601
 * UTC timestamps, ISO 3166 country and IANA timezone codes. Conversion for display
 * happens here so no screen reimplements it.
 */

import type { BookingStatus, SizeTier } from '@/api/types';

/**
 * Format minor units for display.
 *
 * Uses `Intl.NumberFormat` where available and falls back to a manual grouping, so
 * the same code is correct on Hermes without full ICU.
 */
export function formatMoney(amountMinor: number, currency: string): string {
  const major = amountMinor / 100;

  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(major);
  } catch {
    return `${currency} ${major.toFixed(2)}`;
  }
}

/** Compact money for dense rows, e.g. "₹1.2k". */
export function formatMoneyCompact(amountMinor: number, currency: string): string {
  const major = amountMinor / 100;
  const symbol = currencySymbol(currency);
  if (Math.abs(major) >= 1000) {
    return `${symbol}${(major / 1000).toFixed(major % 1000 === 0 ? 0 : 1)}k`;
  }
  return `${symbol}${Math.round(major)}`;
}

function currencySymbol(currency: string): string {
  switch (currency) {
    case 'INR':
      return '₹';
    case 'USD':
      return '$';
    case 'EUR':
      return '€';
    case 'GBP':
      return '£';
    case 'AED':
      return 'AED ';
    default:
      return `${currency} `;
  }
}

function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

const pad = (value: number) => String(value).padStart(2, '0');

/** Local date and time, e.g. "4 Oct, 12:30". */
export function formatDateTime(value: string | null | undefined): string {
  const date = parseDate(value);
  if (!date) return '—';
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return `${date.getDate()} ${months[date.getMonth()]}, ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Local date only, e.g. "4 Oct 2026". */
export function formatDate(value: string | null | undefined): string {
  const date = parseDate(value);
  if (!date) return '—';
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return `${date.getDate()} ${months[date.getMonth()]} ${date.getFullYear()}`;
}

/** Local time only, e.g. "12:30". */
export function formatTime(value: string | null | undefined): string {
  const date = parseDate(value);
  if (!date) return '—';
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/**
 * A promised window, e.g. "12:30 – 13:00".
 *
 * An arrival promise is only ever published after a partner has accepted, so an
 * absent window means "not yet promised" rather than a data problem.
 */
export function formatWindow(start: string | null | undefined, end: string | null | undefined): string {
  if (!start) return 'Not yet confirmed';
  if (!end) return formatTime(start);
  return `${formatTime(start)} – ${formatTime(end)}`;
}

/**
 * Coarse relative time.
 *
 * Past: "just now", "5 min ago". Future: "in 12 min" - needed for deadlines such
 * as a quote expiry, which is always ahead of the clock.
 */
export function formatRelative(value: string | null | undefined): string {
  const date = parseDate(value);
  if (!date) return '—';

  const seconds = Math.round((date.getTime() - Date.now()) / 1000);

  // The future branch must come first: a negative delta is below every past-tense
  // threshold, so without it every unexpired deadline would read "just now".
  if (seconds > 0) {
    if (seconds < 90) return 'in 1 min';
    if (seconds < 3600) return `in ${Math.round(seconds / 60)} min`;
    if (seconds < 7200) return 'in 1 hour';
    if (seconds < 86400) return `in ${Math.round(seconds / 3600)} hours`;
    if (seconds < 604800) return `in ${Math.round(seconds / 86400)} days`;
    return formatDate(value);
  }

  const elapsed = -seconds;
  if (elapsed < 45) return 'just now';
  if (elapsed < 90) return '1 min ago';
  if (elapsed < 3600) return `${Math.round(elapsed / 60)} min ago`;
  if (elapsed < 7200) return '1 hour ago';
  if (elapsed < 86400) return `${Math.round(elapsed / 3600)} hours ago`;
  if (elapsed < 604800) return `${Math.round(elapsed / 86400)} days ago`;
  return formatDate(value);
}

/**
 * Coarse age from a duration the server already measured.
 *
 * Mirrors the past-tense branch of `formatRelative`, so a queue row reads the same
 * whether its age arrives as a timestamp or as seconds, and the caller stays pure.
 */
export function formatAge(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—';

  const elapsed = Math.abs(seconds);
  if (elapsed < 45) return 'just now';
  if (elapsed < 90) return '1 min ago';
  if (elapsed < 3600) return `${Math.round(elapsed / 60)} min ago`;
  if (elapsed < 7200) return '1 hour ago';
  if (elapsed < 86400) return `${Math.round(elapsed / 3600)} hours ago`;
  if (elapsed < 604800) return `${Math.round(elapsed / 86400)} days ago`;
  return `${Math.round(elapsed / 604800)} weeks ago`;
}

/** Countdown as m:ss, for live offer timers. */
export function formatCountdown(secondsRemaining: number): string {
  const safe = Math.max(secondsRemaining, 0);
  const minutes = Math.floor(safe / 60);
  const seconds = safe % 60;
  return `${minutes}:${pad(seconds)}`;
}

/** Duration in minutes as "1h 15m". */
export function formatDuration(minutes: number | null | undefined): string {
  if (!minutes || minutes <= 0) return '—';
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return remainder ? `${hours}h ${remainder}m` : `${hours}h`;
}

export function formatDistance(km: number | null | undefined): string {
  if (km === null || km === undefined) return '—';
  return km < 1 ? `${Math.round(km * 1000)} m` : `${km.toFixed(1)} km`;
}

/** Convert minutes-after-local-midnight into "08:00". */
export function formatMinutesOfDay(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return `${pad(hours)}:${pad(remainder)}`;
}

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

/** 0 = Monday, matching the backend's `ZoneServiceWindow.weekday`. */
export function weekdayName(index: number): string {
  return WEEKDAYS[index] ?? '—';
}

/** Short weekday label for the availability editor. */
export function weekdayShort(index: number): string {
  return ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][index] ?? '—';
}

/**
 * The lifecycle position of a booking, used for the progress indicator.
 *
 * The happy path only. Exception branches deliberately map to `-1` so the indicator
 * shows an explicit "stopped here" state rather than implying forward progress.
 */
export function bookingProgress(status: BookingStatus): number {
  const path: BookingStatus[] = [
    'requested',
    'quote_accepted',
    'dispatching',
    'assigned',
    'en_route',
    'arrived',
    'in_service',
    'completed',
    'payment_captured',
    'partner_payout_eligible',
  ];
  const index = path.indexOf(status);
  return index === -1 ? -1 : index;
}

export const HAPPY_PATH: BookingStatus[] = [
  'requested',
  'quote_accepted',
  'dispatching',
  'assigned',
  'en_route',
  'arrived',
  'in_service',
  'completed',
  'payment_captured',
  'partner_payout_eligible',
];

export const STATUS_LABELS: Record<BookingStatus, string> = {
  requested: 'Requested',
  quote_accepted: 'Quote accepted',
  dispatching: 'Finding a partner',
  assigned: 'Partner assigned',
  en_route: 'On the way',
  arrived: 'Arrived',
  in_service: 'In progress',
  completed: 'Completed',
  payment_captured: 'Payment taken',
  partner_payout_eligible: 'Partner paid',
  expired_offer: 'No partner found',
  no_partner_available: 'No partner available',
  cancelled: 'Cancelled',
  partner_no_show: 'Partner no-show',
  unsafe_site: 'Site not serviceable',
  payment_failed: 'Payment failed',
  disputed_work: 'Under review',
  refunded: 'Refunded',
};

/** Statuses where nothing more will happen, so the app stops prompting. */
export const TERMINAL_STATUSES: BookingStatus[] = [
  'cancelled',
  'partner_no_show',
  'payment_failed',
  'refunded',
  'expired_offer',
  'no_partner_available',
  'unsafe_site',
  'partner_payout_eligible',
];

/** Statuses that mean something has gone wrong and the app should say so. */
export const EXCEPTION_STATUSES: BookingStatus[] = [
  'expired_offer',
  'no_partner_available',
  'cancelled',
  'partner_no_show',
  'unsafe_site',
  'payment_failed',
  'disputed_work',
  'refunded',
];

export function isTerminalStatus(status: BookingStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}

export function isExceptionStatus(status: BookingStatus): boolean {
  return EXCEPTION_STATUSES.includes(status);
}

export const SITE_TYPE_LABELS: Record<string, string> = {
  standalone_house: 'Independent house',
  apartment: 'Apartment',
  basement: 'Basement / parking',
  society: 'Society / gated community',
  commercial: 'Commercial site',
};

export const SIZE_TIER_LABELS: Record<SizeTier, string> = {
  S: 'Small',
  M: 'Medium',
  L: 'Large',
  H: 'Extra large',
};

export const VEHICLE_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: 'car', label: 'Car' },
  { value: 'suv', label: 'SUV' },
  { value: 'van', label: 'Van' },
  { value: 'truck', label: 'Truck' },
  { value: 'bike', label: 'Motorcycle' },
  { value: 'scooter', label: 'Scooter' },
];

/**
 * A plain-language explanation for the errors the API returns most often.
 *
 * Business-rule failures are the ones worth translating: they tell the customer what
 * to do next, which the raw code alone does not.
 */
const ERROR_HINTS: Record<string, string> = {
  site_method_not_permitted:
    'This service is not available at your site type. Try another location or service.',
  zone_capacity_reached: 'No capacity remains in your area right now. Please try a later time.',
  zone_inactive: 'Bookings in your area are temporarily paused.',
  on_demand_not_available: 'On-demand service is not available here right now.',
  quote_expired: 'This price has expired. Request a fresh quote.',
  quote_not_accepted: 'Accept the quote before booking.',
  offer_expired: 'This offer expired. Check your feed for new work.',
  offer_already_responded: 'You already responded to this offer.',
  booking_already_assigned: 'Another partner has taken this job.',
  evidence_incomplete: 'Capture the required photos before closing the job.',
  checklist_incomplete: 'Finish the checklist before closing the job.',
  payment_authorization_failed: 'We could not take payment. Try another method.',
  partner_not_eligible: 'Your account is not currently eligible for offers.',
  location_context_inactive: 'Start a shift or accept a job to share your location.',
  location_update_stale: 'Your location update was out of date.',
  comms_window_closed: 'Messaging closes shortly after the job ends.',
  rate_limited: 'Too many attempts. Please wait a moment.',
  network_error: 'Cannot reach the server. Check your connection.',
  timeout: 'The request timed out. Please try again.',
  idempotency_key_required: 'Missing request key. Please retry the action.',
};

export function errorHint(code: string | undefined): string | undefined {
  return code ? ERROR_HINTS[code] : undefined;
}

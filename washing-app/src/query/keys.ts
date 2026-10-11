/**
 * Centralised query keys.
 *
 * Key factories rather than inline strings, so invalidating a booking from anywhere
 * after a mutation cannot miss. `bookingKeys.root` deliberately matches every
 * booking-prefixed key, which is how a job update refreshes the list and the detail
 * together.
 */

export const sessionKeys = {
  me: ['me'] as const,
  preferences: ['me', 'preferences'] as const,
  consents: ['me', 'consents'] as const,
};

export const vehicleKeys = {
  all: ['vehicles'] as const,
};

export const addressKeys = {
  all: ['addresses'] as const,
};

export const catalogKeys = {
  services: (params?: { site_type?: string; vehicle_type?: string }) =>
    ['catalog', 'services', params ?? {}] as const,
  service: (code: string) => ['catalog', 'services', code] as const,
  addons: (serviceCode?: string) => ['catalog', 'addons', serviceCode ?? null] as const,
  priceRule: ['catalog', 'price-rule'] as const,
};

export const zoneKeys = {
  all: ['zones'] as const,
  availability: (code: string, date?: string) => ['zones', code, 'availability', date ?? null] as const,
};

export const quoteKeys = {
  root: ['quote'] as const,
  detail: (id: string) => ['quote', id] as const,
};

export const bookingKeys = {
  /** Prefix shared by every booking query, so one invalidation refreshes them all. */
  root: ['booking'] as const,
  list: (filters: Record<string, unknown>) => ['booking', 'list', filters] as const,
  detail: (reference: string) => ['booking', 'detail', reference] as const,
  events: (reference: string) => ['booking', 'events', reference] as const,
  transitions: (reference: string) => ['booking', 'transitions', reference] as const,
  checklist: (reference: string) => ['booking', 'checklist', reference] as const,
  evidence: (reference: string) => ['booking', 'evidence', reference] as const,
  payments: (reference: string) => ['booking', 'payments', reference] as const,
  job: (reference: string) => ['booking', 'job', reference] as const,
};

export const partnerKeys = {
  me: ['partner', 'me'] as const,
  skills: ['partner', 'skills'] as const,
  equipment: ['partner', 'equipment'] as const,
  documents: ['partner', 'documents'] as const,
  earnings: (params?: { from?: string; to?: string }) => ['partner', 'earnings', params ?? {}] as const,
};

export const dispatchKeys = {
  offers: ['dispatch', 'offers'] as const,
  offer: (id: string) => ['dispatch', 'offer', id] as const,
};

export const commsKeys = {
  threads: ['comms', 'threads'] as const,
  messages: (reference: string) => ['comms', 'messages', reference] as const,
};

export const notificationKeys = {
  all: ['notifications'] as const,
};

export const supportKeys = {
  all: ['support', 'cases'] as const,
  detail: (reference: string) => ['support', 'cases', reference] as const,
};

export const opsKeys = {
  jobs: (params: Record<string, unknown>) => ['ops', 'jobs', params] as const,
  job: (reference: string) => ['ops', 'jobs', reference] as const,
  exceptions: (type?: string) => ['ops', 'exceptions', type ?? 'all'] as const,
  partners: (params?: Record<string, unknown>) => ['ops', 'partners', params ?? {}] as const,
  zones: ['ops', 'zones'] as const,
  cases: (params?: Record<string, unknown>) => ['ops', 'cases', params ?? {}] as const,
  dashboard: (params?: Record<string, unknown>) => ['ops', 'dashboard', params ?? {}] as const,
  reconciliation: ['ops', 'reconciliation'] as const,
  payouts: ['ops', 'payouts'] as const,
  audit: (params?: Record<string, unknown>) => ['ops', 'audit', params ?? {}] as const,
};

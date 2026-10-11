# Phase 2 — Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│ Mobile App  (Expo Router · React Native · TypeScript strict)        │
│                                                                      │
│  Screens ──► Feature hooks ──► src/api/endpoints ──► src/api/client  │
│                                        │                             │
│                          TanStack Query (server state)               │
│                          AuthContext  (session only)                 │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │  HTTPS · JSON · Bearer JWT
                                 │  X-Request-Id · Idempotency-Key
                                 ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Django REST Framework  (modular monolith)                            │
│                                                                      │
│  api/  (versioned routers, throttling, error envelope, pagination)   │
│    ├── identity      auth, OTP, roles, consent, devices               │
│    ├── locations     addresses, zones, windows, site restrictions    │
│    ├── catalog       vehicles, services, add-ons, price rule versions│
│    ├── quotes        pricing engine, quote lifecycle                  │
│    ├── bookings      state machine, booking commands, events         │
│    ├── dispatch      eligibility, ranking, offers, monitoring        │
│    ├── partners      profile, readiness, skills, shifts, location     │
│    ├── evidence      photo records, storage port, retention           │
│    ├── payments      methods, attempts, ledger, refunds, payables     │
│    ├── comms         masked chat + call relay                         │
│    ├── notifications in-app feed, transactional outbox, push port    │
│    ├── support       cases, evidence freeze, SLA                     │
│    └── ops           console API, dashboards, manual assignment       │
│                                                                      │
│  services/  domain logic (no HTTP knowledge)                          │
│  domain/    state machines, pricing, eligibility, readiness           │
│  ports/     PaymentGateway · PushProvider · EtaProvider ·             │
│             EvidenceStorage · CommsProvider  (replaceable adapters)   │
│  common/    base models, RBAC, idempotency, audit, errors, money, time│
└───────────────┬──────────────────────────────┬───────────────────────┘
                │                              │
                ▼                              ▼
        ┌───────────────┐              ┌──────────────────────┐
        │  PostgreSQL   │              │ Outbox worker        │
        │  (authoritative│             │ (mgmt command, bounded│
        │   + row locks)│              │  retries, DLQ)        │
        └───────┬───────┘              └──────────┬───────────┘
                │                                 ▼
                │                        Push / Storage / ETA / Comms
                │                        adapters (sandbox by default)
                ▼
        ┌────────────────────────────────────────────────┐
        │ FileSystemEvidenceStorage (private dir, signed) │
        └────────────────────────────────────────────────┘
```

---

## 1. Repository layout

```
D:\React-native\WashingApp\
├── Car Wash Platform - Improved Implementation Plan.pdf   (source of truth)
├── docs/
│   ├── REQUIREMENTS_ANALYSIS.md
│   ├── ARCHITECTURE.md                ← this file
│   ├── IMPLEMENTATION_PLAN.md
│   └── REQUIREMENTS_AUDIT.md
├── backend/
└── washing-app/                        (existing Expo project; extended in place)
```

`washing-app` is kept as the mobile project directory because it already contains the Expo
scaffold, assets, theme constants and colour-scheme hooks that are worth preserving.

---

## 2. Backend structure

```
backend/
├── manage.py
├── pyproject.toml                     # deps + pytest/ruff/mypy config
├── .env.example
├── pytest.ini / conftest.py
├── config/
│   ├── settings/{__init__,base,dev,test,prod}.py
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
├── apps/
│   ├── common/          # TimeStampedModel, UUID pk base, permissions, error
│   │                    #   envelope, exception handler, pagination, throttles,
│   │                    #   idempotency mixin, audit helper, money/decimal utils,
│   │                    #   request-id middleware, health view
│   ├── identity/        # User, RoleGrant, OtpChallenge, RefreshToken,
│   │                    #   ConsentRecord, NotificationPreference, Device
│   ├── locations/       # Address, ServiceZone, ZoneServiceWindow, SiteRestriction
│   ├── catalog/         # Vehicle, ServiceType, AddOn, PriceRuleVersion
│   ├── quotes/          # Quote, QuoteLine
│   ├── partners/        # PartnerProfile, PartnerDocument, PartnerServiceSkill,
│   │                    #   PartnerEquipmentItem, PartnerShift,
│   │                    #   PartnerAvailabilityWindow, PartnerLocationPing
│   ├── bookings/        # Booking, BookingEvent, Cancellation, Acknowledgement
│   ├── dispatch/        # DispatchOffer
│   ├── evidence/        # JobEvidence
│   ├── payments/        # PaymentMethodToken, PaymentAttempt, LedgerEntry, Refund,
│   │                    #   PartnerPayable, PayoutBatch, ReconciliationItem
│   ├── comms/           # ChatThread, ChatMessage, CallRelaySession
│   ├── notifications/   # Notification, OutboxEvent
│   ├── support/         # SupportCase
│   ├── webhooks/        # ProviderWebhookEvent + receiver views
│   └── ops/             # operations console API + dashboards
├── tests/                             # per-app tests live in apps/<app>/tests/
└── scripts/                           # seed_demo, bootstrap helpers
```

### Layering rules (enforced by convention and review)

| Layer | May import | Must NOT |
|---|---|---|
| `api/` (views, serializers, urls, permissions) | `services/`, `domain/`, models, `common` | contain business rules |
| `services/` | `domain/`, `ports/`, models, `common` | know about request/response, DRF |
| `domain/` | pure python (+ pydantic-free dataclasses) | touch the ORM |
| `ports/` | nothing but stdlib typing | import adapters |
| `adapters/` (gateway impls) | `ports/`, SDK | be imported by `domain/` |

Business rules live in `services/`. Viewsets stay thin: validate → call service → serialise.

---

## 3. Django apps and responsibilities

| App | Models | Services | Notes |
|---|---|---|---|
| `common` | `AdminAuditLog`, `RequestAudit`, `IdempotencyRecord` | `audit`, `idempotency`, `money`, `timeutil`, `errors` | No domain models |
| `identity` | `User`, `RoleGrant`, `OtpChallenge`, `RefreshToken`, `ConsentRecord`, `NotificationPreference`, `Device` | `otp`, `tokens`, `registration` | Custom user model, phone-based identity |
| `locations` | `Address`, `ServiceZone`, `ZoneServiceWindow`, `SiteRestriction` | `zone_geo` (point-in-polygon, bbox), `availability`, `site_rules` | GeoJSON + indexed bbox |
| `catalog` | `Vehicle`, `ServiceType`, `AddOn`, `PriceRuleVersion` | `pricing_rules` (rule evaluation) | Size tier derivation |
| `quotes` | `Quote`, `QuoteLine` | `quote_service` (build, lock, expire) | Server recomputes all lines |
| `partners` | `PartnerProfile`, `PartnerDocument`, `PartnerServiceSkill`, `PartnerEquipmentItem`, `PartnerShift`, `PartnerAvailabilityWindow`, `PartnerLocationPing` | `readiness`, `availability`, `location_ingest`, `earnings` | Readiness gate for offers |
| `bookings` | `Booking`, `BookingEvent`, `Cancellation`, `Acknowledgement` | `state_machine`, `booking_commands`, `cancellation` | Authoritative lifecycle |
| `dispatch` | `DispatchOffer` | `eligibility`, `ranking`, `offers`, `dispatcher`, `monitoring` | ETA + fairness ranking |
| `evidence` | `JobEvidence` | `evidence_service`, `retention` | Storage port, checksum |
| `payments` | `PaymentMethodToken`, `PaymentAttempt`, `LedgerEntry`, `Refund`, `PartnerPayable`, `PayoutBatch`, `ReconciliationItem` | `ledger`, `authorisation`, `capture`, `refunds`, `payables`, `payouts`, `reconciliation` | Append-only ledger |
| `comms` | `ChatThread`, `ChatMessage`, `CallRelaySession` | `masking`, `thread_window` | Window enforcement |
| `notifications` | `Notification`, `OutboxEvent` | `outbox`, `delivery`, `push` | Transactional outbox |
| `support` | `SupportCase` | `case_service`, `sla` | Evidence freeze |
| `webhooks` | `ProviderWebhookEvent` | `signature`, `ingest`, `processor` | Persist before process |
| `ops` | — | `dashboards`, `manual_assignment`, `exceptions_queue` | Console API only |

---

## 4. Booking state machine

```
                    ┌─────────────────── exception branches ───────────────────┐
                    │                                                       │
  requested ──► quote_accepted ──► dispatching ──► assigned ──► en_route ──► arrived
                    │                    │              │           │            │
                    │                    │              │           │            ▼
                    │                    │              │           │       in_service
                    │                    │              │           │            │
                    │                    │              │           │            ▼
                    │                    │              │           │       completed
                    │                    │              │           │            │
                    │                    │              │           │            ▼
                    │                    │              │           │     payment_captured
                    │                    │              │           │            │
                    │                    │              │           │            ▼
                    │                    │              │           │   partner_payout_eligible
                    │                    ▼              ▼           ▼            │
                    │              expired_offer  reassigned  cancelled /        │
                    │              no_partner_available        disputed_work     │
                    │              partner_no_show             refund_requested  │
                    │              unsafe_site                payment_failed    │
                    └───────────────────────────────────────────────────────────┘
```

Terminal states: `cancelled`, `refunded`, `partner_no_show`, `payment_failed`, `expired_offer`.

**Enforcement**
- `domain/state_machine.py` holds a declarative transition table: `{from_state: {action: to_state, roles: [...], guards: [...]}}`.
- Every mutation goes through `booking_commands.apply(booking, action, actor, **kwargs)` inside
  `transaction.atomic()` with `select_for_update()` on the booking row.
- Invalid action → `InvalidStateTransition` → HTTP 409 `invalid_state_transition`.
- Each accepted transition appends an immutable `BookingEvent` with `seq`, `from_status`, `to_status`,
  `actor_type`, `actor`, `occurred_at`.
- `ops` override uses the same table but requires `reason` and writes `AdminAuditLog` in the same
  transaction.
- Price immutability: once `quote.locked_at` is set, any write to `total_minor` is blocked by
  `Booking.save()` guard; a price change requires a customer-approved re-quote
  (`POST /bookings/{ref}/reprice-approval`), which the MVP does not expose to customers beyond
  cancelling and rebooking. Guarded server-side regardless.

**Atomic booking lock** (`dispatch/offers` accept):
```python
with transaction.atomic():
    booking = Booking.objects.select_for_update().get(reference=ref)
    offer  = DispatchOffer.objects.select_for_update().get(id=offer_id)
    if offer.status != PENDING or offer.expires_at <= now: raise OfferExpired
    if booking.status != DISPATCHING: raise BookingAlreadyAssigned
    offer.status, booking.partner_id, booking.status = ACCEPTED, partner, ASSIGNED
    # supersede all sibling offers in the same transaction
    DispatchOffer.objects.filter(booking=booking).exclude(pk=offer.pk)\
        .update(status=SUPERSEDED)
    BookingEvent.objects.create(...)          # assigned
    OutboxEvent.objects.create(topic="booking.assigned", ...)   # transactional outbox
```
Exactly one acceptance can win; no duplicate partner work, no duplicate capture.

---

## 5. Data model highlights (indexes & constraints)

- UUID primary keys everywhere (`models.UUIDField(primary_key=True, default=uuid4)`).
- Composite indexes match the query patterns actually used:
  - `Booking`: `(customer, status)`, `(partner, status)`, `(status, window_start)`, `(zone, scheduled_start)`
  - `DispatchOffer`: `(partner, status, expires_at)` — the partner offer-feed query
  - `JobEvidence`: `(booking, evidence_type, sequence)`
  - `PartnerLocationPing`: `(partner, recorded_at DESC)` — latest-ping + staleness query
  - `ServiceZone`: bbox columns — spatial pre-filter before point-in-polygon
  - `Notification`: `(user, created_at DESC)`, `(user, read_at)`
- Unique constraints as safety nets: `User.phone`, `Booking.reference`, `Booking.idempotency_key`,
  `IdempotencyRecord.key`, `DispatchOffer(booking, partner)`, `PartnerPayable(booking, partner)`,
  `ProviderWebhookEvent(provider, provider_event_id)`, `JobEvidence.object_key`,
  `PaymentAttempt(provider, provider_ref)`.
- Append-only enforcement: `LedgerEntry`, `BookingEvent`, `AdminAuditLog`, `PartnerLocationPing`
  get a `save()` guard that raises on update of business fields, and no `delete()` is exposed.
- Money: `PositiveIntegerField` minor units + `CharField(max_length=3)` currency; a `Money` value
  object in `common.money` handles arithmetic and formatting. No floats anywhere.
- Time: `USE_TZ=True`, `TIME_ZONE='UTC'`; rendered per-zone on the client using the zone's IANA tz.

---

## 6. Authentication & tokens

**Why OTP + rotating refresh tokens.** The existing scaffold already establishes phone + OTP as the
onboarding intent; the PDF requires identity, consent and verification records. Passwords are avoided
for customers/partners (no password to phish or leak), but staff (`ops`/`admin`) get a password *plus*
an enforced MFA challenge, per §05.

| Token | Lifetime | Storage (mobile) | Storage (server) |
|---|---|---|---|
| Access (JWT HS256) | 15 min (env) | memory only | not stored (stateless verify) |
| Refresh (opaque, random 256-bit) | 30 days (env) | `expo-secure-store` | `RefreshToken.token_hash` (SHA-256), never plaintext |
| OTP code | 5 min | n/a | `OtpChallenge.code_hash` (PBKDF2), never plaintext |

Refresh rotation with **reuse detection**: presenting a rotated/revoked token revokes the whole
`family` and emits a security log. Roles are embedded in the access token *and* re-checked against
the DB on privileged endpoints (defence against stale role grants).

Staff MFA: `POST /auth/staff/mfa` issues a challenge; staff cannot call any `ops` endpoint until a
valid second factor is exchanged for a short-lived `ops` access token.

Secrets: `DJANGO_SECRET_KEY`, OTP pepper, idempotency HMAC key — env only. `.env.example` ships with
empty placeholders. No secret in source.

---

## 7. Authorization (RBAC)

- `RoleGrant` is the single source of truth for roles. `User.has_role()` reads it.
- DRF permission classes: `IsCustomer`, `IsPartner`, `IsOps`, `IsAdmin`, `IsBookingParty`,
  `IsEvidenceReader` (policy-based), `ReadOnly`.
- Object-level checks are explicit, never implicit:
  - customer endpoints filter `customer=request.user`
  - partner endpoints filter `partner=profile_for(request.user)`
  - booking reads use `IsBookingParty` (customer, assigned partner, or ops/admin)
  - `PartnerDocument` identity docs are readable only by `admin` or the verifying role — enforced in
    `PartnerDocumentQuerySet.for_actor()`
- Every service function re-verifies ownership/role rather than trusting the view. "Never trust data
  coming from the mobile application."
- Privilege escalation guards: role grants are never settable through customer/partner serializers
  (read-only field); a partner cannot self-`approve` or self-`suspend`; `commission_bps` is ops/admin
  only; registration cannot pass a `role` in the payload.

---

## 8. Error handling

Single exception handler producing one envelope everywhere:

```json
{ "error": { "code": "invalid_state_transition", "message": "...",
             "details": {...}, "request_id": "..." } }
```

Domain exceptions in `common/errors.py` map to codes and statuses:
`Unauthenticated→401`, `PermissionDenied→403`, `NotFound→404`, `ValidationFailed→400`,
`Conflict→409`, `Gone/Expired→410`, `RateLimited→429`, `Unprocessable→422`.
DRF's own 400/401/403/404/405 responses are normalised to the same envelope, so the mobile client has
exactly one error shape. Mobile `ApiError` mirrors it.

---

## 9. Idempotency, outbox, retries

**Idempotency** — `IdempotencyMiddleware` on unsafe methods: requires `Idempotency-Key`, locks the
record, compares a request fingerprint, replays the stored response for a completed key, returns
`409 idempotency_key_reuse_mismatch` when the fingerprint differs. Applied to: create booking, accept
offer, authorize, capture, refund, create payout batch, upload evidence.

**Transactional outbox** — domain services write `OutboxEvent` rows inside the same transaction as the
state change, so "a database commit cannot succeed while losing the dispatch/notification event".
`python manage.py run_outbox` claims pending events with `select_for_update(skip_locked=True)`,
dispatches, marks delivered, and on repeated failure moves to `dead_letter` for operator visibility
(`OpsOutboxViewSet`).

**Monitoring job** — `run_job_monitor` detects stale locations and missed milestones and raises ops
alerts *before* automatic reassignment.

---

## 10. Third-party ports (replaceable adapters)

| Port | Default adapter (`sandbox`) | Real adapter slot |
|---|---|---|
| `ports.PaymentGateway` | `SandboxPaymentGateway` — authorize/capture/refund/payout/void, deterministic decline scenarios, signed webhooks | any marketplace-capable PSP |
| `ports.PushProvider` | `ExpoPushProvider` | FCM/APNs direct |
| `ports.EtaProvider` | `EstimatedEtaProvider` (haversine × assumed speed, labelled an estimate) | road-ETA/geocoding provider |
| `ports.EvidenceStorage` | `FileSystemEvidenceStorage` (private dir, checksum, signed short-lived reads) | S3-compatible private bucket |
| `ports.CommsProvider` | `RelayCommsProvider` (server-side masked number) | masked-communications vendor |

Selected via env (`PAYMENT_GATEWAY=sandbox`, etc.). No adapter imports a concrete SDK outside itself.

---

## 11. Mobile architecture

### Navigation (Expo Router, file-based)

```
app/
├── _layout.tsx                 # providers + splash + <AuthGate>
├── +not-found.tsx
├── (auth)/
│   ├── _layout.tsx             # Stack, no header
│   ├── phone.tsx
│   ├── otp.tsx                 # ?challengeId=
│   └── register/
│       ├── customer.tsx
│       └── partner.tsx
├── (customer)/                # tabs — customer experience
│   ├── _layout.tsx
│   ├── index.tsx               # home: active job, next booking, quick actions
│   ├── garage.tsx  → garage/[id].tsx, garage/new.tsx
│   ├── addresses.tsx → addresses/new.tsx, addresses/[id].tsx
│   ├── bookings.tsx → bookings/[reference].tsx
│   ├── services.tsx
│   ├── notifications.tsx
│   └── profile.tsx
├── (partner)/                 # tabs — partner experience (distinct)
│   ├── _layout.tsx
│   ├── index.tsx               # shift toggle, live offers, earnings snapshot
│   ├── availability.tsx
│   ├── earnings.tsx
│   └── profile.tsx
├── (ops)/                     # tabs — operations (staff only)
│   ├── _layout.tsx
│   ├── index.tsx               # job board
│   ├── exceptions.tsx
│   ├── partners.tsx
│   ├── zones.tsx
│   ├── refunds.tsx
│   ├── cases.tsx
│   ├── reconciliation.tsx
│   └── dashboard.tsx
└── booking/                    # shared stack routes (role-aware content)
    ├── quote.tsx               # builder
    ├── quote-review.tsx
    ├── confirm.tsx
    ├── [reference]/
    │   ├── job.tsx             # partner fulfilment
    │   ├── checklist.tsx
    │   ├── evidence.tsx        # guided capture
    │   ├── comms.tsx
    │   ├── report.tsx
    │   └── rate.tsx
```

Route protection: root `_layout` renders an `AuthGate` that reads session state and redirects:
no session → `/(auth)/phone`; session + `account_complete=false` → `/(auth)/register/*`;
role customer → `/(customer)`; partner → `/(partner)`; ops/admin → `/(ops)`.
Route groups keep customer and partner experiences visually and structurally distinct per §02.

### State management

- **TanStack Query** is the only server-state store. Query keys centralised in `src/query/keys.ts`
  so invalidation is systematic (`['booking', reference]`, `['offers']`, `['notifications']`, …).
- **AuthContext** holds only session identity + roles + token refs. Not a general store.
- Mutations invalidate the affected keys; booking detail screens poll (`refetchInterval`) while a job
  is active, and switch to push/refetch-on-focus when backgrounded.
- No Redux/Zustand — unnecessary dependency for this state shape.

### API layer (`src/api`)

`client.ts` is the only place that touches the network:
- base URL from `EXPO_PUBLIC_API_URL` (`.env`), validated at startup; throws a clear config error if
  missing — **no hardcoded URLs**.
- attaches `Authorization`, `X-Request-Id` (uuid), `Idempotency-Key` (auto for commands),
  `Content-Type`, `Accept`.
- **401 handling**: single-flight refresh; concurrent requests queue behind one refresh; original
  request replayed once; on refresh failure → sign out and redirect to `/(auth)/phone`.
- **Retry**: only for idempotent reads and only on network error / 5xx / 429-with-`Retry-After`;
  exponential backoff with jitter, max 3 attempts. Never blind-retries a non-idempotent POST.
- **Error normalization**: every failure becomes `ApiError { status, code, message, details, requestId, isNetworkError }`.
- **Timeouts** via `AbortController` (default 20 s, 60 s for uploads).
- `endpoints/*.ts` — one typed function per use case, returning parsed DTOs. Screens never build URLs.

### Offline / resilience behaviour

- `useNetworkStatus` (expo-network) drives a global offline banner.
- Mutations that fail with a network error show a retry affordance; nothing is silently queued.
- Reads are cached by TanStack Query but booking/quote screens show an explicit
  "last updated at" timestamp; stale GPS is never presented as live (§02).
- Booking creation requires connectivity — an honest failure instead of a phantom booking.

### Forms, validation, states

- React Hook Form + Zod. Shared schemas in `src/lib/schemas/*.ts` (phone, otp, customer profile,
  vehicle, address, partner application, availability, checklist, report, refund).
- Reusable UI kit in `src/components/ui`: `Screen`, `AppButton`, `TextField`, `SelectField`,
  `Card`, `Badge`, `Money`, `StatusBadge`, `Timeline`, `EmptyState`, `ErrorState`,
  `LoadingState`/`Skeleton`, `ConfirmSheet`, `Stepper`, `Chip`, `Banner`, `CountdownPill`.
- Every list screen implements loading / empty / error(+retry) / content, with pull-to-refresh.
- Keyboard: `KeyboardAvoidingView` + `keyboardShouldPersistTaps` on forms; scroll-to-error.
- Accessibility: roles/labels on controls, 44pt touch targets, `accessibilityLiveRegion` for status
  changes, dynamic-type-safe layouts, `AccessibilityInfo.announceCurrency` for screen readers.
- `expo-image-picker` + `expo-image` + `expo-file-system` for evidence; `expo-location` for partner
  pings with the on-shift gate enforced client-side *and* server-side; `expo-secure-store` for the
  refresh token; `expo-notifications` for push; `expo-web-browser` for T&Cs.

---

## 12. Environment configuration

**Backend `.env`** (never committed; `.env.example` provided):
`DJANGO_SETTINGS_MODULE`, `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`,
`POSTGRES_DB/USER/PASSWORD/HOST/PORT`, `JWT_SIGNING_KEY`, `JWT_ACCESS_TTL_MINUTES`,
`JWT_REFRESH_TTL_DAYS`, `OTP_PEPPER`, `OTP_TTL_MINUTES`, `OTP_MAX_ATTEMPTS`, `OTP_RATE_LIMIT`,
`IDEMPOTENCY_TTL_HOURS`, `CORS_ALLOWED_ORIGINS`, `EVIDENCE_STORAGE_BACKEND`, `EVIDENCE_ROOT`,
`EVIDENCE_RETENTION_DAYS`, `PAYMENT_GATEWAY`, `PAYMENT_WEBHOOK_SECRET`, `PUSH_PROVIDER`,
`EXPO_PUSH_ENABLED`, `ETA_PROVIDER`, `COMMS_PROVIDER`, `DEFAULT_CURRENCY`,
`PLATFORM_TIMEZONE`, `DISPATCH_*` caps, `REFUND_APPROVAL_LIMIT_MINOR`, `COMMUNICATION_WINDOW_MINUTES`,
`RATE_LIMIT_*`, `LOG_LEVEL`.

**Mobile `.env`**: `EXPO_PUBLIC_API_URL`, `EXPO_PUBLIC_ENV`, `EXPO_PUBLIC_ENABLE_EVIDENCE_UPLOADS`.
Only `EXPO_PUBLIC_*` is inlined into the bundle; no secrets exist on the client by design.

Settings split: `base` → `dev` (verbose, console email, sandbox gateways) → `test` (in-memory-ish,
eager outbox off, throttles relaxed) → `prod` (secure proxy headers, HSTS, no debug, strict CORS,
required env validation that refuses to boot on missing secrets).

---

## 13. Key architectural decisions (and why)

1. **Modular monolith, not microservices** — PDF §02 explicitly rejects premature splitting.
   Django apps give module boundaries with a shared transaction, which the booking lock depends on.
2. **PostgreSQL row locks as the booking lock** — PDF says Redis "is not the source of truth" and
   "keep PostgreSQL transactions authoritative during the pilot". Avoids a Redis dependency.
3. **Transactional outbox + management-command worker instead of Celery** — satisfies the reliability
   requirement without adding broker infrastructure. Adapter slot documented for when scale requires it.
4. **Append-only event/ledger tables, relational current-state tables** — PDF §04: "relational records
   for current business truth and append-only events for history".
5. **Server recomputes every quote line** — client totals are never trusted; the price rule version is
   stored with the quote.
6. **Debounced declarative state machine in `domain/`** — the single enforcement point for the PDF's
   hard rule that a client cannot skip states or alter an accepted price.
7. **Evidence as object key + checksum + retention metadata, never DB blobs** — PDF §04 explicit.
8. **One Expo app, distinct role route groups** — satisfies "keep customer and partner experiences
   distinct" while shipping a single binary.
9. **Access token in memory, refresh token in SecureStore** — limits token exposure if the app process
   is inspected; rotation with reuse detection gives revocation.
10. **Ports for every external provider** — PDF repeatedly demands replaceable provider integrations.
11. **GeoJSON + indexed bbox instead of mandatory PostGIS** — keeps plain PostgreSQL the only hard
    dependency; PostGIS upgrade documented.
12. **Ops delivered as an audited API + Django admin** — the user's stack has no web front-end; this
    gives the console a complete, permissioned backend without inventing unrequested tooling.

---

## 14. Testing strategy

**Backend** — `pytest` + `pytest-django` + `factory_boy`.
Per app: model constraints, service/business-rule tests, serializer validation, API status/permission
tests, and explicit negative tests for: unauthenticated, wrong role, non-owner, expired token, stale
location, expired quote/offer, illegal state transition, idempotency replay/mismatch, refund limits,
webhook signature failure, duplicate webhook, reconciliation mismatch.

**Mobile** — `jest-expo` + `@testing-library/react-native`.
Component tests for the UI kit, form validation tests per schema, navigation/protected-route tests,
API-client tests (auth header, 401 refresh queue, retry policy, error normalization), and
role-based-visibility tests.

**Not mocked**: business rules are tested against the real service layer; the mobile API tests run
against recorded real response shapes.
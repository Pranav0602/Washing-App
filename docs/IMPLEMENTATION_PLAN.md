# Phase 3 — Implementation Plan

Ten phases. Each phase lists files, dependencies, tasks, tests, and an exit gate.
The gate must pass before the next phase starts.

Legend for effort: **S** ≤ half day · **M** 1–2 days · **L** 3+ days.

---

## Phase 1 — Project foundation

**Effort:** M

### Files
```
backend/manage.py
backend/pyproject.toml
backend/.env.example
backend/pytest.ini
backend/conftest.py
backend/config/__init__.py
backend/config/settings/{__init__,base,dev,test,prod}.py
backend/config/urls.py  config/wsgi.py  config/asgi.py
backend/apps/__init__.py
backend/apps/common/…          (base models, errors, middleware, health)
washing-app/.env.example
```
Modify: `washing-app/package.json` (add deps + scripts), `washing-app/app.json`
(`extra.eas`, `scheme`, permissions), `washing-app/tsconfig.json` (keep strict; add paths).
Delete: `washing-app/App.tsx` (dead — `main` is `expo-router/entry`).
Preserve: `components/themed-*.tsx`, `hooks/use-color-scheme*`, `constants/theme.ts`, `assets/`.

### Dependencies
Backend: `Django`, `djangorestframework`, `psycopg[binary]`, `django-cors-headers`,
`python-dotenv`, `PyJWT`, `django-filter`, `drf-spectacular`(optional; skip if unwanted),
`pytest`, `pytest-django`, `pytest-cov`, `factory-boy`, `ruff`, `mypy`(light).
Mobile: `expo-secure-store`, `expo-image-picker`, `expo-image`, `expo-file-system`,
`expo-location`, `expo-notifications`, `expo-network`, `@tanstack/react-query`,
`react-hook-form`, `zod`, `@hookform/resolvers`, `expo-dev-client`(optional).

### Tasks
1. Split settings base/dev/test/prod; env-driven; `prod` refuses to boot without required secrets.
2. PostgreSQL via env; `psycopg3`; `CONN_MAX_AGE`; health-check view.
3. Common app: `TimeStampedUUIDModel` base, `AdminAuditLog`, `RequestAudit`,
   `IdempotencyRecord`, error envelope + `exception_handler`, `X-Request-Id` middleware,
   money helpers, UTC time helpers, default pagination.
4. CORS from env; security headers; throttles from env.
5. Mobile: remove dead `App.tsx`; add `src/lib/env.ts` with startup validation; set up
   `src/theme` reusing `constants/theme.ts`; add deps; verify `npx tsc --noEmit` is clean.

### Tests
- Settings import cleanly for all four environments.
- Error envelope shape for 404/400/500.
- `X-Request-Id` generated when absent, echoed when present.
- Money helpers round-trip minor units.
- `tsc --noEmit` passes.

### Gate
`manage.py check` clean; `pytest` green; `npx tsc --noEmit` clean; no secrets in the repo.

---

## Phase 2 — Identity, roles, RBAC, auth

**Effort:** M

### Files
```
backend/apps/identity/models.py         User, RoleGrant, OtpChallenge, RefreshToken,
                                        ConsentRecord, NotificationPreference, Device
backend/apps/identity/services/{otp,tokens,registration}.py
backend/apps/identity/serializers.py
backend/apps/identity/views.py          auth + me endpoints
backend/apps/identity/permissions.py    IsCustomer/IsPartner/IsOps/IsAdmin
backend/apps/identity/urls.py
backend/apps/identity/migrations/0001_initial.py
backend/apps/identity/tests/…
```

### Tasks
1. Custom `User` (phone unique, `account_complete`, consent fields, soft-delete fields).
2. `RoleGrant`; `User.has_role()`; never assignable from client serializers.
3. OTP request/verify/resend with PBKDF2 hashing, attempt limits, lockout, cooldown, rate limits.
   Phone numbers normalised to E.164.
4. JWT access tokens (short TTL) + opaque rotating refresh tokens with **family reuse detection**.
5. Staff login with enforced MFA challenge gate on `ops` endpoints.
6. `register/customer` (profile + first address + first vehicle + consents) and
   `register/partner` (application → `pending_verification`).
7. `/me`, `/me/preferences`, `/me/consents`, `/me/data-requests`.
8. Permissions classes + DRP wiring.

### Tests
- OTP happy path, wrong code, expiry, attempt lockout, resend cooldown, rate limit (429).
- Refresh rotation works; reuse of a rotated token revokes the family.
- Access token carries roles; role re-checked against DB on privileged endpoints.
- Registration cannot escalate privilege (`role`, `commission_bps`, `status` ignored/rejected).
- Customer cannot call a partner endpoint (403); anonymous cannot call a protected endpoint (401).
- Consent is required and versioned.

### Gate
Full auth + RBAC suite green. Mobile login API integrated later in Phase 5.

---

## Phase 3 — Supply, catalog, zones, pricing, quotes

**Effort:** L

### Files
```
backend/apps/locations/{models,services/*,serializers,views,urls}.py
backend/apps/catalog/{models,services/*,serializers,views,urls}.py
backend/apps/quotes/{models,services/*,serializers,views,urls}.py
backend/apps/partners/models.py          (profile, documents, skills, equipment, shifts,
                                          availability windows, location pings)
backend/apps/partners/services/{readiness,availability,location_ingest}.py
seed script: backend/scripts/seed_demo.py
```

### Tasks
1. `Address` (lat/lng, `site_type`, access notes, parking details, property approval).
2. `ServiceZone` (GeoJSON polygon + indexed bbox), `ZoneServiceWindow`, `SiteRestriction`.
3. `ServiceType`, `AddOn`, `PriceRuleVersion`; vehicle **size-tier** derivation.
4. **Zone geo**: bbox pre-filter + ray-casting point-in-polygon; `ServiceZone.contains()`.
5. **Site rules**: block a service at an unsupported site type (`site_method_not_permitted`).
6. **Availability**: service windows, capacity cap, on-demand gating (radius + staffed hours).
7. **Pricing engine** `services/pricing.py`: base + tier + add-ons + zone/travel + tax + fees −
   discounts; writes `QuoteLine` rows; stores `price_rule_version`; tax bps defaults to 0.
8. Quote lifecycle: create → `quoted` → accept → `locked`; expiry sweep command.
9. Partner readiness gate: verified ∧ insurance valid ∧ kit current ∧ assessment passed ∧ not suspended.
10. Location ingest: reject when neither on-shift nor active job; reject stale/out-of-order; prune.
11. Seed script: zones, windows, services, add-ons, price rule, demo customer/partner/admin.

### Tests
- Point-in-polygon inside/outside/boundary; bbox index actually used.
- Service blocked at a prohibited site type; allowed at a permitted one.
- Quote line arithmetic for every combination; rounding; tax bps 0 and non-zero.
- Client-supplied totals are ignored — server recomputes.
- Quote expiry boundary (just before / exactly at / after).
- Capacity cap and on-demand gating enforced server-side.
- Partner not eligible for offers when insurance/kit/assessment expired.
- Location ping rejected off-shift, and rejected when out-of-order.

### Gate
Pricing is deterministic and auditable; site/zone rules enforced server-side; seed runs clean.

---

## Phase 4 — Bookings, dispatch, evidence, payments

**Effort:** L

### Files
```
backend/apps/bookings/{models,domain/state_machine.py,services/*,serializers,views,urls}.py
backend/apps/dispatch/{models,services/{eligibility,ranking,offers,dispatcher,monitoring},
                        ports/eta.py,serializers,views,urls}.py
backend/apps/evidence/{models,services/*,ports/storage.py,serializers,views,urls}.py
backend/apps/payments/{models,ports/gateway.py,adapters/sandbox.py,
                       services/{ledger,authorisation,capture,refunds,payables,payouts,reconciliation}.py,
                       serializers,views,urls}.py
backend/apps/notifications/{models.py,ports/push.py,adapters/expo.py}
backend/apps/common/management/commands/{run_outbox,run_job_monitor,expire_quotes,prune_location}.py
```

### Tasks
1. **State machine** as a declarative transition table with role and guard checks; every transition
   writes an immutable `BookingEvent`; `Booking.save()` blocks price mutation after quote lock.
2. Booking create (idempotent), read, list with filters, cancel with policy snapshot, acknowledgement,
   rating (completed only), issue report.
3. **Eligibility** filter: zone polygon, open hours, service type, partner status, skills, equipment,
   capacity, travel limit, site restrictions.
4. **Ranking**: ETA + predicted arrival reliability, then a modest fairness factor for workload and
   recent offer history. No straight-line-distance-only ranking.
5. **Offers**: time-limited, single or small batch, expiry/retry/widen within configured caps;
   **atomic first-accept lock** with `select_for_update`; sibling offers superseded in the same
   transaction; no duplicate work or capture on reassignment.
6. **Arrival promise** published only after acceptance.
7. **Monitoring**: stale-location and missed-milestone detection → ops alert before auto-reassignment.
8. **Evidence**: content-type/size validation, SHA-256 checksum, sequence + guided checks
   (lighting/angle/identity), `access_policy`, `retention_deadline`, private storage + short-lived
   signed reads, deletion/legal-hold, retention sweep.
9. **Payments**: payment-method tokens only (reject anything resembling a PAN), authorize inside the
   provider window, capture at completion, refund ≤ captured with approval limit + recorded approver,
   append-only ledger, partner payable, payout batch, daily reconciliation, chargeback + failed-payout
   states.
10. **Transactional outbox** written inside every state-changing transaction; `run_outbox` worker with
    bounded retries and dead-letter.
11. Job commands: `arrive` (code verify) → `start` (requires pre-evidence) → checklist →
    evidence → `complete` (requires after-evidence + checklist confirmed).

### Tests
- Every legal transition succeeds; **every** illegal transition returns 409 `invalid_state_transition`.
- Price cannot be altered after acceptance (model guard + service guard).
- Concurrent offer acceptance → exactly one winner (threaded test).
- Expired offer acceptance → 409; already-accepted offer → 409.
- Eligibility excludes partner for each of the nine criteria independently.
- Reassignment leaves no duplicate active job and no second capture.
- `start` blocked without pre-evidence; `complete` blocked without after-evidence/checklist.
- Evidence: reject non-image, oversize, checksum mismatch, sequence conflict; wrong role → 403.
- Payment: no PAN stored; double capture → 409; refund > captured → 422; refund over approval limit → 403.
- Ledger append-only: update/delete raises.
- Webhook: bad signature → 401; duplicate event id → deduped, processed once; unmatched → surfaced.
- Idempotency: replay returns the stored response; fingerprint mismatch → 409.

### Gate
The full job loop works end-to-end in tests, and every negative path above is covered.

---

## Phase 5 — Communications, support, webhooks, ops console API

**Effort:** M

### Files
```
backend/apps/comms/{models,services/masking.py,serializers,views,urls}.py
backend/apps/support/{models,services/*,serializers,views,urls}.py
backend/apps/webhooks/{models,services/*,views,urls}.py
backend/apps/ops/{serializers,views/*,urls}.py, apps/ops/services/{dashboards,manual_assignment,exceptions_queue}.py
backend/apps/common/management/commands/{run_reconciliation,run_retention_sweep}.py
```
Register `ops` in Django admin.

### Tasks
1. Masked comms: thread auto-created on assignment; closes at completion + configurable support window;
   raw numbers never returned; relay returns a masked number; rate limited.
2. Support cases: categories (issue/damage/unsafe_site/emergency/payment/no_show), priority, SLA due
   date, **evidence freeze** blocking deletion, human-led resolution, liability decided by a person,
   refund authority tracking.
3. Webhook ingestion: signature verify → dedupe → **persist** → enqueue → process idempotently →
   surface unmatched for reconciliation.
4. Ops API: job board, exception queue, manual assign/reassign/override (**reason required** + audit),
   partner approvals/suspend, zone CRUD + pause, catalog/price-rule CRUD, refunds, support cases,
   reconciliation run + results, payouts + approve, dashboards, audit log, outbox + retry, webhooks view.
5. Pilot dashboard metrics, per §07, with the exact definitions: fulfilment, on-time arrival, customer
   rating (with response count + distribution), rework/refund rate, partner utilisation, contribution
   margin (unit-economics formula), repeat rate, safety/trust counts.
6. Retention sweep: evidence deadlines, comms thread expiry, notification pruning, location pruning.

### Tests
- Comms window: open during active booking, closed after window, wrong party → 403.
- Masked number returned; raw number absent from every response.
- Evidence freeze blocks deletion until released.
- Ops override without reason → 400; with reason → `AdminAuditLog` written in the same transaction.
- Ops cannot read identity verification documents (403) unless admin/verifier.
- Partner self-approval → 403.
- Refund beyond ops approval limit → 403.
- Dashboard metric definitions match §07 (numerator/denominator) on a fixed dataset.
- Webhook duplicate/unmatched/bad-signature paths.

### Gate
Ops can run the whole business by hand — the PDF's core promise for the pilot.

---

## Phase 6 — Mobile foundation

**Effort:** M

### Files
```
washing-app/src/lib/{env,result,format,apiError}.ts
washing-app/src/lib/schemas/*.ts
washing-app/src/api/{client.ts,types.ts}
washing-app/src/api/endpoints/{auth,me,vehicles,addresses,catalog,zones,quotes,bookings,
                               partners,dispatch,evidence,payments,comms,notifications,
                               support,ops}.ts
washing-app/src/query/{queryClient.ts,keys.ts}
washing-app/src/auth/{AuthContext.tsx,tokenStorage.ts,useAuth.ts,useRole.ts}
washing-app/src/components/ui/*.tsx
washing-app/src/theme/{colors,spacing,typography}.ts
washing-app/app/_layout.tsx, app/+not-found.tsx
washing-app/app/(auth)/{_layout,phone,otp}.tsx
washing-app/app/(auth)/register/{customer,partner}.tsx
```

### Tasks
1. `env.ts`: read `EXPO_PUBLIC_API_URL`, fail fast with a clear message; **no hardcoded URL**.
2. `client.ts`: auth header, request id, idempotency key, timeout via `AbortController`,
   single-flight refresh + one replay, bounded retry with jitter for safe methods only,
   `ApiError` normalization.
3. `queryClient.ts` with sensible defaults; `keys.ts` centralised.
4. `tokenStorage.ts` using `expo-secure-store` for refresh; access token in memory.
5. `AuthContext`: bootstrap from stored refresh, login/logout, role routing decision.
6. `AuthGate` + role-based redirects in the root layout.
7. Full UI kit: `Screen`, `AppButton`, `TextField`, `SelectField`, `Card`, `Badge`, `Money`,
   `StatusBadge`, `Timeline`, `EmptyState`, `ErrorState`, `Skeleton`, `ConfirmSheet`, `Banner`,
   `Stepper`, `Chip`, `CountdownPill`.
8. Shared Zod schemas + RHF wiring.
9. Auth screens: phone → OTP (resend + cooldown + attempts) → registration.
10. Loading / empty / error(+retry) primitives; offline banner via `expo-network`.

### Tests
- `client.ts`: header injection; 401 → refresh → replay once; refresh failure → sign-out;
  retry policy (reads retried, POSTs not); error normalization; timeout.
- `tokenStorage` round-trip; secure-store failure handling.
- Schema validation unit tests for every form schema.
- UI kit snapshot/behaviour tests for `Money`, `StatusBadge`, `EmptyState`, `ErrorState`.
- `AuthGate` redirects for: no session, incomplete account, customer, partner, ops.

### Gate
`npx tsc --noEmit` clean, `expo lint` clean, jest green, and the app boots to the phone screen
against a running backend.

---

## Phase 7 — Mobile feature screens

**Effort:** L

### Files
```
washing-app/app/(customer)/{_layout,index,garage,addresses,services,bookings,notifications,profile}.tsx
washing-app/app/(customer)/garage/{new,[id]}.tsx
washing-app/app/(customer)/addresses/{new,[id]}.tsx
washing-app/app/(customer)/bookings/[reference].tsx
washing-app/app/(customer)/profile.tsx
washing-app/app/(partner)/{_layout,index,availability,earnings,profile}.tsx
washing-app/app/(ops)/{_layout,index,exceptions,partners,zones,refunds,cases,reconciliation,dashboard}.tsx
washing-app/app/booking/{quote,quote-review,confirm}.tsx
washing-app/app/booking/[reference]/{job,checklist,evidence,comms,report,rate}.tsx
washing-app/src/components/booking/{StatusTimeline,PriceBreakdown,PromiseWindow,MaskedContact}.tsx
washing-app/src/components/evidence/{EvidenceUploader,GuidedCaptureStep}.tsx
washing-app/src/hooks/{useCountdown,useNetworkStatus,usePermissions}.ts
```

### Tasks
1. **Customer**: home (active job + next booking), garage CRUD, addresses with pin/site type/access
   notes, service catalog, quote builder, quote review (total, duration, inclusions/exclusions,
   expiry, cancellation terms), booking confirm + payment authorisation, booking list with filters,
   booking detail timeline, evidence viewer, issue report, rating, comms, notifications, profile.
2. **Partner**: shift/radius/capacity toggle, skills & equipment, live offer feed with countdown,
   offer detail with payout estimate + access notes, accept/decline, active job (navigate handoff,
   mark arrived, booking-code verify), guided evidence capture with lighting/angle/identity checks,
   checklist, complete, earnings summary, readiness/blockers panel, pause/unavailability.
3. **Ops**: job board, exception queue, job detail with manual assign/reassign/override (reason
   required), partner approvals, zones, refunds, cases, reconciliation, pilot dashboard.
4. Cross-cutting: pull-to-refresh, last-updated timestamps, honest "estimate" labelling for ETAs,
   countdown pills, keyboard handling, accessibility labels/live regions, offline banner,
   role-aware navigation that hides what a role cannot use.
5. Delete the 8 placeholder `screens/*.tsx` files and `App.tsx`.

### Tests
- Customer booking flow integration test (quote → accept → authorise) against a mocked API layer.
- Partner accept/decline + guarded transitions.
- Ops override requires a reason before the request is sent.
- Role-based UI: customer never sees partner/ops affordances and vice versa.
- Form validation errors surface inline for each required field.
- Empty, loading and error states render for every list screen.

### Gate
Both customer and partner journeys complete end-to-end against the real Django API.

---

## Phase 8 — Testing, hardening, verification

**Effort:** M

### Tasks
1. Fill coverage gaps found in Phases 2–7; target the negative paths listed in the plan.
2. Run the full backend suite and the mobile suite; record results.
3. `ruff check` + `ruff format --check`; `mypy` on services/domain.
4. `npx tsc --noEmit`; `expo lint`; `jest --coverage`.
5. Security sweep: no secrets, no hardcoded URLs, no raw card data path, file-upload validation,
   mass-assignment audit on every serializer (`fields`/`read_only`), permission audit on every
   viewset, SQL via ORM only, CORS/proxy/header config.
6. Migration check: `makemigrations --check --dry-run` is clean; `migrate` from empty DB works.
7. Dead-code sweep: unused exports, unused deps (`npx depcheck` equivalent), leftover debug
   statements.
8. Concurrency test for offer acceptance and booking lock under load.

### Gate
All suites green; lint/type checks clean; no critical open findings.

---

## Phase 9 — Production configuration & documentation

**Effort:** M

### Files
```
backend/config/settings/prod.py           (hardened)
backend/Dockerfile, docker-compose.yml   (Postgres + API + worker)
backend/scripts/{bootstrap,seed_demo}.sh
.env.example (backend + mobile)
README.md, docs/{API.md,DEPLOYMENT.md,TESTING.md,OPERATIONS.md}
docs/REQUIREMENTS_AUDIT.md
```

### Tasks
1. Prod settings: debug off, secure proxy SSL header, HSTS, strict CORS allowlist, required-secret
   validation, JSON logging with request id, DB connection pooling, throttling tightened.
2. Docker/compose for Postgres + API + outbox worker; health checks; migration-on-deploy step.
3. `.env.example` for both projects — placeholders only, never real credentials.
4. Documentation: install, backend setup, database setup, API reference, mobile dev, build/release,
   deployment, testing, operations runbook (exception queue, dead-letter handling, reconciliation,
   restore drill).
5. **Requirements audit** table: every PDF requirement → implemented → tested → location.
6. Fix everything the audit surfaces before declaring completion.

### Gate
A fresh clone can be brought to a running system from documentation alone, and the audit has no
unresolved critical rows.

---

## Build order summary

```
P1 foundation
      ↓
P2 identity/RBAC ──────────────┐
      ↓                        │
P3 catalog/zones/quotes        │
      ↓                        │
P4 bookings/dispatch/evidence/payments
      ↓                        │
P5 comms/support/webhooks/ops API
      ↓                        │
P6 mobile foundation ◄──────────┘
      ↓
P7 mobile screens
      ↓
P8 test + harden
      ↓
P9 prod config + docs + audit
```

Backend Phases 2–5 can be validated with the API test client alone; the mobile app is wired to the
real API from Phase 6 onward. Frontend and backend contracts are kept in sync by generating the
TypeScript DTO types from the same field names used in the DRF serializers and verifying with
`tsc` on both sides.
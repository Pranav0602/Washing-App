"""The pricing engine.

Implements the PDF's transparent quote formula exactly::

    service base + vehicle tier + selected add-ons + zone/travel
    + taxes/fees - discounts

Every step produces a persisted ``QuoteLine``. Two rules matter most:

1. **The server computes every amount.** Nothing about the price is taken from the
   request body, so a modified client cannot change what it pays.
2. **Weather and demand surcharges are deliberately absent.** The PDF forbids them at
   launch; the surcharge concept does not exist in this module, so it cannot be
   switched on by accident.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from apps.catalog.models import AddOn, PriceRuleVersion, ServiceType
from apps.common.enums import BookingMode
from apps.common.exceptions import (
    QuoteNotAccepted,
    Unprocessable,
    ValidationFailed,
)
from apps.common.money import Money
from apps.locations.models import Address, ServiceZone
from apps.locations.services import availability as availability_service
from apps.locations.services import geo
from apps.quotes.models import Quote, QuoteLine

logger = logging.getLogger("apps.quotes.pricing")

DEFAULT_QUOTE_TTL_MINUTES = 30


@dataclass
class PriceBreakdown:
    """Intermediate results, kept for logging and for the quote's audit trail."""

    currency: str
    lines: list[dict] = field(default_factory=list)
    subtotal: Money = field(default_factory=lambda: Money(0, "INR"))
    tax: Money = field(default_factory=lambda: Money(0, "INR"))
    fee: Money = field(default_factory=lambda: Money(0, "INR"))
    discount: Money = field(default_factory=lambda: Money(0, "INR"))
    duration_minutes: int = 0
    distance_km: float | None = None

    @property
    def total(self) -> Money:
        return self.subtotal + self.tax + self.fee - self.discount


def _tier_amount(rule: PriceRuleVersion, tier: str, currency: str) -> Money:
    table = rule.vehicle_tier_minor or {}
    return Money(int(table.get(tier, 0)), currency)


def _zone_travel_amount(
    rule: PriceRuleVersion, *, distance_km: float | None, currency: str
) -> Money:
    """Zone/travel component: a flat zone fee plus a per-km element.

    ``None`` distance means the service is outside any zone/travel pricing, which
    happens when no zone has been resolved.
    """
    table = rule.zone_travel_minor or {}
    flat = int(table.get("default", 0))
    per_km = int(table.get("per_km_minor", 0))
    if distance_km is None or distance_km <= 0:
        return Money(flat, currency)
    return Money(flat, currency) + Money(int(round(distance_km * per_km)), currency)


def _discount_amount(rule: PriceRuleVersion, coupon_code: str, base: Money) -> Money:
    """Resolve a coupon. Unknown or inapplicable coupons are rejected loudly."""
    if not coupon_code:
        return Money.zero(base.currency)
    rules = rule.discount_rules or {}
    rule = rules.get(coupon_code.upper())
    if not rule:
        raise ValidationFailed(
            "That promotion code is not valid.", details={"field": "coupon_code"}
        )
    kind = rule.get("type")
    if kind == "percent":
        # A percentage is a basis-point rate applied to the base. ``percentage_of``
        # puts its *receiver* in the numerator, so it cannot express this at all.
        return base.scale_basis_points(int(rule.get("bps", 0)))
    if kind == "fixed":
        amount = Money(int(rule.get("amount_minor", 0)), base.currency)
        return amount if amount.amount_minor <= base.amount_minor else base
    logger.warning("unknown discount rule type %r for coupon %s", kind, coupon_code)
    return Money.zero(base.currency)


def compute_quote(
    *,
    customer,
    vehicle,
    address: Address,
    service: ServiceType,
    addon_codes: list[str],
    booking_mode: str,
    window_start=None,
    window_end=None,
    coupon_code: str = "",
    rule: PriceRuleVersion | None = None,
) -> tuple[PriceBreakdown, ServiceZone, list[AddOn]]:
    """Price a wash. Pure calculation: no database writes.

    Returns the breakdown, the resolved zone and the validated add-ons so the caller
    can persist the quote.
    """
    rule = rule or PriceRuleVersion.current()
    currency = rule.currency or service.currency

    if currency != service.currency:
        raise Unprocessable(
            "This service is priced in a different currency.",
            code="currency_mismatch",
            details={"service_currency": service.currency, "quote_currency": currency},
        )

    # --- catalog and site eligibility --------------------------------------
    if not service.is_active:
        raise Unprocessable("This service is not currently available.", code="service_inactive")

    if not service.supports_vehicle_tier(vehicle.size_tier):
        raise Unprocessable(
            f"{service.name} is not available for a {vehicle.get_vehicle_type_display().lower()}.",
            code="service_not_offered_for_vehicle",
            details={"service_code": service.code, "vehicle_tier": vehicle.size_tier},
        )

    zone = availability_service.find_zone_for_point(address.latitude, address.longitude)
    if zone is None:
        raise Unprocessable(
            "We do not currently serve this address.",
            code="outside_service_area",
            details={"latitude": address.latitude, "longitude": address.longitude},
        )

    availability_service.assert_zone_bookable(zone)
    availability_service.assert_address_supports_service(address, service, zone)
    availability_service.assert_within_service_window(
        zone=zone, booking_mode=booking_mode, window_start=window_start
    )

    if booking_mode == BookingMode.ON_DEMAND:
        availability_service.assert_on_demand_in_radius(
            zone=zone, lat=address.latitude, lng=address.longitude
        )

    availability_service.assert_capacity_available(zone=zone, booking_mode=booking_mode)

    # --- distance for the travel component --------------------------------
    distance_km: float | None = None
    centroid = availability_service.zone_centroid(zone)
    if centroid is not None:
        distance_km = geo.haversine_km(
            centroid[0], centroid[1], address.latitude, address.longitude
        )

    # --- add-ons ----------------------------------------------------------
    requested = [code for code in addon_codes if code]
    addons = list(AddOn.objects.filter(code__in=requested, is_active=True))
    found_codes = {addon.code for addon in addons}
    missing = sorted(set(requested) - found_codes)
    if missing:
        raise ValidationFailed(
            "One or more selected options are unavailable.",
            details={"field": "addon_codes", "unavailable": missing},
        )

    for addon in addons:
        if not addon.supports_service(service.code):
            raise Unprocessable(
                f"{addon.name} is not available with {service.name}.",
                code="addon_not_offered_for_service",
                details={"addon_code": addon.code, "service_code": service.code},
            )
        if not addon.supports_site_type(address.site_type):
            raise Unprocessable(
                f"{addon.name} is not available at this site type.",
                code="addon_not_offered_at_site",
                details={"addon_code": addon.code, "site_type": address.site_type},
            )

    # --- build the lines --------------------------------------------------
    breakdown = PriceBreakdown(currency=currency)
    order = 0

    base = Money(service.base_price_minor, currency)
    breakdown.lines.append(
        {
            "line_type": QuoteLine.LineType.SERVICE_BASE,
            "ref_code": service.code,
            "description": service.name,
            "quantity": 1,
            "unit_price_minor": base.amount_minor,
            "amount_minor": base.amount_minor,
            "sort_order": order,
        }
    )
    order += 1
    breakdown.subtotal = breakdown.subtotal + base
    breakdown.duration_minutes += service.expected_duration_minutes

    tier = _tier_amount(rule, vehicle.size_tier, currency)
    if tier.amount_minor:
        breakdown.lines.append(
            {
                "line_type": QuoteLine.LineType.VEHICLE_TIER,
                "ref_code": vehicle.size_tier,
                "description": f"Adjustment for {vehicle.get_vehicle_type_display()}",
                "quantity": 1,
                "unit_price_minor": tier.amount_minor,
                "amount_minor": tier.amount_minor,
                "sort_order": order,
            }
        )
        order += 1
        breakdown.subtotal = breakdown.subtotal + tier

    for addon in sorted(addons, key=lambda item: item.sort_order):
        amount = Money(addon.price_minor, currency)
        breakdown.lines.append(
            {
                "line_type": QuoteLine.LineType.ADDON,
                "ref_code": addon.code,
                "description": addon.name,
                "quantity": 1,
                "unit_price_minor": amount.amount_minor,
                "amount_minor": amount.amount_minor,
                "sort_order": order,
            }
        )
        order += 1
        breakdown.subtotal = breakdown.subtotal + amount
        breakdown.duration_minutes += addon.duration_delta_minutes

    travel = _zone_travel_amount(rule, distance_km=distance_km, currency=currency)
    if travel.amount_minor:
        breakdown.lines.append(
            {
                "line_type": QuoteLine.LineType.ZONE_TRAVEL,
                "ref_code": zone.code,
                "description": f"Zone and travel charge ({zone.name})",
                "quantity": 1,
                "unit_price_minor": travel.amount_minor,
                "amount_minor": travel.amount_minor,
                "sort_order": order,
                "meta": {"distance_km": round(distance_km, 2) if distance_km else None},
            }
        )
        order += 1
        breakdown.subtotal = breakdown.subtotal + travel

    breakdown.distance_km = distance_km

    discount = _discount_amount(rule, coupon_code, breakdown.subtotal)
    if discount.amount_minor:
        breakdown.lines.append(
            {
                "line_type": QuoteLine.LineType.DISCOUNT,
                "ref_code": coupon_code.upper(),
                "description": "Promotion",
                "quantity": 1,
                "unit_price_minor": -discount.amount_minor,
                "amount_minor": -discount.amount_minor,
                "sort_order": order,
            }
        )
        order += 1
        breakdown.discount = discount

    fee = Money(rule.platform_fee_minor, currency)
    if fee.amount_minor:
        breakdown.lines.append(
            {
                "line_type": QuoteLine.LineType.FEE,
                "ref_code": "platform_fee",
                "description": "Service fee",
                "quantity": 1,
                "unit_price_minor": fee.amount_minor,
                "amount_minor": fee.amount_minor,
                "sort_order": order,
            }
        )
        breakdown.fee = fee

    tax = breakdown.subtotal.scale_basis_points(rule.tax_bps) - breakdown.discount.scale_basis_points(rule.tax_bps)
    tax = tax.clamp_non_negative()
    if tax.amount_minor:
        breakdown.lines.append(
            {
                "line_type": QuoteLine.LineType.TAX,
                "ref_code": f"tax_{rule.tax_bps}bps",
                "description": "Tax",
                "quantity": 1,
                "unit_price_minor": tax.amount_minor,
                "amount_minor": tax.amount_minor,
                "sort_order": order,
            }
        )
        breakdown.tax = tax

    return breakdown, zone, addons


@transaction.atomic
def create_quote(
    *,
    customer,
    vehicle,
    address: Address,
    service: ServiceType,
    addon_codes: list[str],
    booking_mode: str = BookingMode.SCHEDULED,
    window_start=None,
    window_end=None,
    coupon_code: str = "",
    ttl_minutes: int | None = None,
) -> Quote:
    """Price and persist a quote."""
    breakdown, zone, _addons = compute_quote(
        customer=customer,
        vehicle=vehicle,
        address=address,
        service=service,
        addon_codes=addon_codes,
        booking_mode=booking_mode,
        window_start=window_start,
        window_end=window_end,
        coupon_code=coupon_code,
    )

    ttl = ttl_minutes or DEFAULT_QUOTE_TTL_MINUTES
    rule = PriceRuleVersion.current()

    inclusions = list(service.inclusions or [])
    exclusions = list(service.exclusions or [])

    quote = Quote.objects.create(
        customer=customer,
        vehicle=vehicle,
        address=address,
        service=service,
        zone=zone,
        booking_mode=booking_mode,
        window_start=window_start,
        window_end=window_end,
        status=Quote.Status.QUOTED,
        currency=breakdown.currency,
        subtotal_minor=breakdown.subtotal.amount_minor,
        tax_minor=breakdown.tax.amount_minor,
        fee_minor=breakdown.fee.amount_minor,
        discount_minor=breakdown.discount.amount_minor,
        price_rule_version=rule,
        expected_duration_minutes=max(breakdown.duration_minutes, 0),
        distance_km=breakdown.distance_km,
        inclusions=inclusions,
        exclusions=exclusions,
        coupon_code=(coupon_code or "").upper(),
        expires_at=timezone.now() + timezone.timedelta(minutes=ttl),
    )

    for line in breakdown.lines:
        QuoteLine.objects.create(quote=quote, **line)

    # Only now that this quote exists is it safe to supersede older equivalents.
    # Two things matter here:
    #   * this runs *after* pricing succeeded, so a rejected quote request cannot
    #     invalidate a quote the customer was about to book;
    #   * the new quote is excluded explicitly, because its status is already
    #     ``quoted`` and it would otherwise supersede itself.
    Quote.objects.filter(
        customer=customer,
        vehicle=vehicle,
        address=address,
        service=service,
        status__in=(Quote.Status.QUOTED, Quote.Status.ACCEPTED),
        created_at__lt=quote.created_at,
    ).update(status=Quote.Status.SUPERSEDED, superseded_at=timezone.now())

    logger.info(
        "quote_created quote=%s total=%s %s lines=%s",
        quote.pk,
        quote.total_minor,
        quote.currency,
        len(breakdown.lines),
    )
    return quote


def accept_quote(*, quote: Quote, customer) -> Quote:
    """Mark a quote accepted. Booking creation then locks it."""
    if quote.customer_id != customer.pk:
        from apps.common.exceptions import PermissionDenied

        raise PermissionDenied("This quote belongs to another customer.")
    if quote.status == Quote.Status.EXPIRED or quote.is_expired:
        from apps.common.exceptions import QuoteExpired

        _mark_expired(quote)
        raise QuoteExpired(details={"quote_id": str(quote.pk)})
    if quote.status == Quote.Status.LOCKED:
        return quote
    if quote.status != Quote.Status.QUOTED:
        raise QuoteNotAccepted(details={"status": quote.status})

    quote.status = Quote.Status.ACCEPTED
    quote.accepted_at = timezone.now()
    quote.save(update_fields=["status", "accepted_at", "updated_at"])
    return quote


def lock_quote(*, quote: Quote) -> Quote:
    """Freeze the price once a booking exists.

    After this point the total must never change: the PDF is explicit that a client
    cannot alter an accepted price.
    """
    if quote.status == Quote.Status.LOCKED:
        return quote
    if quote.status not in (Quote.Status.ACCEPTED, Quote.Status.QUOTED):
        raise QuoteNotAccepted(details={"status": quote.status})
    quote.status = Quote.Status.LOCKED
    quote.locked_at = timezone.now()
    quote.save(update_fields=["status", "locked_at", "updated_at"])
    return quote


def decline_quote(*, quote: Quote, customer) -> Quote:
    if quote.customer_id != customer.pk:
        from apps.common.exceptions import PermissionDenied

        raise PermissionDenied("This quote belongs to another customer.")
    if quote.status in (Quote.Status.LOCKED,):
        raise QuoteNotAccepted(details={"status": quote.status})
    quote.status = Quote.Status.DECLINED
    quote.declined_at = timezone.now()
    quote.save(update_fields=["status", "declined_at", "updated_at"])
    return quote


def expire_quote(*, quote: Quote) -> Quote:
    if quote.status in (Quote.Status.LOCKED, Quote.Status.DECLINED, Quote.Status.EXPIRED):
        return quote
    quote.status = Quote.Status.EXPIRED
    quote.save(update_fields=["status", "updated_at"])
    return quote


def _mark_expired(quote: Quote) -> None:
    Quote.objects.filter(pk=quote.pk, status=Quote.Status.QUOTED).update(
        status=Quote.Status.EXPIRED
    )


def supersede_previous_quotes(*, customer, vehicle, address, service) -> int:
    """Mark older equivalent quotes superseded so only one is actionable."""
    return Quote.objects.filter(
        customer=customer,
        vehicle=vehicle,
        address=address,
        service=service,
        status__in=(Quote.Status.QUOTED, Quote.Status.ACCEPTED),
    ).update(status=Quote.Status.SUPERSEDED, superseded_at=timezone.now())


def expire_due_quotes() -> int:
    """Sweep for quotes whose window has closed."""

    count = Quote.objects.filter(
        status=Quote.Status.QUOTED, expires_at__lte=timezone.now()
    ).update(status=Quote.Status.EXPIRED)
    count += Quote.objects.filter(
        status=Quote.Status.ACCEPTED, expires_at__lte=timezone.now()
    ).update(status=Quote.Status.EXPIRED)
    return count


def assert_usable(quote: Quote, customer) -> Quote:
    """Guard used at booking creation."""
    if quote.customer_id != customer.pk:
        from apps.common.exceptions import PermissionDenied

        raise PermissionDenied("This quote belongs to another customer.")
    if quote.is_expired:
        _mark_expired(quote)
        from apps.common.exceptions import QuoteExpired

        raise QuoteExpired(details={"quote_id": str(quote.pk)})
    if quote.status not in (Quote.Status.QUOTED, Quote.Status.ACCEPTED):
        raise QuoteNotAccepted(details={"status": quote.status})
    return quote
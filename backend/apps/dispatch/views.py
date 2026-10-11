"""Dispatch offer endpoints for partners."""

from __future__ import annotations

import logging

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import NotFound
from apps.common.idempotency import IdempotentCommandMixin
from apps.common.permissions import IsPartner
from apps.dispatch.models import DispatchOffer
from apps.dispatch.services import offers as offer_service

logger = logging.getLogger("apps.dispatch.views")


def _profile(request):
    profile = getattr(request.user, "partner_profile", None)
    if profile is None:
        raise NotFound("This account has no partner profile.")
    return profile


def _offer_payload(offer: DispatchOffer) -> dict:
    """Offer projection.

    Includes the access notes, because the PDF requires access detail at offer time
    rather than after acceptance.
    """
    booking = offer.booking
    remaining = offer.seconds_remaining()
    return {
        "id": str(offer.pk),
        "booking_reference": booking.reference,
        "status": offer.status,
        "expires_at": offer.expires_at.isoformat(),
        "seconds_remaining": remaining,
        "dispatch_round": offer.dispatch_round,
        "rank": offer.rank,
        "payout_estimate_minor": offer.payout_estimate_minor,
        "currency": offer.currency,
        "eta_seconds": offer.eta_seconds,
        "eta_is_estimate": True,
        "distance_km": offer.distance_km,
        "service": {"code": booking.service.code, "name": booking.service.name},
        "vehicle": {
            "display_name": booking.vehicle.display_name,
            "make": booking.vehicle.make,
            "model": booking.vehicle.model,
            "color": booking.vehicle.color,
            "size_tier": booking.vehicle.size_tier,
        },
        "location": {
            "line1": booking.address.line1,
            "line2": booking.address.line2,
            "city": booking.address.city,
            "latitude": booking.address.latitude,
            "longitude": booking.address.longitude,
            "site_type": booking.address.site_type,
        },
        "access_notes": offer.access_notes_snapshot,
        "expected_duration_minutes": booking.expected_duration_minutes,
        "window_start": booking.window_start.isoformat() if booking.window_start else None,
        "is_actionable": offer.is_actionable,
    }


class OfferCollectionView(APIView):
    """The signed-in partner's live offer feed."""

    permission_classes = [IsPartner]

    def get(self, request):
        profile = _profile(request)
        include_expired = request.query_params.get("include_expired") == "true"
        offers = offer_service.offers_for_partner(
            partner=profile, include_expired=include_expired
        )
        return Response(
            {
                "results": [_offer_payload(offer) for offer in offers],
                "count": len(offers),
            }
        )


class OfferResponseView(IdempotentCommandMixin, APIView):
    """Accept or decline an offer.

    Acceptance takes an atomic booking lock: the first valid acceptance wins, and
    any sibling offer is superseded in the same transaction.
    """

    permission_classes = [IsPartner]
    idempotent_actions = {"post"}
    throttle_scope = "ops_write"

    def get(self, request, offer_id):
        profile = _profile(request)
        offer = offer_service.offer_for_actor(offer_id=offer_id, partner=profile)
        return Response(_offer_payload(offer))

    def post(self, request, offer_id):
        profile = _profile(request)
        action = str(request.data.get("action", "accept")).lower()

        if action == "accept":
            booking = offer_service.accept_offer(
                offer_id=offer_id, partner=profile, actor=request.user
            )
            _publish_promise(booking)
            _notify_customer_assigned(booking)
            booking.refresh_from_db()
            return Response(
                {
                    "offer_id": str(offer_id),
                    "booking": {
                        "reference": booking.reference,
                        "status": booking.status,
                        "promise_window_start": booking.promise_window_start.isoformat()
                        if booking.promise_window_start
                        else None,
                        "promise_window_end": booking.promise_window_end.isoformat()
                        if booking.promise_window_end
                        else None,
                        "booking_code": booking.booking_code,
                    },
                }
            )

        if action == "decline":
            offer = offer_service.decline_offer(
                offer_id=offer_id,
                partner=profile,
                reason_code=str(request.data.get("reason_code", "")),
                actor=request.user,
            )
            _widen_after_decline(booking=offer.booking)
            return Response({"offer_id": str(offer_id), "status": offer.status})

        from apps.common.exceptions import ValidationFailed

        raise ValidationFailed(
            "action must be 'accept' or 'decline'.", details={"field": "action"}
        )


def _publish_promise(booking) -> None:
    """Only now, after acceptance, is a firm arrival window allowed."""
    booking.refresh_from_db()
    if booking.promise_window_start is None:
        booking.set_promise_window()
        booking.save(
            update_fields=[
                "promise_window_start", "promise_window_end", "eta_seconds_at_assignment"
            ]
        )


def _notify_customer_assigned(booking) -> None:
    from apps.notifications.models import Notification

    Notification.objects.create(
        user=booking.customer,
        kind=Notification.Kind.ASSIGNMENT,
        title=f"{booking.reference}: partner assigned",
        body=(
            "A partner has been assigned to your wash. "
            "Your arrival window is now shown in the app."
        ),
        data={"booking_reference": booking.reference, "promise_window_start": booking.promise_window_start.isoformat() if booking.promise_window_start else None},
        booking=booking,
    )


def _widen_after_decline(*, booking) -> None:
    """A decline should trigger the next search round immediately."""
    from apps.dispatch.services import dispatcher

    booking.refresh_from_db()
    if booking.status == "dispatching":
        pending = DispatchOffer.objects.filter(
            booking=booking, status=DispatchOffer.Status.PENDING
        ).count()
        if pending == 0:
            dispatcher.dispatch_booking(booking=booking)


class PartnerJobView(APIView):
    """Everything the assigned partner needs to run the job."""

    permission_classes = [IsPartner]

    def get(self, request, reference):
        from apps.bookings.models import Booking
        from apps.bookings.serializers import (
            BookingChecklistSerializer,
            BookingDetailSerializer,
        )
        from apps.bookings.services import commands
        from apps.common.exceptions import PermissionDenied as Denied

        booking = (
            Booking.objects.select_related(
                "customer", "partner", "partner__user", "zone", "service",
                "vehicle", "address", "quote",
            )
            .filter(reference=reference)
            .first()
        )
        if booking is None:
            raise NotFound(f"No booking with reference {reference}.")

        profile = _profile(request)
        if booking.partner_id != profile.pk:
            # An offer recipient who did not accept has no job access.
            raise Denied("You are not the assigned partner for this job.")

        from apps.bookings.domain import state_machine as sm
        from apps.evidence.serializers import EvidenceSerializer

        required = {
            "start": ["pre_condition"],
            "complete": ["post_service"],
        }

        return Response(
            {
                "booking": BookingDetailSerializer(booking, context={"request": request}).data,
                "checklist": BookingChecklistSerializer(booking.checklist_items.all(), many=True).data,
                "evidence": EvidenceSerializer(booking.evidence.all(), many=True).data,
                "required_evidence": required,
                "allowed_transitions": sm.allowed_transitions_for(
                    booking.status, commands.role_for(request.user)
                ),
                "navigation": {
                    "latitude": booking.address.latitude,
                    "longitude": booking.address.longitude,
                    "address_lines": booking.address.summary,
                },
                "customer_contact": {
                    "masked_phone": booking.customer.mask_phone(),
                    "note": "Calls are relayed and masked while the job is active.",
                },
            }
        )
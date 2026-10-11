"""Domain exceptions and the single API error envelope.

Every failure the API returns has the same shape::

    {"error": {"code": "...", "message": "...", "details": {...}, "request_id": "..."}}

The mobile client therefore has exactly one error contract to normalise against.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import APIException, NotAuthenticated
from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response


class DomainError(Exception):
    """Base class for expected business failures.

    Subclasses set ``code``, ``status_code`` and optionally ``details``. Raising one
    of these is the normal way a service rejects invalid business input; views do
    not need to translate errors themselves.
    """

    code: str = "domain_error"
    status_code: int = status.HTTP_400_BAD_REQUEST
    default_message: str = "The request could not be processed."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        code: str | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details = details or {}
        if code:
            self.code = code
        super().__init__(self.message)


# --------------------------------------------------------------- authentication


class Unauthenticated(DomainError):
    code = "unauthenticated"
    status_code = status.HTTP_401_UNAUTHORIZED
    default_message = "Authentication credentials were not provided or are invalid."


class InvalidToken(Unauthenticated):
    code = "invalid_token"
    default_message = "The access token is invalid or has expired."


class PermissionDenied(DomainError):
    code = "permission_denied"
    status_code = status.HTTP_403_FORBIDDEN
    default_message = "You do not have permission to perform this action."


class NotFound(DomainError):
    code = "not_found"
    status_code = status.HTTP_404_NOT_FOUND
    default_message = "The requested resource does not exist."


class Gone(DomainError):
    code = "gone"
    status_code = status.HTTP_410_GONE
    default_message = "The requested resource is no longer available."


# ------------------------------------------------------------------- validation


class ValidationFailed(DomainError):
    code = "validation_error"
    status_code = status.HTTP_400_BAD_REQUEST
    default_message = "The request contains invalid data."


class Conflict(DomainError):
    code = "conflict"
    status_code = status.HTTP_409_CONFLICT
    default_message = "The request conflicts with the current state of the resource."


class Unprocessable(DomainError):
    code = "unprocessable"
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_message = "The request is well formed but cannot be processed."


class RateLimited(DomainError):
    code = "rate_limited"
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_message = "Too many requests. Please slow down and try again shortly."


# ------------------------------------------------------- stable business codes


class InvalidStateTransition(Conflict):
    code = "invalid_state_transition"
    default_message = "That action is not allowed from the current state."


class QuoteExpired(Gone):
    code = "quote_expired"
    default_message = "This quote has expired. Please request a new quote."


class QuoteNotAccepted(Conflict):
    code = "quote_not_accepted"
    default_message = "The quote must be accepted before a booking can be created."


class OfferExpired(Gone):
    code = "offer_expired"
    default_message = "This offer has expired and is no longer available."


class OfferAlreadyResponded(Conflict):
    code = "offer_already_responded"
    default_message = "You have already responded to this offer."


class BookingAlreadyAssigned(Conflict):
    code = "booking_already_assigned"
    default_message = "Another partner has already accepted this job."


class LocationContextInactive(PermissionDenied):
    code = "location_context_inactive"
    default_message = (
        "Location is only shared while you are on shift or serving an active job."
    )


class LocationUpdateStale(Conflict):
    code = "location_update_stale"
    default_message = "This location update is older than the last accepted update."


class SiteMethodNotPermitted(Unprocessable):
    code = "site_method_not_permitted"
    default_message = "The selected service is not permitted at this site type."


class ZoneInactive(Unprocessable):
    code = "zone_inactive"
    default_message = "This service zone is not currently bookable."


class ZoneCapacityReached(Unprocessable):
    code = "zone_capacity_reached"
    default_message = "No capacity remains in this zone for the requested window."


class OnDemandNotAvailable(Unprocessable):
    code = "on_demand_not_available"
    default_message = "On-demand service is not available for this zone or time."


class PartnerNotEligible(Unprocessable):
    code = "partner_not_eligible"
    default_message = "This partner is not currently eligible to receive offers."


class EvidenceIncomplete(Conflict):
    code = "evidence_incomplete"
    default_message = "Required photo evidence has not been provided."


class ChecklistIncomplete(Conflict):
    code = "checklist_incomplete"
    default_message = "The service checklist has not been completed."


class PaymentAuthorizationFailed(Unprocessable):
    code = "payment_authorization_failed"
    default_message = "The payment could not be authorised."


class AlreadyCaptured(Conflict):
    code = "already_captured"
    default_message = "This payment has already been captured."


class RefundExceedsCaptured(Unprocessable):
    code = "refund_exceeds_captured"
    default_message = "The refund exceeds the amount captured for this booking."


class RefundApprovalLimitExceeded(PermissionDenied):
    code = "refund_approval_limit_exceeded"
    default_message = "This refund exceeds your approval limit."


class PayoutAlreadyProcessed(Conflict):
    code = "payout_already_processed"
    default_message = "This payout batch has already been processed."


class OverrideReasonRequired(ValidationFailed):
    code = "override_reason_required"
    default_message = "A reason is required and will be recorded in the audit history."


class IdempotencyKeyReuseMismatch(Conflict):
    code = "idempotency_key_reuse_mismatch"
    default_message = (
        "This idempotency key was already used with a different request body."
    )


class IdempotencyKeyRequired(ValidationFailed):
    code = "idempotency_key_required"
    default_message = "This action requires an Idempotency-Key header."


class WebhookSignatureInvalid(PermissionDenied):
    code = "webhook_signature_invalid"
    default_message = "The webhook signature could not be verified."


class CommsWindowClosed(PermissionDenied):
    code = "comms_window_closed"
    default_message = "Messaging is available only around an active booking."


class ImmutableRecordError(DomainError):
    code = "immutable_record"
    status_code = status.HTTP_409_CONFLICT
    default_message = "This record is append-only and cannot be changed."


# ------------------------------------------------------------------- envelope


def error_payload(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id,
        }
    }


def _flatten_drf_details(data: Any) -> dict[str, Any]:
    """Normalise DRF's nested error structures into a flat details mapping."""
    if isinstance(data, dict):
        return {key: _flatten_drf_details(value) for key, value in data.items()}
    if isinstance(data, list):
        return {"errors": [str(item) for item in data]}
    return {"error": str(data)}


def _translate_payment_error(exc: Exception, request_id: str | None) -> Response | None:
    """Map a payment provider error onto the API envelope.

    Imported lazily: the payments app imports this module, so a module-level import
    would be circular. Provider failures are customer-correctable, so they become 4xx
    rather than 500 - including "raw card data rejected", which is a client bug we
    must report clearly.
    """
    try:
        from apps.payments.ports.gateway import PaymentDeclined, PaymentError
    except Exception:  # pragma: no cover - payments app not loaded
        return None

    if not isinstance(exc, PaymentError):
        return None

    status_code = (
        status.HTTP_402_PAYMENT_REQUIRED
        if isinstance(exc, PaymentDeclined)
        else status.HTTP_422_UNPROCESSABLE_ENTITY
    )
    return Response(
        error_payload(
            exc.code,
            exc.message,
            {"retryable": exc.retryable},
            request_id,
        ),
        status=status_code,
    )


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Project-wide DRF exception handler producing one error envelope."""
    request = context.get("request")
    request_id = getattr(request, "request_id", None) if request else None

    if isinstance(exc, DomainError):
        return Response(
            error_payload(exc.code, exc.message, exc.details, request_id),
            status=exc.status_code,
        )

    # Provider errors must not surface as a 500. A decline or a bad token is a
    # customer-correctable problem, not an internal fault.
    translated = _translate_payment_error(exc, request_id)
    if translated is not None:
        return translated

    # Translate Django/DRF built-ins into the same envelope.
    if isinstance(exc, NotAuthenticated):
        return Response(
            error_payload("unauthenticated", str(exc) or "Authentication required.", {}, request_id),
            status=status.HTTP_401_UNAUTHORIZED,
        )
    if isinstance(exc, (DRFPermissionDenied, DjangoPermissionDenied)):
        return Response(
            error_payload("permission_denied", str(exc) or "Permission denied.", {}, request_id),
            status=status.HTTP_403_FORBIDDEN,
        )
    if isinstance(exc, Http404):
        return Response(
            error_payload("not_found", str(exc) or "Not found.", {}, request_id),
            status=status.HTTP_404_NOT_FOUND,
        )
    if isinstance(exc, (DRFValidationError, DjangoValidationError)):
        return Response(
            error_payload(
                "validation_error",
                "The request contains invalid data.",
                _flatten_drf_details(getattr(exc, "detail", exc)),
                request_id,
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )
    if isinstance(exc, APIException):
        return Response(
            error_payload(
                getattr(exc, "default_code", "api_error"),
                str(getattr(exc, "detail", "Request failed.")),
                {},
                request_id,
            ),
            status=exc.status_code,
        )

    # Imported lazily: DRF resolves DEFAULT_AUTHENTICATION_CLASSES while
    # rest_framework.views is still initialising, so a module-level import here
    # would be circular.
    from rest_framework.views import exception_handler as drf_exception_handler

    response = drf_exception_handler(exc, context)
    if response is not None:
        response.data = error_payload(
            getattr(exc, "default_code", "api_error"),
            str(getattr(exc, "detail", "Request failed.")),
            _flatten_drf_details(response.data),
            request_id,
        )
        return response
    return None
"""Booking lifecycle: the declarative state machine.

The PDF is unambiguous about this: *"Use a booking state machine enforced
server-side; a client must not be able to jump from assigned to paid or alter price
after acceptance."* Everything about lifecycle safety lives here:

* :data:`TRANSITIONS` is the single source of truth for what may follow what
* every transition names the roles allowed to perform it and its guards
* :func:`apply` is the only supported way to change a booking's status
* each accepted transition appends an immutable event

The happy path, with the PDF's explicit branches::

    requested -> quote_accepted -> dispatching -> assigned -> en_route
              -> arrived -> in_service -> completed -> payment_captured
              -> partner_payout_eligible

    branches: expired_offer, no_partner_available, customer_cancellation,
              partner_no_show, unsafe_site, payment_failed, disputed_work,
              refund, reassignment
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from apps.common.enums import ActorType


class BookingStatus:
    REQUESTED = "requested"
    QUOTE_ACCEPTED = "quote_accepted"
    DISPATCHING = "dispatching"
    ASSIGNED = "assigned"
    EN_ROUTE = "en_route"
    ARRIVED = "arrived"
    IN_SERVICE = "in_service"
    COMPLETED = "completed"
    PAYMENT_CAPTURED = "payment_captured"
    PARTNER_PAYOUT_ELIGIBLE = "partner_payout_eligible"

    # Exception / terminal branches
    EXPIRED_OFFER = "expired_offer"
    NO_PARTNER_AVAILABLE = "no_partner_available"
    CANCELLED = "cancelled"
    PARTNER_NO_SHOW = "partner_no_show"
    UNSAFE_SITE = "unsafe_site"
    PAYMENT_FAILED = "payment_failed"
    DISPUTED_WORK = "disputed_work"
    REFUNDED = "refunded"


TERMINAL_STATUSES = frozenset(
    {
        BookingStatus.CANCELLED,
        BookingStatus.PARTNER_NO_SHOW,
        BookingStatus.PAYMENT_FAILED,
        BookingStatus.REFUNDED,
        BookingStatus.EXPIRED_OFFER,
        BookingStatus.NO_PARTNER_AVAILABLE,
        BookingStatus.UNSAFE_SITE,
    }
)

#: Statuses that still occupy a customer-visible booking and partner capacity.
ACTIVE_STATUSES = (
    BookingStatus.REQUESTED,
    BookingStatus.QUOTE_ACCEPTED,
    BookingStatus.DISPATCHING,
    BookingStatus.ASSIGNED,
    BookingStatus.EN_ROUTE,
    BookingStatus.ARRIVED,
    BookingStatus.IN_SERVICE,
    BookingStatus.COMPLETED,
    BookingStatus.PAYMENT_CAPTURED,
    BookingStatus.PARTNER_PAYOUT_ELIGIBLE,
    BookingStatus.DISPUTED_WORK,
)

#: Statuses in which a partner is actively responsible for the job.
PARTNER_ACTIVE_STATUSES = (
    BookingStatus.ASSIGNED,
    BookingStatus.EN_ROUTE,
    BookingStatus.ARRIVED,
    BookingStatus.IN_SERVICE,
)

#: Statuses after which the job is finished work, for fulfilment metrics.
COMPLETED_STATUSES = (
    BookingStatus.COMPLETED,
    BookingStatus.PAYMENT_CAPTURED,
    BookingStatus.PARTNER_PAYOUT_ELIGIBLE,
)

CUSTOMER = "customer"
PARTNER = "partner"
OPS = "ops"
SYSTEM = "system"


@dataclass(frozen=True)
class Transition:
    """One permitted change of state."""

    action: str
    to_status: str
    roles: tuple[str, ...]
    #: Named guards evaluated by the caller; a falsey guard rejects the transition.
    guards: tuple[str, ...] = ()
    description: str = ""
    #: Whether this transition needs an explicit reason recorded in the audit log.
    requires_reason: bool = False


def _t(action, to_status, roles, *, guards=(), description="", requires_reason=False):
    return Transition(action, to_status, roles, tuple(guards), description, requires_reason)


#: ``from_status -> (Transition, ...)``. This table is the whole state machine.
TRANSITIONS: dict[str, tuple[Transition, ...]] = {
    BookingStatus.REQUESTED: (
        _t(
            "accept_quote",
            BookingStatus.QUOTE_ACCEPTED,
            (SYSTEM, CUSTOMER),
            guards=("quote_accepted",),
            description="Customer accepts the quote and authorises payment.",
        ),
        _t(
            "cancel",
            BookingStatus.CANCELLED,
            (CUSTOMER, OPS, SYSTEM),
            requires_reason=True,
            description="Customer or operations cancels before dispatch.",
        ),
    ),
    BookingStatus.QUOTE_ACCEPTED: (
        _t(
            "start_dispatch",
            BookingStatus.DISPATCHING,
            (SYSTEM, OPS),
            guards=("payment_authorized",),
            description="Payment authorised; the job enters the dispatch pool.",
        ),
        _t(
            "cancel",
            BookingStatus.CANCELLED,
            (CUSTOMER, OPS, SYSTEM),
            requires_reason=True,
            description="Cancellation after payment authorisation triggers a void or refund.",
        ),
        _t(
            "payment_failed",
            BookingStatus.PAYMENT_FAILED,
            (SYSTEM, OPS),
            description="Authorisation failed or was declined.",
        ),
    ),
    BookingStatus.DISPATCHING: (
        _t(
            "accept_offer",
            BookingStatus.ASSIGNED,
            (PARTNER, OPS),
            guards=("offer_valid", "partner_eligible"),
            description="A partner accepted a time-limited offer and took the booking lock.",
        ),
        _t(
            "cancel",
            BookingStatus.CANCELLED,
            (CUSTOMER, OPS, SYSTEM),
            requires_reason=True,
            description="Cancelled while searching for a partner.",
        ),
        _t(
            "expire_offers",
            BookingStatus.EXPIRED_OFFER,
            (SYSTEM, OPS),
            description="Offer rounds exhausted without an acceptance.",
        ),
        _t(
            "no_partner_available",
            BookingStatus.NO_PARTNER_AVAILABLE,
            (SYSTEM, OPS),
            description="No eligible partner exists; operations must intervene.",
        ),
    ),
    BookingStatus.ASSIGNED: (
        _t(
            "start_travel",
            BookingStatus.EN_ROUTE,
            (PARTNER, OPS),
            description="Partner is travelling to the site.",
        ),
        _t(
            "reassign",
            BookingStatus.DISPATCHING,
            (SYSTEM, OPS),
            guards=("reason_recorded",),
            requires_reason=True,
            description="Operations moved the job to another partner. Must not duplicate work or capture.",
        ),
        _t(
            "mark_partner_no_show",
            BookingStatus.PARTNER_NO_SHOW,
            (SYSTEM, OPS),
            requires_reason=True,
            description="Partner did not arrive inside the promise window.",
        ),
        _t(
            "report_unsafe_site",
            BookingStatus.UNSAFE_SITE,
            (PARTNER, CUSTOMER, OPS),
            requires_reason=True,
            description="Site cannot be served safely; the wash is blocked here.",
        ),
        _t(
            "cancel",
            BookingStatus.CANCELLED,
            (CUSTOMER, OPS, SYSTEM),
            requires_reason=True,
            description="Cancellation after assignment.",
        ),
    ),
    BookingStatus.EN_ROUTE: (
        _t("arrive", BookingStatus.ARRIVED, (PARTNER, OPS), guards=("booking_code_ok",)),
        _t(
            "reassign",
            BookingStatus.DISPATCHING,
            (SYSTEM, OPS),
            guards=("reason_recorded",),
            requires_reason=True,
            description="Late or unresponsive partner; reassigned with a recorded reason.",
        ),
        _t(
            "mark_partner_no_show",
            BookingStatus.PARTNER_NO_SHOW,
            (SYSTEM, OPS),
            requires_reason=True,
            description="Partner never arrived.",
        ),
        _t(
            "report_unsafe_site",
            BookingStatus.UNSAFE_SITE,
            (PARTNER, CUSTOMER, OPS),
            requires_reason=True,
            description="Conditions on arrival make the wash unsafe.",
        ),
    ),
    BookingStatus.ARRIVED: (
        _t(
            "start_service",
            BookingStatus.IN_SERVICE,
            (PARTNER, OPS),
            guards=("pre_evidence_present",),
            description="Work begins. Pre-service condition evidence is mandatory first.",
        ),
        _t(
            "report_unsafe_site",
            BookingStatus.UNSAFE_SITE,
            (PARTNER, CUSTOMER, OPS),
            requires_reason=True,
            description="Site blocked at arrival.",
        ),
        _t("cancel", BookingStatus.CANCELLED, (CUSTOMER, OPS, SYSTEM), requires_reason=True),
    ),
    BookingStatus.IN_SERVICE: (
        _t(
            "complete",
            BookingStatus.COMPLETED,
            (PARTNER, OPS),
            guards=("post_evidence_present", "checklist_complete"),
            description="Work finished with after-evidence and a completed checklist.",
        ),
        _t(
            "report_unsafe_site",
            BookingStatus.UNSAFE_SITE,
            (PARTNER, CUSTOMER, OPS),
            requires_reason=True,
            description="Conditions made the wash unsafe mid-job.",
        ),
    ),
    BookingStatus.COMPLETED: (
        _t(
            "capture_payment",
            BookingStatus.PAYMENT_CAPTURED,
            (SYSTEM, OPS),
            guards=("payment_capturable",),
            description="Payment captured at completion.",
        ),
        _t(
            "open_dispute",
            BookingStatus.DISPUTED_WORK,
            (CUSTOMER, OPS),
            requires_reason=True,
            description="Customer reports damage or unsatisfactory work.",
        ),
        _t("cancel", BookingStatus.CANCELLED, (OPS, SYSTEM), requires_reason=True),
    ),
    BookingStatus.PAYMENT_CAPTURED: (
        _t(
            "mark_payout_eligible",
            BookingStatus.PARTNER_PAYOUT_ELIGIBLE,
            (SYSTEM, OPS),
            guards=("payable_created",),
            description="Partner payable created and queued for the next payout batch.",
        ),
        _t(
            "open_dispute",
            BookingStatus.DISPUTED_WORK,
            (CUSTOMER, OPS),
            requires_reason=True,
            description="Dispute raised after capture; may lead to a partial refund.",
        ),
    ),
    BookingStatus.PARTNER_PAYOUT_ELIGIBLE: (
        _t(
            "open_dispute",
            BookingStatus.DISPUTED_WORK,
            (CUSTOMER, OPS),
            requires_reason=True,
            description="Late dispute; funds may be held pending resolution.",
        ),
    ),
    BookingStatus.DISPUTED_WORK: (
        _t(
            "refund",
            BookingStatus.REFUNDED,
            (OPS, SYSTEM),
            guards=("refund_approved", "reason_recorded"),
            requires_reason=True,
            description="Human-led dispute resolved with a refund.",
        ),
        _t(
            "resolve_dispute",
            BookingStatus.COMPLETED,
            (OPS, SYSTEM),
            guards=("reason_recorded",),
            requires_reason=True,
            description="Dispute closed with no refund, returning the booking to completed.",
        ),
    ),
    # Terminal states have no outgoing transitions by design.
    BookingStatus.CANCELLED: (),
    BookingStatus.PARTNER_NO_SHOW: (),
    BookingStatus.PAYMENT_FAILED: (),
    BookingStatus.REFUNDED: (),
    BookingStatus.EXPIRED_OFFER: (),
    BookingStatus.NO_PARTNER_AVAILABLE: (),
    BookingStatus.UNSAFE_SITE: (),
}

#: Actions that may be attempted regardless of the current state, for the customer
#: reporting flow. These do not change the lifecycle state.
REPORT_ACTIONS = frozenset({"report_unsafe_site"})


class InvalidAction(Exception):
    """Raised when an action is not permitted from the current state."""

    def __init__(self, message: str, *, code: str = "invalid_state_transition", details=None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(message)


def find_transition(current_status: str, action: str) -> Transition | None:
    for transition in TRANSITIONS.get(current_status, ()):
        if transition.action == action:
            return transition
    return None


def allowed_actions(current_status: str, role: str) -> list[str]:
    return sorted(
        transition.action
        for transition in TRANSITIONS.get(current_status, ())
        if role in transition.roles
    )


def allowed_transitions_for(current_status: str, role: str) -> list[dict]:
    """Machine-readable transition list, so the app can show only valid actions."""
    return [
        {
            "action": transition.action,
            "to_status": transition.to_status,
            "description": transition.description,
            "requires_reason": transition.requires_reason,
            "guards": list(transition.guards),
        }
        for transition in TRANSITIONS.get(current_status, ())
        if role in transition.roles
    ]


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATUSES


@dataclass
class TransitionResult:
    from_status: str
    to_status: str
    action: str
    actor_type: str


@dataclass
class GuardContext:
    """Facts the guards need, supplied by the booking service."""

    booking: object
    actor: object
    reason: str = ""
    payload: dict = field(default_factory=dict)
    facts: dict = field(default_factory=dict)

    def get(self, name: str, default=None):
        return self.facts.get(name, default)


#: Named guard implementations. A guard returns ``(ok, reason_detail)``.
GUARDS: dict[str, Callable[[GuardContext], tuple[bool, dict]]] = {}


def guard(name: str):
    """Register a guard under a name used by the transition table."""

    def decorator(func: Callable[[GuardContext], tuple[bool, dict]]):
        GUARDS[name] = func
        return func

    return decorator


def evaluate_guards(transition: Transition, context: GuardContext) -> None:
    """Raise :class:`InvalidAction` if any guard fails."""
    for guard_name in transition.guards:
        implementation = GUARDS.get(guard_name)
        if implementation is None:
            raise InvalidAction(
                f"Guard {guard_name!r} is not implemented.",
                code="guard_not_implemented",
                details={"guard": guard_name},
            )
        ok, details = implementation(context)
        if not ok:
            raise InvalidAction(
                f"This action is not currently allowed: {guard_name}",
                code=_guard_error_code(guard_name),
                details={**details, "guard": guard_name, "action": transition.action},
            )


def _guard_error_code(guard_name: str) -> str:
    return {
        "quote_accepted": "quote_not_accepted",
        "payment_authorized": "payment_not_authorized",
        "offer_valid": "offer_expired",
        "partner_eligible": "partner_not_eligible",
        "reason_recorded": "override_reason_required",
        "booking_code_ok": "invalid_booking_code",
        "pre_evidence_present": "evidence_incomplete",
        "post_evidence_present": "evidence_incomplete",
        "checklist_complete": "checklist_incomplete",
        "payment_capturable": "payment_authorization_failed",
        "payable_created": "payable_not_created",
        "refund_approved": "refund_not_approved",
    }.get(guard_name, "invalid_state_transition")


ACTOR_ROLE_TO_TYPE = {
    CUSTOMER: ActorType.CUSTOMER,
    PARTNER: ActorType.PARTNER,
    OPS: ActorType.ADMIN,
    SYSTEM: ActorType.SYSTEM,
}
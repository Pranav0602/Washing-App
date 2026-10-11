"""Shared DRF permission classes.

Roles are plain strings resolved from ``RoleGrant`` rows (see ``apps.identity``).
Permission classes read roles off the authenticated user; they never trust a role
supplied by the client.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission

ROLE_CUSTOMER = "customer"
ROLE_PARTNER = "partner"
ROLE_OPS = "ops"
ROLE_ADMIN = "admin"

STAFF_ROLES = frozenset({ROLE_OPS, ROLE_ADMIN})


class _RolePermission(BasePermission):
    required_roles: frozenset[str] = frozenset()
    message = "You do not have permission to perform this action."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        if not getattr(user, "is_active", False):
            return False
        return bool(self.required_roles & set(user.roles()))


class IsAuthenticatedActor(BasePermission):
    """Default permission: any active, authenticated account.

    Staff accounts must additionally clear the MFA gate, so an operations endpoint
    cannot be reached with a password-only token.
    """

    message = "Authentication required."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        if not getattr(user, "is_active", False):
            return False
        if user.is_staff_account and not request.auth.get("mfa_verified", False):
            self.message = "Multi-factor verification is required for staff access."
            return False
        return True


class IsCustomer(_RolePermission):
    required_roles = frozenset({ROLE_CUSTOMER})
    message = "This action is only available to customer accounts."


class IsPartner(_RolePermission):
    required_roles = frozenset({ROLE_PARTNER})
    message = "This action is only available to partner accounts."


class IsOps(_RolePermission):
    required_roles = frozenset({ROLE_OPS, ROLE_ADMIN})
    message = "This action is only available to operations staff."


class IsAdmin(_RolePermission):
    required_roles = frozenset({ROLE_ADMIN})
    message = "This action requires an administrator."


class ReadOnly(BasePermission):
    def has_permission(self, request, view) -> bool:
        return request.method in ("GET", "HEAD", "OPTIONS")


class IsBookingParty(BasePermission):
    """Object-level access to a booking.

    Allowed for the owning customer, the assigned partner, and operations staff.
    Critically, a partner who merely *received* an offer but did not accept it has
    no access - that is what stops two partners acting on the same job.
    """

    message = "You are not a party to this booking."

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        if not getattr(user, "is_active", False):
            return False
        roles = set(user.roles())
        if roles & STAFF_ROLES:
            return True
        if ROLE_CUSTOMER in roles and obj.customer_id == user.pk:
            return True
        if ROLE_PARTNER in roles and obj.partner_id is not None:
            return getattr(user, "partner_profile", None) and (
                obj.partner_id == user.partner_profile.pk
            )
        return False


class IsDispatchOfferRecipient(BasePermission):
    """A partner may only read or respond to offers addressed to them."""

    message = "This offer was not sent to you."

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        profile = getattr(user, "partner_profile", None)
        return profile is not None and obj.partner_id == profile.pk


class IsOwnObject(BasePermission):
    """Generic owner check for endpoints carrying an ``owner_field``."""

    owner_field = "customer"
    message = "You may only access your own records."

    def has_object_permission(self, request, view, obj) -> bool:
        if set(request.user.roles()) & STAFF_ROLES:
            return True
        owner = getattr(obj, f"{self.owner_field}_id", None)
        return owner == request.user.pk
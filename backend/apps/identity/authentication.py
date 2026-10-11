"""JWT authentication for DRF."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import authentication, exceptions

from apps.identity.services.tokens import decode_access_token

AUTH_HEADER = "HTTP_AUTHORIZATION"
PREFIX = "bearer "


class JWTAuthentication(authentication.BaseAuthentication):
    """Stateless bearer-token authentication.

    The user is loaded from the database on every request rather than trusted from
    the token body, so a revoked account, a suspended partner or a newly revoked role
    takes effect immediately.
    """

    keyword = "Bearer"

    def authenticate(self, request):
        header = request.META.get(AUTH_HEADER, "")
        if not header:
            return None
        if not header.lower().startswith(PREFIX):
            # Let other schemes (e.g. webhook signatures) handle it.
            return None

        token = header[len(PREFIX) :].strip()
        if not token:
            return None

        payload = decode_access_token(token)

        user_model = get_user_model()
        try:
            user = user_model.objects.get(pk=payload["sub"])
        except (user_model.DoesNotExist, ValueError, KeyError) as exc:
            raise exceptions.AuthenticationFailed("Account no longer exists.") from exc

        if not user.is_active or user.status != user_model.Status.ACTIVE:
            raise exceptions.AuthenticationFailed("This account is not active.")

        # Carry the MFA decision so IsAuthenticatedActor can gate staff endpoints.
        request.auth = payload
        return (user, payload)

    def authenticate_header(self, request) -> str:
        return self.keyword
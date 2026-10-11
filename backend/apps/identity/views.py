"""Authentication and account endpoints."""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import PermissionDenied, Unauthenticated, ValidationFailed
from apps.identity import services
from apps.identity.models import (
    Device,
    NotificationPreference,
    OtpChallenge,
    StaffMfaChallenge,
    User,
)
from apps.identity.serializers import (
    ConsentSerializer,
    DeviceSerializer,
    LogoutSerializer,
    NotificationPreferenceSerializer,
    OtpRequestSerializer,
    OtpResendSerializer,
    OtpVerifySerializer,
    ProfileUpdateSerializer,
    RefreshSerializer,
    RoleGrantSerializer,
    StaffMfaSerializer,
    UserSerializer,
)
from apps.identity.services import otp as otp_service
from apps.identity.services import tokens as token_service
from apps.identity.services.consents import record_consents

logger = logging.getLogger("apps.identity.views")


class OTPDelivery:
    """Default OTP delivery channel.

    The real platform must plug in an SMS provider here. Until a provider is
    selected, the code is logged at WARNING level outside production so the flow is
    testable end to end without sending messages.
    """

    def __call__(self, phone: str, code: str) -> None:
        if settings.DEBUG:
            logger.warning("DEV OTP phone=%s code=%s", phone, code)
        else:
            logger.info("OTP dispatched phone=%s (code withheld from logs)", phone)


def _token_response(pair: token_service.TokenPair, user: User) -> dict[str, Any]:
    return {
        "access_token": pair.access_token,
        "refresh_token": pair.refresh_token,
        "token_type": "Bearer",
        "expires_in": pair.access_ttl_seconds,
        "access_expires_at": pair.access_expires_at.isoformat(),
        "refresh_expires_at": pair.refresh_expires_at.isoformat(),
        "user": UserSerializer(user).data,
    }


def _has_partner_profile(user: User) -> bool:
    """Whether a partner application already exists for this account.

    The profile is the real record of a submitted application; ``account_complete``
    is the flag the registration service sets alongside it. An account holding a
    profile without the flag is registered as far as the app is concerned.
    """
    from apps.partners.models import PartnerProfile

    return PartnerProfile.objects.filter(user=user).exists()


def _next_step(user: User) -> str:
    """Tell the app which screen to show after a successful login."""
    roles = set(user.roles())
    if not user.account_complete and not _has_partner_profile(user):
        from apps.identity.models import ROLE_CUSTOMER, ROLE_PARTNER

        if ROLE_PARTNER in roles and ROLE_CUSTOMER not in roles:
            return "register_partner"
        return "register_customer"
    if {"ops", "admin"} & roles:
        return "ops_home"
    if "partner" in roles or _has_partner_profile(user):
        return "partner_home"
    return "customer_home"


class OTPRequestView(APIView):
    """Step 1 of login: request a one-time code."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_scope = "otp_request"

    def post(self, request):
        serializer = OtpRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        issued = services.issue_otp_challenge(
            raw_phone=serializer.validated_data["phone"],
            purpose=serializer.validated_data["purpose"],
            request=request,
        )
        return Response(
            {
                "challenge_id": str(issued.challenge.pk),
                **otp_service.cooldown_state(issued.challenge),
            },
            status=status.HTTP_202_ACCEPTED,
        )


class OTPVerifyView(APIView):
    """Step 2 of login: exchange a code for tokens."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_scope = "otp_verify"

    def post(self, request):
        serializer = OtpVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        challenge, phone = otp_service.verify_challenge(
            challenge_id=serializer.validated_data["challenge_id"],
            code=serializer.validated_data["code"],
            request=request,
        )

        user, _created = otp_service.get_or_create_user_for_phone(phone)
        user.touch_login()
        pair = token_service.issue_token_pair(user, request=request)
        payload = _token_response(pair, user)
        payload["next"] = _next_step(user)
        return Response(payload)


class OTPResendView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_scope = "otp_request"

    def post(self, request):
        serializer = OtpResendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        challenge = get_object_or_404(OtpChallenge, pk=serializer.validated_data["challenge_id"])

        issued = services.issue_otp_challenge(
            raw_phone=challenge.phone,
            purpose=challenge.purpose,
            request=request,
        )
        return Response(
            {
                "challenge_id": str(issued.challenge.pk),
                **otp_service.cooldown_state(issued.challenge),
            },
            status=status.HTTP_202_ACCEPTED,
        )


class RefreshView(APIView):
    """Rotate a refresh token. Replay revokes the whole token family."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pair = token_service.rotate_refresh_token(
            serializer.validated_data["refresh_token"], request=request
        )
        payload = _token_response(pair, pair.user)
        payload["next"] = _next_step(pair.user)
        return Response(payload)


class LogoutView(APIView):
    permission_classes: list = []

    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data.get("refresh_token")
        if token:
            token_service.revoke_refresh_token(token)
        return Response(status=status.HTTP_204_NO_CONTENT)


class StaffLoginView(APIView):
    """Staff sign-in: password first, then a mandatory MFA challenge."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        phone = str(request.data.get("phone", ""))
        password = str(request.data.get("password", ""))
        if not phone or not password:
            raise ValidationFailed("Phone and password are required.", details={"field": "phone"})

        try:
            from apps.identity.models import normalise_phone

            user = User.objects.get(phone=normalise_phone(phone))
        except (User.DoesNotExist, ValueError):
            raise Unauthenticated("Invalid credentials.") from None

        if not user.check_password(password) or not user.is_staff:
            logger.warning("staff_login_failed phone=%s", phone)
            raise Unauthenticated("Invalid credentials.")

        challenge, code = StaffMfaChallenge.issue(user)
        logger.warning("DEV staff MFA phone=%s code=%s", phone, code)
        return Response(
            {
                "challenge_id": str(challenge.pk),
                "expires_in_seconds": challenge.ttl_seconds,
                "mfa_required": True,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class StaffMfaVerifyView(APIView):
    """Exchange a satisfied MFA challenge for staff tokens."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        serializer = StaffMfaSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        challenge_id = request.data.get("challenge_id")
        if not challenge_id:
            raise ValidationFailed("challenge_id is required.", details={"field": "challenge_id"})

        challenge = StaffMfaChallenge.consume(
            challenge_id, serializer.validated_data["code"]
        )
        user = challenge.user
        user.touch_login()
        pair = token_service.issue_token_pair(user, request=request, mfa_verified=True)
        payload = _token_response(pair, user)
        payload["next"] = "ops_home"
        return Response(payload)


# ------------------------------------------------------------------ registration


class RegisterCustomerView(APIView):
    """Complete a customer account after phone verification.

    Requires a bearer token from a verified OTP login. The phone cannot be changed
    here, and no role can be requested: ``customer`` is granted by the service.
    """

    def post(self, request):
        from apps.identity.registration_serializers import (
            CustomerRegistrationSerializer,
            consent_map,
        )
        from apps.identity.services import registration

        otp_service.assert_verified_phone(request.user)

        serializer = CustomerRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        payload["consent"] = consent_map(payload)

        result = registration.register_customer(user=request.user, payload=payload, request=request)
        return Response(
            registration.complete_customer_registration(result),
            status=status.HTTP_201_CREATED,
        )


class RegisterPartnerView(APIView):
    """Submit a partner application. Approval is a separate, audited ops action."""

    def post(self, request):
        from apps.identity.registration_serializers import (
            PartnerRegistrationSerializer,
            consent_map,
        )
        from apps.identity.services import registration

        otp_service.assert_verified_phone(request.user)

        serializer = PartnerRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        payload["consent"] = consent_map(payload)

        result = registration.register_partner(user=request.user, payload=payload, request=request)
        return Response(
            registration.complete_partner_registration(result),
            status=status.HTTP_201_CREATED,
        )


# ------------------------------------------------------------------ account


class MeView(APIView):
    """Read and update the authenticated account."""

    def get(self, request):
        serializer = UserSerializer(request.user)
        data = dict(serializer.data)
        data["roles_detail"] = RoleGrantSerializer(
            request.user.role_grants.all(), many=True
        ).data
        data["notification_preferences"] = NotificationPreferenceSerializer(
            _preferences_for(request.user)
        ).data
        return Response(data)

    def patch(self, request):
        serializer = ProfileUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserSerializer(user).data)


def _preferences_for(user: User) -> NotificationPreference:
    prefs, _ = NotificationPreference.objects.get_or_create(user=user)
    return prefs


class MePreferencesView(APIView):
    def get(self, request):
        return Response(NotificationPreferenceSerializer(_preferences_for(request.user)).data)

    def patch(self, request):
        prefs = _preferences_for(request.user)
        serializer = NotificationPreferenceSerializer(prefs, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return Response(NotificationPreferenceSerializer(serializer.save()).data)


class MeConsentsView(APIView):
    def get(self, request):
        records = request.user.consents.order_by("-granted_at")
        return Response(ConsentSerializer(records, many=True).data)

    def post(self, request):
        serializer = ConsentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record_consents(request.user, {serializer.validated_data["consent_type"]: serializer.validated_data["granted"]}, request=request)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class MeDevicesView(APIView):
    def get(self, request):
        devices = request.user.devices.filter(is_active=True)
        return Response(DeviceSerializer(devices, many=True).data)

    def post(self, request):
        serializer = DeviceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data["push_token"]
        device, _created = Device.objects.update_or_create(
            push_token=token,
            defaults={
                "user": request.user,
                "platform": serializer.validated_data["platform"],
                "is_active": True,
                "last_seen_at": timezone.now(),
            },
        )
        return Response(DeviceSerializer(device).data, status=status.HTTP_201_CREATED)

    def delete(self, request, device_id=None):
        device = get_object_or_404(Device, pk=device_id)
        if device.user_id != request.user.pk:
            raise PermissionDenied("You may only manage your own devices.")
        device.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeDataRequestView(APIView):
    """Privacy export / deletion request intake.

    Deletion is never automatic: evidence under legal hold, unsettled ledger entries
    and statutory records are retained, and the response states so explicitly.
    """

    def post(self, request):
        kind = str(request.data.get("kind", ""))
        if kind not in ("export", "delete"):
            raise ValidationFailed(
                "kind must be 'export' or 'delete'.", details={"field": "kind"}
            )
        logger.info("privacy_request user=%s kind=%s", request.user.pk, kind)
        return Response(
            {
                "request_id": getattr(request, "request_id", None),
                "kind": kind,
                "status": "received",
                "note": (
                    "Your request has been recorded. Deletion requests are reviewed "
                    "against legal hold, financial record and evidence retention "
                    "obligations before any data is removed."
                ),
            },
            status=status.HTTP_202_ACCEPTED,
        )
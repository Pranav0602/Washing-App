"""Support case endpoints available to customers and partners."""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import NotFound, PermissionDenied
from apps.common.permissions import IsAuthenticatedActor
from apps.support.models import SupportCase
from apps.support.serializers import CaseNoteSerializer, OpenCaseSerializer, SupportCaseSerializer
from apps.support.services import cases as case_service


def _visible_cases(user):
    roles = set(user.roles())
    if roles & {"ops", "admin"}:
        return SupportCase.objects.all()
    return SupportCase.objects.filter(opened_by=user)


class SupportCaseCollectionView(APIView):
    """List the caller's cases, or open one on a booking."""

    permission_classes = [IsAuthenticatedActor]

    def get(self, request):
        queryset = _visible_cases(request.user).select_related("booking")
        return Response(
            SupportCaseSerializer(queryset, many=True, context={"request": request}).data
        )

    def post(self, request):
        from apps.bookings.models import Booking

        serializer = OpenCaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        booking_reference = request.data.get("booking_reference")
        if not booking_reference:
            from apps.common.exceptions import ValidationFailed

            raise ValidationFailed(
                "booking_reference is required.", details={"field": "booking_reference"}
            )

        booking = Booking.objects.filter(reference=booking_reference).first()
        if booking is None:
            raise NotFound(f"No booking with reference {booking_reference}.")
        _assert_party(request, booking)

        case = case_service.open_case(
            booking=booking,
            opened_by=request.user,
            category=data["category"],
            description=data["description"],
            evidence_ids=data.get("evidence_ids") or [],
            priority=data.get("priority"),
        )
        return Response(
            SupportCaseSerializer(case, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class SupportCaseDetailView(APIView):
    permission_classes = [IsAuthenticatedActor]

    def get(self, request, reference):
        case = get_object_or_404(SupportCase, reference=reference)
        _assert_case_access(request, case)
        return Response(SupportCaseSerializer(case, context={"request": request}).data)


class SupportCaseNoteView(APIView):
    permission_classes = [IsAuthenticatedActor]

    def post(self, request, reference):
        case = get_object_or_404(SupportCase, reference=reference)
        _assert_case_access(request, case)

        body = str(request.data.get("body", "")).strip()
        if not body:
            from apps.common.exceptions import ValidationFailed

            raise ValidationFailed("A note body is required.", details={"field": "body"})

        internal = bool(request.data.get("is_internal", False))
        if internal and not (set(request.user.roles()) & {"ops", "admin"}):
            raise PermissionDenied("Only operations can add internal notes.")

        note = case_service.add_note(case=case, author=request.user, body=body, internal=internal)
        return Response(CaseNoteSerializer(note).data, status=status.HTTP_201_CREATED)


def _assert_party(request, booking) -> None:
    roles = set(request.user.roles())
    if roles & {"ops", "admin"}:
        return
    if booking.customer_id == request.user.pk:
        return
    profile = getattr(request.user, "partner_profile", None)
    if profile is not None and booking.partner_id == profile.pk:
        return
    raise PermissionDenied("You are not a party to this booking.")


def _assert_case_access(request, case) -> None:
    roles = set(request.user.roles())
    if roles & {"ops", "admin"}:
        return
    if case.opened_by_id == request.user.pk:
        return
    if case.booking_id is not None:
        _assert_party(request, case.booking)
        return
    raise PermissionDenied("You do not have access to this case.")
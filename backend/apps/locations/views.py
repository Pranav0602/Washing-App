"""Customer addresses and public zone endpoints."""

from __future__ import annotations

from datetime import datetime

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from apps.common.exceptions import Conflict, ValidationFailed
from apps.common.permissions import IsCustomer
from apps.locations.models import Address, ServiceZone
from apps.locations.serializers import (
    AddressSerializer,
    ServiceZoneSerializer,
    describe_zone_availability,
)
from apps.locations.services import availability as availability_service


class AddressViewSet(ModelViewSet):
    """A customer's own saved service locations."""

    serializer_class = AddressSerializer
    permission_classes = [IsCustomer]
    pagination_class = None

    def get_queryset(self):
        return Address.objects.filter(owner=self.request.user, is_active=True).order_by(
            "-is_default", "-created_at"
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            if serializer.validated_data.get("is_default"):
                Address.objects.filter(owner=request.user, is_default=True).update(
                    is_default=False
                )
            address = serializer.save(owner=request.user)
        return Response(
            self.get_serializer(address).data, status=status.HTTP_201_CREATED
        )

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=kwargs.get("partial", False))
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            if serializer.validated_data.get("is_default"):
                Address.objects.filter(owner=request.user, is_default=True).exclude(
                    pk=instance.pk
                ).update(is_default=False)
            address = serializer.save()
        return Response(self.get_serializer(address).data)

    def destroy(self, request, *args, **kwargs):
        address = self.get_object()
        from apps.bookings.models import Booking

        if Booking.objects.filter(
            address=address, status__in=Booking.ACTIVE_STATUSES
        ).exists():
            raise Conflict(
                "This address is on an active booking and cannot be removed.",
                code="address_in_use",
            )
        Address.objects.filter(pk=address.pk).update(is_active=False, is_default=False)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ServiceZoneViewSet(ReadOnlyModelViewSet):
    """Public zone list, optionally filtered to those containing a point."""

    serializer_class = ServiceZoneSerializer
    permission_classes = [AllowAny]
    authentication_classes: list = []
    pagination_class = None
    lookup_field = "code"

    def get_queryset(self):
        queryset = ServiceZone.objects.filter(is_active=True)
        city = self.request.query_params.get("city")
        if city:
            queryset = queryset.filter(city=city)
        return queryset.order_by("code")

    def list(self, request, *args, **kwargs):
        lat = request.query_params.get("lat")
        lng = request.query_params.get("lng")
        queryset = self.filter_queryset(self.get_queryset())
        if lat and lng:
            try:
                zone = availability_service.find_zone_for_point(float(lat), float(lng))
            except (TypeError, ValueError):
                raise ValidationFailed(
                    "lat and lng must be numbers.", details={"field": "lat"}
                ) from None
            queryset = queryset.filter(pk=zone.pk) if zone else queryset.none()
        return Response(self.get_serializer(queryset, many=True).data)


class ZoneAvailabilityViewSet(ReadOnlyModelViewSet):
    """Bookable windows and remaining capacity for a zone on a given day."""

    serializer_class = ServiceZoneSerializer
    permission_classes = [AllowAny]
    authentication_classes: list = []
    pagination_class = None
    lookup_field = "code"

    def get_queryset(self):
        return ServiceZone.objects.filter(is_active=True)

    def list(self, request, *args, **kwargs):
        return self.retrieve(request, *args, **kwargs)

    def retrieve(self, request, code=None, *args, **kwargs):
        zone = get_object_or_404(self.get_queryset(), code=code or kwargs.get("code"))
        day_param = request.query_params.get("date")
        day = _parse_day(day_param) or timezone.now()
        return Response(describe_zone_availability(zone=zone, day=day))


def _parse_day(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise ValidationFailed(
            "date must be in YYYY-MM-DD format.", details={"field": "date"}
        ) from None
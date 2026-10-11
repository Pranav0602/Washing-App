"""Customer garage and public catalog endpoints."""

from __future__ import annotations

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from apps.catalog.models import AddOn, PriceRuleVersion, ServiceType, Vehicle
from apps.catalog.serializers import (
    AddOnSerializer,
    PriceRuleVersionSerializer,
    ServiceDetailSerializer,
    ServiceTypeSerializer,
    VehicleSerializer,
)
from apps.common.exceptions import Conflict
from apps.common.permissions import IsCustomer


class VehicleViewSet(ModelViewSet):
    """A customer's own garage.

    The queryset is scoped to the authenticated user, so a client cannot address
    another customer's vehicle by guessing an id.
    """

    serializer_class = VehicleSerializer
    permission_classes = [IsCustomer]
    pagination_class = None

    def get_queryset(self):
        return Vehicle.objects.filter(owner=self.request.user).order_by(
            "-is_default", "-created_at"
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            if serializer.validated_data.get("is_default"):
                Vehicle.objects.filter(owner=request.user, is_default=True).update(
                    is_default=False
                )
            vehicle = serializer.save(owner=request.user)
        return Response(
            self.get_serializer(vehicle).data, status=status.HTTP_201_CREATED
        )

    def destroy(self, request, *args, **kwargs):
        """Soft-delete. A vehicle on an active booking must not disappear."""
        vehicle = self.get_object()
        if vehicle.is_referenced_by_active_booking():
            raise Conflict(
                "This vehicle is on an active booking and cannot be removed yet.",
                code="vehicle_in_use",
                details={"vehicle_id": str(vehicle.pk)},
            )
        Vehicle.objects.filter(pk=vehicle.pk).update(is_active=False, is_default=False)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ServiceTypeViewSet(ReadOnlyModelViewSet):
    """Public service catalog, filterable by site type and vehicle tier."""

    serializer_class = ServiceTypeSerializer
    permission_classes = [AllowAny]
    authentication_classes: list = []
    pagination_class = None
    lookup_field = "code"

    def get_queryset(self):
        queryset = ServiceType.objects.filter(is_active=True)
        site_type = self.request.query_params.get("site_type")
        if site_type:
            # An empty allowed_site_types means unrestricted.
            from django.db.models import Q

            queryset = queryset.filter(
                Q(allowed_site_types__contains=[site_type]) | Q(allowed_site_types=[])
            )
        vehicle_type = self.request.query_params.get("vehicle_type")
        if vehicle_type:
            from apps.common.enums import VEHICLE_TYPE_TO_TIER

            tier = VEHICLE_TYPE_TO_TIER.get(vehicle_type)
            if tier:
                from django.db.models import Q

                queryset = queryset.filter(
                    Q(allowed_vehicle_tiers__contains=[tier]) | Q(allowed_vehicle_tiers=[])
                )
        return queryset.order_by("sort_order", "code")

    def retrieve(self, request, *args, **kwargs):
        service = self.get_object()
        return Response(ServiceDetailSerializer(service, context={"request": request}).data)


class AddOnViewSet(ReadOnlyModelViewSet):
    serializer_class = AddOnSerializer
    permission_classes = [AllowAny]
    authentication_classes: list = []
    pagination_class = None
    lookup_field = "code"

    def get_queryset(self):
        queryset = AddOn.objects.filter(is_active=True)
        service_code = self.request.query_params.get("service_code")
        if service_code:
            from django.db.models import Q

            queryset = queryset.filter(
                Q(allowed_service_codes__contains=[service_code]) | Q(allowed_service_codes=[])
            )
        return queryset.order_by("sort_order", "code")


class CurrentPriceRuleView(ReadOnlyModelViewSet):
    """The pricing ruleset currently in force.

    Exposed read-only so the app can explain a price, and so a mismatch between app
    and server expectations is detectable before a quote is requested.
    """

    serializer_class = PriceRuleVersionSerializer
    permission_classes = [AllowAny]
    authentication_classes: list = []
    pagination_class = None

    def get_queryset(self):
        try:
            return [PriceRuleVersion.current()]
        except PriceRuleVersion.DoesNotExist:
            return PriceRuleVersion.objects.none()

    def list(self, request, *args, **kwargs):
        rule = PriceRuleVersion.current() if PriceRuleVersion.objects.exists() else None
        if rule is None:
            return Response({"results": []})
        return Response({"results": [PriceRuleVersionSerializer(rule).data]})
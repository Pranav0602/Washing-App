"""Identity URLs, mounted under ``/api/v1/``."""

from __future__ import annotations

from django.urls import path

from apps.identity import views

app_name = "identity"

urlpatterns = [
    # --- authentication ---
    path("auth/otp/request", views.OTPRequestView.as_view(), name="otp-request"),
    path("auth/otp/verify", views.OTPVerifyView.as_view(), name="otp-verify"),
    path("auth/otp/resend", views.OTPResendView.as_view(), name="otp-resend"),
    path("auth/refresh", views.RefreshView.as_view(), name="auth-refresh"),
    path("auth/logout", views.LogoutView.as_view(), name="auth-logout"),
    path("auth/staff/login", views.StaffLoginView.as_view(), name="staff-login"),
    path("auth/staff/mfa", views.StaffMfaVerifyView.as_view(), name="staff-mfa"),
    # --- registration ---
    path("auth/register/customer", views.RegisterCustomerView.as_view(), name="register-customer"),
    path("auth/register/partner", views.RegisterPartnerView.as_view(), name="register-partner"),
    # --- account ---
    path("me", views.MeView.as_view(), name="me"),
    path("me/preferences", views.MePreferencesView.as_view(), name="me-preferences"),
    path("me/consents", views.MeConsentsView.as_view(), name="me-consents"),
    path("me/devices", views.MeDevicesView.as_view(), name="me-devices"),
    path("me/devices/<uuid:device_id>", views.MeDevicesView.as_view(), name="me-device-detail"),
    path("me/data-requests", views.MeDataRequestView.as_view(), name="me-data-requests"),
]
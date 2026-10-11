"""Quote URLs, mounted under ``/api/v1/``."""

from __future__ import annotations

from django.urls import path

from apps.quotes import views

app_name = "quotes"

urlpatterns = [
    path("quotes", views.QuoteCollectionView.as_view(), name="quote-collection"),
    path("quotes/<uuid:quote_id>", views.QuoteDetailView.as_view(), name="quote-detail"),
]
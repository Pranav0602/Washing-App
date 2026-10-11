from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    name = "apps.payments"
    label = "payments"
    verbose_name = "Payments, ledger, refunds and payouts"
    default_auto_field = "django.db.models.BigAutoField"

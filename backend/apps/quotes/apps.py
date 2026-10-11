from django.apps import AppConfig


class QuotesConfig(AppConfig):
    name = "apps.quotes"
    label = "quotes"
    verbose_name = "Quotes and the pricing engine"
    default_auto_field = "django.db.models.BigAutoField"

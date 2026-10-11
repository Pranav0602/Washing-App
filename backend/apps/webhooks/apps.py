from django.apps import AppConfig


class WebhooksConfig(AppConfig):
    name = "apps.webhooks"
    label = "webhooks"
    verbose_name = "Payment provider webhooks"
    default_auto_field = "django.db.models.BigAutoField"

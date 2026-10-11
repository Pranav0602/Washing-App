from django.apps import AppConfig


class SupportConfig(AppConfig):
    name = "apps.support"
    label = "support"
    verbose_name = "Support cases and disputes"
    default_auto_field = "django.db.models.BigAutoField"

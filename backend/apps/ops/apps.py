from django.apps import AppConfig


class OpsConfig(AppConfig):
    name = "apps.ops"
    label = "ops"
    verbose_name = "Operations console API"
    default_auto_field = "django.db.models.BigAutoField"

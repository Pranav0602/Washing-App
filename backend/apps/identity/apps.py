from django.apps import AppConfig


class IdentityConfig(AppConfig):
    name = "apps.identity"
    label = "identity"
    verbose_name = "Identity and access"
    default_auto_field = "django.db.models.BigAutoField"
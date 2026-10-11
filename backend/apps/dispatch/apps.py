from django.apps import AppConfig


class DispatchConfig(AppConfig):
    name = "apps.dispatch"
    label = "dispatch"
    verbose_name = "Dispatch eligibility, ranking and offers"
    default_auto_field = "django.db.models.BigAutoField"

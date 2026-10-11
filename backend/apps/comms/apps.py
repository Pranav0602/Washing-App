from django.apps import AppConfig


class CommsConfig(AppConfig):
    name = "apps.comms"
    label = "comms"
    verbose_name = "Masked customer and partner communications"
    default_auto_field = "django.db.models.BigAutoField"

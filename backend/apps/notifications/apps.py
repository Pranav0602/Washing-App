from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    name = "apps.notifications"
    label = "notifications"
    verbose_name = "In-app notifications and the outbox"
    default_auto_field = "django.db.models.BigAutoField"

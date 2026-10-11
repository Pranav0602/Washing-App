from django.apps import AppConfig


class BookingsConfig(AppConfig):
    name = "apps.bookings"
    label = "bookings"
    verbose_name = "Bookings, lifecycle and events"
    default_auto_field = "django.db.models.BigAutoField"

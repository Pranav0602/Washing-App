from django.apps import AppConfig


class CatalogConfig(AppConfig):
    name = "apps.catalog"
    label = "catalog"
    verbose_name = "Vehicle, service and pricing catalog"
    default_auto_field = "django.db.models.BigAutoField"

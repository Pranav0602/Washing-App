from django.apps import AppConfig


class EvidenceConfig(AppConfig):
    name = "apps.evidence"
    label = "evidence"
    verbose_name = "Job evidence records"
    default_auto_field = "django.db.models.BigAutoField"

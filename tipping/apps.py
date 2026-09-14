from django.apps import AppConfig


class TippingConfig(AppConfig):
    default_auto_field = (
        "django.db.models.BigAutoField"
    )

    name = "tipping"

    def ready(self):
        from . import account_retention_signals  # noqa: F401
        from . import bonus_signals  # noqa: F401
        from . import branding_signals  # noqa: F401
        from . import membership_signals  # noqa: F401
        from . import prediction_signals  # noqa: F401
        from . import signals  # noqa: F401

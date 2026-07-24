"""Config Django de l'app `inventory` (voir InventoryConfig)."""

from django.apps import AppConfig


class InventoryConfig(AppConfig):
    """Config de l'app `inventory` — contient les 8 modèles de schema.md."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'inventory'

    def ready(self):
        """Branche les signaux : provisioning OAuth (`signals.py`) et
        régénération auto des propositions de transport (`regenerate_signals.py`)."""
        from . import regenerate_signals  # noqa: F401
        from . import signals  # noqa: F401

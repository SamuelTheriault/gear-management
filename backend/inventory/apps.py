"""Config Django de l'app `inventory` (voir InventoryConfig)."""

from django.apps import AppConfig


class InventoryConfig(AppConfig):
    """Config de l'app `inventory` — contient les 8 modèles de schema.md."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'inventory'

    def ready(self):
        """Branche les signaux de provisioning OAuth (voir inventory/signals.py)."""
        from . import signals  # noqa: F401

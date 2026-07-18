"""
Tests du provisioning automatique de `inventory.User` au login Google OAuth.

Simule l'envoi du signal `allauth.account.signals.user_logged_in` (branché
dans `inventory/signals.py`) plutôt que de dérouler un vrai flux OAuth Google
complet — ce qui suffit à vérifier la logique de provisioning elle-même
(voir `inventory/signals.py` pour la justification de ce choix de signal).
"""

from allauth.account.signals import user_logged_in
from django.contrib.auth.models import User as DjangoUser
from django.test import TestCase

from .models import User as InventoryUser


class OAuthProvisioningTests(TestCase):
    """Vérifie la création/synchronisation de `inventory.User` sur `user_logged_in`."""

    def _simuler_login(self, django_user):
        """Envoie le signal comme le ferait allauth à la fin d'un login réussi."""
        user_logged_in.send(sender=DjangoUser, request=None, user=django_user)

    def test_premier_login_cree_un_inventory_user_viewer(self):
        django_user = DjangoUser.objects.create_user(
            username='vero.tech',
            email='vero@example.com',
            first_name='Véronique',
            last_name='Tech',
        )

        self._simuler_login(django_user)

        self.assertEqual(InventoryUser.objects.count(), 1)
        inventory_user = InventoryUser.objects.get(email='vero@example.com')
        self.assertEqual(inventory_user.role, InventoryUser.ROLE_VIEWER)
        self.assertEqual(inventory_user.django_user_id, django_user.id)
        self.assertEqual(inventory_user.name, 'Véronique Tech')

    def test_login_suivant_ne_duplique_pas_l_utilisateur(self):
        django_user = DjangoUser.objects.create_user(
            username='vero.tech',
            email='vero@example.com',
            first_name='Véronique',
            last_name='Tech',
        )

        self._simuler_login(django_user)
        self.assertEqual(InventoryUser.objects.count(), 1)
        premier_id = InventoryUser.objects.get().id

        # Deuxième connexion du même compte Google (nouvelle session).
        self._simuler_login(django_user)

        self.assertEqual(InventoryUser.objects.count(), 1)
        self.assertEqual(InventoryUser.objects.get().id, premier_id)

    def test_login_relie_un_inventory_user_existant_sans_ecraser_le_role(self):
        # Cas où Samuel a déjà créé/promu l'inventory.User via /admin/ avant
        # que la personne ne se connecte pour la première fois via Google.
        inventory_user = InventoryUser.objects.create(
            email='admin.deja.promu@example.com',
            name='Admin Existant',
            role=InventoryUser.ROLE_ADMIN,
        )
        django_user = DjangoUser.objects.create_user(
            username='admin.deja.promu',
            email='admin.deja.promu@example.com',
        )

        self._simuler_login(django_user)

        inventory_user.refresh_from_db()
        self.assertEqual(InventoryUser.objects.count(), 1)
        self.assertEqual(inventory_user.django_user_id, django_user.id)
        # Le role admin déjà en place ne doit pas être réécrit en viewer.
        self.assertEqual(inventory_user.role, InventoryUser.ROLE_ADMIN)

    def test_sans_email_ne_cree_rien(self):
        django_user = DjangoUser.objects.create_user(username='sans.email', email='')

        self._simuler_login(django_user)

        self.assertEqual(InventoryUser.objects.count(), 0)

"""Signaux applicatifs.

1. Authentification Google OAuth (django-allauth) : provisionne
   automatiquement l'`inventory.User` applicatif correspondant à un compte
   `django.contrib.auth.User` qui vient de se connecter (voir modèle
   `User.django_user` dans `inventory/models.py`).
2. Catégories de matériel : chaque nouveau `Project` reçoit les catégories
   par défaut (voir `MaterialCategory.DEFAULTS`), pour ne pas démarrer une
   production sur une liste vide.

Voir aussi `regenerate_signals.py` pour les signaux du module transport.
"""

from allauth.account.signals import user_logged_in
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import MaterialCategory, Project
from .models import User as InventoryUser


@receiver(user_logged_in)
def provisionner_utilisateur_inventory(request, user, **kwargs):
    """Crée ou retrouve l'`inventory.User` lié au compte Django qui vient de se connecter.

    Branché sur `allauth.account.signals.user_logged_in`, envoyé à **chaque**
    connexion réussie (login classique ou social Google) une fois la session
    Django établie — à ce stade `user` (django.contrib.auth.User) est déjà
    persisté avec un `pk` et un `email` renseignés par le provider Google.
    Ce signal a été préféré à `pre_social_login`/`social_account_added` :
    il est indépendant du provider (robuste si un autre provider social est
    ajouté plus tard), et `user` y est garanti sauvegardé (contrairement à
    `pre_social_login`, où le `User` du `sociallogin` peut ne pas encore
    exister en base), ce qui simplifie la logique de provisioning ci-dessous.

    `get_or_create` sur l'email (avec `django_user` en clé d'idempotence en
    premier lieu) garantit qu'une connexion suivante du même compte Google ne
    duplique pas l'`inventory.User` : `role='viewer'` n'est appliqué que par
    défaut à la création, jamais réécrit sur un compte déjà promu `admin` par
    Samuel via /admin/.
    """
    if not user.email:
        return

    inventory_user = InventoryUser.objects.filter(django_user=user).first()
    if inventory_user is not None:
        return

    inventory_user, created = InventoryUser.objects.get_or_create(
        email=user.email,
        defaults={
            'name': user.get_full_name() or user.username or user.email,
            'django_user': user,
        },
    )
    if not created and inventory_user.django_user_id is None:
        # Un inventory.User existait déjà pour cet email (ex. créé
        # manuellement via /admin/ avant le premier login Google) — on relie
        # les deux comptes sans toucher au `role` déjà en place.
        inventory_user.django_user = user
        inventory_user.save(update_fields=['django_user'])


@receiver(post_save, sender=Project)
def creer_categories_par_defaut(sender, instance, created, **kwargs):
    """Dote chaque nouveau projet des catégories de matériel par défaut.

    Les 9 catégories historiques (ex-`Material.CATEGORY_CHOICES`, devenues des
    lignes de `MaterialCategory` le 2026-07-30) sont recréées à l'identique
    pour toute nouvelle production, plutôt que de laisser Samuel repartir
    d'une liste vide à chaque mandat. Elles restent librement modifiables et
    supprimables ensuite — c'est tout l'intérêt du changement.

    Volontairement idempotent (`get_or_create`) : la duplication de projet
    (`duplication.py`) crée un `Project` puis recopie les catégories du projet
    source, et ne doit pas se retrouver avec des doublons quand les deux
    portent le même nom.
    """
    if not created:
        return
    for name, color in MaterialCategory.DEFAULTS:
        MaterialCategory.objects.get_or_create(
            project=instance, name=name, defaults={'color': color},
        )

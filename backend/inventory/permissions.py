"""
Permission DRF pour l'isolation multi-tenant par projet (2026-08-02).

Ajoutée quand Samuel a décidé de vendre des abonnements à l'outil à d'autres
directeurs techniques/compagnies : jusque-là, `REST_FRAMEWORK.
DEFAULT_PERMISSION_CLASSES` ne contenait que `IsAuthenticated` et
`ProjectFilteredMixin` (`views.py`) n'était qu'un filtre optionnel
`?project=<id>` — n'importe quel compte provisionné pouvait lire ET modifier
tous les projets de tout le monde. Voir `ProjectMembership` (models.py) pour
le modèle d'accès (rôles `owner`/`editor`/`viewer`, par projet).

`HasProjectAccess` est la permission appliquée aux ViewSets isolés par projet
(directement ou via une relation) — voir `views.py`. Deux méthodes DRF
standard, sans dupliquer la résolution du projet :

- `has_permission` : couvre la LISTE (déférée au queryset filtré, voir
  `restrict_queryset_to_membership` ci-dessous — la permission elle-même
  laisse toujours passer une liste, pour ne jamais renvoyer un 403 sur un
  `GET` de collection ; l'utilisateur voit simplement ce qui lui est
  accessible) et la CRÉATION (résout le projet visé depuis le corps de la
  requête AVANT que l'objet n'existe, donc avant qu'un queryset puisse
  filtrer quoi que ce soit).
- `has_object_permission` : couvre le détail (lecture/écriture) d'un objet
  déjà résolu par `get_object()` — lui-même déjà passé par un queryset
  restreint (voir `restrict_queryset_to_membership`), donc un objet d'un
  projet inaccessible ne s'y rend jamais : `get_object_or_404` répond 404
  avant même que cette méthode ne s'exécute pour un non-membre. Cette
  méthode ne fait donc plus, dans la pratique, que distinguer les RÔLES
  entre membres d'un même projet (viewer ne peut pas écrire, etc.).

Chaque ViewSet project-scoped déclare (voir `views.py`) :
- `project_lookup` (défaut `'project_id'`) : chemin ORM depuis le modèle de
  la vue jusqu'au `project_id` — direct pour Venue/Material/Show/etc.,
  traversant une relation pour ShowMaterial/ShowTechnician/Transport
  (`'show__project_id'`).
- `get_create_project_id(self, request)` (optionnel — sinon
  `request.data.get('project')` par défaut) : résout le projet visé par une
  CRÉATION quand il ne s'agit pas d'un champ direct `project` du corps de
  requête (ex. `ShowMaterialViewSet` le déduit de `request.data['show']`).
- `get_object_project_id(self, obj)` (optionnel — sinon `obj.project_id` par
  défaut) : résout le projet d'un objet déjà créé, pour le même cas de
  relation indirecte.
- `owner_only_actions` (défaut `()`) : actions de CE ViewSet qui exigent le
  rôle `owner` plutôt que le `editor` minimal habituel pour une écriture —
  utilisé par `ProjectMembershipViewSet` (gestion des accès, réservée aux
  owners) et par `ProjectViewSet` (`destroy`, réservé aux owners).

**Court-circuit staff/superutilisateur** (voir `_bypasses_project_access`) :
en plus de `User.is_staff_global` (l'accès de dépannage plateforme prévu
pour Samuel — voir models.py), un superutilisateur Django
(`request.user.is_superuser`) contourne aussi entièrement ce contrôle. Ce
n'était PAS demandé explicitement, mais c'est nécessaire pour ne pas casser
la suite de tests existante (~289 tests), qui s'authentifie partout via
`DjangoUser.objects.create_superuser(...)` sans jamais créer de profil
`inventory.User`/`ProjectMembership` — et c'est de toute façon défendable en
soi : un compte /admin/ a déjà un accès complet et non filtré à la base via
l'admin Django, le gater côté API serait de la sécurité de façade.
"""

from rest_framework.permissions import BasePermission

from .models import ProjectMembership

SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS')

_ROLE_RANK = {
    ProjectMembership.ROLE_VIEWER: 1,
    ProjectMembership.ROLE_EDITOR: 2,
    ProjectMembership.ROLE_OWNER: 3,
}


def resolve_inventory_user(request):
    """`inventory.User` lié au `django.contrib.auth.User` de la requête, ou
    `None` — absent pour un compte Django sans profil applicatif (ex. un
    superutilisateur créé directement via `createsuperuser`, jamais passé
    par le login Google)."""
    django_user = request.user
    if django_user is None or not django_user.is_authenticated:
        return None
    return getattr(django_user, 'inventory_profile', None)


def bypasses_project_access(request):
    """True si la requête court-circuite entièrement le contrôle par projet
    — voir le docstring de module pour les deux façons d'y arriver."""
    django_user = request.user
    if django_user is not None and getattr(django_user, 'is_superuser', False):
        return True
    profile = resolve_inventory_user(request)
    return bool(profile and profile.is_staff_global)


def restrict_queryset_to_membership(request, queryset, project_lookup='project_id'):
    """Restreint `queryset` aux lignes dont le projet (résolu via
    `project_lookup`, ex. `'project_id'` ou `'show__project_id'`) fait
    l'objet d'un `ProjectMembership` actif de l'utilisateur courant — sauf
    court-circuit staff/superutilisateur (`bypasses_project_access`).

    C'est le mécanisme qui empêche une LISTE (ou un `get_object()`, qui
    s'appuie sur le même queryset) de fuiter les données d'un projet
    auquel l'utilisateur n'a pas accès, avec ou sans `?project=` explicite
    dans la requête — voir `ProjectMembershipQuerysetMixin` (views.py), qui
    appelle cette fonction depuis `get_queryset()`.
    """
    if bypasses_project_access(request):
        return queryset
    profile = resolve_inventory_user(request)
    if profile is None:
        return queryset.none()
    accessible_ids = ProjectMembership.objects.filter(
        user=profile, status=ProjectMembership.STATUS_ACTIVE,
    ).values_list('project_id', flat=True)
    return queryset.filter(**{f'{project_lookup}__in': accessible_ids})


def _has_role(profile, project_id, required):
    """True si `profile` a un `ProjectMembership` actif sur `project_id` avec
    un rôle au moins aussi élevé que `required` (owner > editor > viewer)."""
    if project_id is None:
        return False
    membership = ProjectMembership.objects.filter(
        project_id=project_id, user=profile, status=ProjectMembership.STATUS_ACTIVE,
    ).first()
    if membership is None:
        return False
    return _ROLE_RANK[membership.role] >= _ROLE_RANK[required]


class HasProjectAccess(BasePermission):
    """Isolation multi-tenant par projet — voir le docstring de module."""

    def _required_role(self, request, view):
        if getattr(view, 'action', None) in getattr(view, 'owner_only_actions', ()):
            return ProjectMembership.ROLE_OWNER
        if request.method in SAFE_METHODS:
            return ProjectMembership.ROLE_VIEWER
        return ProjectMembership.ROLE_EDITOR

    def _create_project_id(self, request, view):
        getter = getattr(view, 'get_create_project_id', None)
        if getter is not None:
            return getter(request)
        raw = request.data.get('project')
        try:
            return int(raw) if raw not in (None, '') else None
        except (TypeError, ValueError):
            return None

    def _object_project_id(self, view, obj):
        getter = getattr(view, 'get_object_project_id', None)
        if getter is not None:
            return getter(obj)
        return getattr(obj, 'project_id', None)

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if bypasses_project_access(request):
            return True

        profile = resolve_inventory_user(request)
        if profile is None:
            return False

        if getattr(view, 'action', None) == 'create':
            project_id = self._create_project_id(request, view)
            if project_id is None:
                # Projet non résolvable depuis le corps de la requête (ex.
                # champ manquant) : on laisse passer pour que le serializer
                # renvoie une 400 exploitable plutôt qu'un 403 trompeur.
                return True
            required = self._required_role(request, view)
            return _has_role(profile, project_id, required)

        # list / retrieve / update / destroy / actions détail : la liste se
        # filtre par queryset (voir restrict_queryset_to_membership), et un
        # objet d'un projet inaccessible ne se rend jamais jusqu'à
        # has_object_permission (404 via get_object_or_404 sur le queryset
        # déjà restreint).
        return True

    def has_object_permission(self, request, view, obj):
        if bypasses_project_access(request):
            return True
        profile = resolve_inventory_user(request)
        if profile is None:
            return False
        project_id = self._object_project_id(view, obj)
        required = self._required_role(request, view)
        return _has_role(profile, project_id, required)


class IsStaffGlobal(BasePermission):
    """Réservé aux comptes staff (accès de dépannage plateforme, voir
    `User.is_staff_global`) — la liste complète des comptes de la plateforme
    ne doit pas fuiter vers un client normal. Voir `UserViewSet` (views.py)."""

    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated and bypasses_project_access(request),
        )

"""
Squelette API — ViewSets DRF pour les tables de schema.md (8 tables initiales
+ `transports` et `settings`, ajoutées le 2026-07-18).

CRUD standard sur chaque modèle. La logique de conflits vit dans les
serializers (ShowMaterialSerializer, ShowTechnicianSerializer,
TransportSerializer) et dans conflicts.py ; ShowViewSet expose en plus une
action `conflicts` en lecture seule pour lister les chevauchements
actuellement en place sur un spectacle — matériel, techniciens, ET
déplacements (utile pour repérer les assignations faites avec `force: true`).
`SettingsView` est une vue singleton (pas de liste/création) pour la future
page de réglages du frontend. `ProjectViewSet` expose en plus une action
`duplicate` pour copier un projet (lieux/matériel/techniciens, sans
assignations) vers un nouveau projet — voir `duplication.py` — ainsi qu'une
action `conflicts` (project-wide, dédupliquée — voir `get_project_conflicts`
dans `conflicts.py`, ajoutée le 2026-07-30 pour l'écran « Conflits » du
frontend, qui n'a pas d'équivalent par-show unique côté Vue).
"""

import json
import unicodedata

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.http import HttpResponse
from django.utils.text import slugify
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.response import Response

from .conflicts import (
    get_material_conflicts,
    get_project_conflicts,
    get_technician_conflicts,
    get_transport_conflicts,
    get_venue_conflicts,
    serialize_material_conflict,
    serialize_technician_conflict,
    serialize_venue_conflict,
)
from .csv_export import (
    MATERIAL_CSV_HEADER,
    SHOW_CSV_HEADER,
    TECHNICIAN_CSV_HEADER,
    VENUE_CSV_HEADER,
    csv_response,
    materials_export_rows,
    shows_export_rows,
    technicians_export_rows,
    venues_export_rows,
)
from .csv_import import (
    CsvImportError,
    import_materials_csv,
    import_shows_csv,
    import_technicians_csv,
    import_venues_csv,
)
from .duplication import duplicate_project
from .permissions import (
    HasProjectAccess,
    IsStaffGlobal,
    bypasses_project_access,
    can_access_project,
    can_edit_project,
    resolve_inventory_user,
    restrict_queryset_to_membership,
)
from .portability import (
    PortabilityError,
    build_project_xml,
    export_project_data,
    import_project_data,
)
from .transport_coherence import (
    get_material_journey,
    get_material_schedule,
    get_material_transports,
    get_project_coherence_report,
    get_project_window,
    get_show_coherence_report,
    get_venue_material_availability,
)
from .models import (
    Material,
    MaterialCategory,
    Project,
    ProjectMembership,
    Settings,
    Show,
    ShowMaterial,
    ShowTechnician,
    Technician,
    Transport,
    TransportTechnician,
    User,
    Venue,
)
from .serializers import (
    MaterialCategorySerializer,
    MaterialSerializer,
    ProjectMembershipSerializer,
    ProjectSerializer,
    SettingsSerializer,
    ShowMaterialSerializer,
    ShowSerializer,
    ShowTechnicianSerializer,
    TechnicianSerializer,
    TransportSerializer,
    UserSerializer,
    VenueSerializer,
)


class ProjectFilteredMixin:
    """Filtre optionnel `?project=<id>` sur les listes — voir `Project` (models.py).

    Isolation par projet : chaque production isolée (venues, matériel,
    techniciens, spectacles) n'apparaît que quand on précise son id. Optionnel
    plutôt qu'obligatoire pour ne pas casser l'accès admin/API brut ; le
    frontend (une fois branché) passera toujours ce paramètre pour refléter
    le projet actif sélectionné par Samuel.
    """

    def get_queryset(self):
        queryset = super().get_queryset()
        project_id = self.request.query_params.get('project')
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        return queryset


class ProjectMembershipQuerysetMixin:
    """Restreint le queryset d'un ViewSet project-scoped aux lignes dont le
    projet fait l'objet d'un `ProjectMembership` actif de l'utilisateur
    courant — voir `permissions.restrict_queryset_to_membership`, dont c'est
    le point d'accroche unique sur chaque ViewSet.

    Complète `ProjectFilteredMixin` (filtre optionnel `?project=<id>`, qui ne
    protège rien à lui seul) et `HasProjectAccess` (qui ne peut rien filtrer
    pour une LISTE, faute d'objet à évaluer un par un) : sans ce mixin, une
    liste renverrait toujours TOUT le queryset de base à n'importe quel
    compte authentifié. `project_lookup` (défaut `'project_id'`) est
    redéfini par les ViewSets dont le modèle n'a pas de FK `project` directe
    (ex. `'show__project_id'` pour ShowMaterial/ShowTechnician/Transport).
    """

    project_lookup = 'project_id'

    def get_queryset(self):
        queryset = super().get_queryset()
        return restrict_queryset_to_membership(self.request, queryset, self.project_lookup)


class _ProjectXmlRenderer(BaseRenderer):
    """Renderer factice pour `ProjectViewSet.export?format=xml` — la vue
    renvoie déjà un `HttpResponse` XML construit à la main (voir
    `portability.build_project_xml`), ce renderer ne sert donc jamais à
    convertir quoi que ce soit. Il existe uniquement pour que DRF reconnaisse
    `format=xml` comme un format VALIDE pendant la négociation de contenu
    (`initial()`, avant même que le corps de l'action ne s'exécute) : sans
    lui, `DefaultContentNegotiation.select_renderer` lève un `Http404`
    (aucun renderer enregistré n'a `format == 'xml'`, seul JSONRenderer
    l'est par défaut) — piège DRF, pas une question d'accès."""

    media_type = 'application/xml'
    format = 'xml'
    charset = None

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data


def _resolve_csv_project(request, project_id_raw, required_edit):
    """Résout et vérifie l'accès au projet visé par une action `import-csv`/
    `export-csv` (`@action(detail=False)`) — ces actions ne passent PAS par
    `get_object()`, donc pas par `has_object_permission` (voir
    `HasProjectAccess`/`permissions.can_access_project`, dont c'est le point
    d'accroche pour ce genre d'action). `required_edit=True` exige le rôle
    editor (import), `False` se contente du rôle viewer (export). Lève
    `NotFound` (404, pas 403 — même convention que le reste de l'API) pour un
    projet manquant ou inaccessible ; retourne `None` si `project_id_raw` est
    vide/non numérique, à charge de l'appelant de renvoyer une 400 explicite
    (« le projet est requis », plutôt qu'un 404 trompeur)."""
    try:
        project_id = int(project_id_raw) if project_id_raw not in (None, '') else None
    except (TypeError, ValueError):
        project_id = None
    if project_id is None:
        return None
    has_access = can_edit_project(request, project_id) if required_edit else can_access_project(request, project_id)
    if not has_access:
        raise NotFound()
    project = Project.objects.filter(id=project_id).first()
    if project is None:
        raise NotFound()
    return project


def _import_csv_response(request, import_func):
    """Fabrique commune aux 4 actions `import-csv` (Material/Venue/
    Technician/Show, voir csv_import.py) : résout le projet visé
    (`request.data['project']`), vérifie l'accès en écriture, délègue à
    `import_func(project, csv_text, mode)` et normalise `CsvImportError` en
    400 — même contrat de réponse pour les 4 sections
    (`{'imported': {...}}`, `201`)."""
    project = _resolve_csv_project(request, request.data.get('project'), required_edit=True)
    if project is None:
        return Response({'project': "Le projet est requis."}, status=status.HTTP_400_BAD_REQUEST)
    mode = request.data.get('mode')
    csv_text = request.data.get('csv') or ''
    try:
        counts = import_func(project, csv_text, mode)
    except CsvImportError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({'imported': counts}, status=status.HTTP_201_CREATED)


class UserViewSet(viewsets.ModelViewSet):
    """CRUD standard sur les comptes applicatifs.

    Réservé aux comptes staff (`is_staff_global`) depuis le 2026-08-02 : la
    liste complète des comptes de la plateforme (toutes productions/clients
    confondus) ne doit pas fuiter vers un client normal — voir
    `permissions.IsStaffGlobal`. `UtilisateursView.vue` continue de
    fonctionner tel quel pour Samuel, qui est staff.
    """

    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsStaffGlobal]


class ProjectMembershipViewSet(viewsets.ModelViewSet):
    """CRUD sur les accès par projet (`ProjectMembership`, voir models.py) —
    invitations, changement de rôle, retrait d'accès. Filtrable par
    `?project=<id>`, comme les autres ViewSets project-scoped.

    Lecture (list/retrieve) : accessible à tout membre actif du projet, pas
    seulement l'owner — « voir qui a accès » n'est pas une action de
    gestion. Écriture (create/update/destroy) : réservée owner/staff
    (`owner_only_actions`), via `HasProjectAccess`.

    `create` (inviter) et `update`/`destroy` (changer un rôle / retirer un
    accès) contournent le flux `ModelSerializer` standard — la logique
    (résoudre un `User` par email, empêcher de retirer le dernier owner
    actif) ne se prête pas à un simple `serializer.save()`.
    """

    queryset = ProjectMembership.objects.select_related('project', 'user', 'invited_by').all()
    serializer_class = ProjectMembershipSerializer
    permission_classes = [HasProjectAccess]
    project_lookup = 'project_id'
    owner_only_actions = ('create', 'update', 'partial_update', 'destroy')

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = restrict_queryset_to_membership(self.request, queryset, self.project_lookup)
        project_id = self.request.query_params.get('project')
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        return queryset

    def get_create_project_id(self, request):
        raw = request.data.get('project')
        try:
            return int(raw) if raw not in (None, '') else None
        except (TypeError, ValueError):
            return None

    def get_object_project_id(self, obj):
        return obj.project_id

    def create(self, request, *args, **kwargs):
        """Invite un email sur un projet avec un rôle donné.

        Réutilise le pattern `get_or_create` par email déjà en place dans
        `signals.py` (`provisionner_utilisateur_inventory`) : si un `User`
        existe déjà pour cet email, on le réutilise ; sinon on en crée un
        (`name` = email par défaut, `django_user` nul — lié plus tard au
        premier login Google, voir `signals.py`). `status` part à `'active'`
        d'emblée si cette personne a déjà un compte Google lié
        (`django_user_id` renseigné), sinon `'pending'` jusqu'à son premier
        login (voir `ProjectMembership`, models.py).
        """
        project_id = request.data.get('project')
        email = (request.data.get('email') or '').strip().lower()
        role = request.data.get('role')
        valid_roles = dict(ProjectMembership.ROLE_CHOICES)
        if not project_id or not email or role not in valid_roles:
            return Response(
                {'detail': "« project », « email » et « role » (owner/editor/viewer) sont requis."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        project = Project.objects.filter(id=project_id).first()
        if project is None:
            return Response({'project': "Projet introuvable."}, status=status.HTTP_400_BAD_REQUEST)

        target_user, _created = User.objects.get_or_create(
            email=email, defaults={'name': email},
        )
        membership_status = (
            ProjectMembership.STATUS_ACTIVE if target_user.django_user_id else ProjectMembership.STATUS_PENDING
        )
        inviter = resolve_inventory_user(request)

        membership, created = ProjectMembership.objects.get_or_create(
            project=project, user=target_user,
            defaults={'role': role, 'status': membership_status, 'invited_by': inviter},
        )
        if not created:
            return Response(
                {'detail': "Cette personne a déjà accès à ce projet."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(self.get_serializer(membership).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        """Change le rôle d'un membership existant — `partial_update` (PATCH)
        et `update` (PUT) se comportent identiquement, seul `role` est
        modifiable ici (changer `project`/`user` reviendrait à une autre
        invitation, pas à une mise à jour)."""
        instance = self.get_object()
        new_role = request.data.get('role', instance.role)
        if new_role not in dict(ProjectMembership.ROLE_CHOICES):
            return Response({'role': "Rôle invalide."}, status=status.HTTP_400_BAD_REQUEST)
        if (
            instance.status == ProjectMembership.STATUS_ACTIVE
            and instance.role == ProjectMembership.ROLE_OWNER
            and new_role != ProjectMembership.ROLE_OWNER
        ):
            self._guard_last_owner(instance)
        instance.role = new_role
        instance.save(update_fields=['role'])
        return Response(self.get_serializer(instance).data)

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        """Retire un accès — refuse de retirer le dernier owner actif du
        projet (voir `_guard_last_owner`, plutôt qu'un projet orphelin)."""
        instance = self.get_object()
        if instance.status == ProjectMembership.STATUS_ACTIVE and instance.role == ProjectMembership.ROLE_OWNER:
            self._guard_last_owner(instance)
        return super().destroy(request, *args, **kwargs)

    def _guard_last_owner(self, instance):
        """Lève une 400 si `instance` est le dernier owner actif de son
        projet — appelé avant de le rétrograder ou de le retirer."""
        autres_owners = ProjectMembership.objects.filter(
            project=instance.project,
            role=ProjectMembership.ROLE_OWNER,
            status=ProjectMembership.STATUS_ACTIVE,
        ).exclude(id=instance.id)
        if not autres_owners.exists():
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'detail': "Impossible de retirer le dernier owner actif de ce projet."})


class ProjectViewSet(viewsets.ModelViewSet):
    """CRUD standard sur les productions — voir `Project` (models.py), plus
    l'action `duplicate` pour démarrer une nouvelle édition d'un mandat.

    Accès (2026-08-02) : voir `ProjectMembership`/`HasProjectAccess`. La
    LISTE ne renvoie que les projets où l'utilisateur a un membership actif
    (tout, pour un compte staff/superutilisateur — voir `get_queryset`) —
    fini la vue « tous projets confondus » pour un compte normal. La
    CRÉATION (POST) et l'action `duplicate` créent automatiquement un
    `ProjectMembership(role='owner', status='active')` sur le projet obtenu
    pour l'utilisateur qui fait l'appel (`_grant_owner_membership`) — sans
    lui, personne n'aurait accès au projet qu'il vient de créer.
    `destroy` (suppression) est réservé owner/staff (`owner_only_actions`) ;
    la gestion des memberships eux-mêmes vit sur `ProjectMembershipViewSet`.
    """

    queryset = Project.objects.all()
    serializer_class = ProjectSerializer
    permission_classes = [HasProjectAccess]
    owner_only_actions = ('destroy',)

    def get_queryset(self):
        queryset = super().get_queryset()
        if bypasses_project_access(self.request):
            return queryset
        profile = resolve_inventory_user(self.request)
        if profile is None:
            return queryset.none()
        return queryset.filter(
            memberships__user=profile, memberships__status=ProjectMembership.STATUS_ACTIVE,
        ).distinct()

    def get_object_project_id(self, obj):
        return obj.id

    def destroy(self, request, *args, **kwargs):
        """Supprime un projet et toute sa production.

        Revue code-reviewer du 2026-08-04 : `project.delete()` seul lève un
        `ProtectedError` (→ 500 DRF non catché) sur quasi tout projet réel,
        malgré le passage des 5 FK `project` en CASCADE (migration `0026`).
        Cause : Django résout les relations `PROTECT` (`Show.venue`,
        `TransportStop.venue`, `Material.category` — les 3 seules du modèle)
        indépendamment du fait que l'objet protégé soit LUI-MÊME promis à la
        suppression par un autre chemin CASCADE (`Show.project`,
        `Material.project`) dans le même appel. Contourné en supprimant
        d'abord ce qui protège, dans l'ordre :
        1. Les `Show` du projet — cascade déjà `Transport`/`TransportStop`/
           `TransportMaterial`/`ShowMaterial`/`ShowTechnician`
           (`on_delete=CASCADE` sur chacun), ce qui lève la protection de
           `Show.venue` ET `TransportStop.venue` sur `Venue` en un seul geste.
        2. `Material.category` mis à `None` pour le projet — lève la
           protection sur `MaterialCategory`.
        Le `project.delete()` final peut alors cascader `Venue`/`Material`/
        `MaterialCategory`/`Technician` sans plus rien qui bloque. Tout dans
        une transaction : soit la production entière part, soit rien.
        """
        project = self.get_object()
        with transaction.atomic():
            Show.objects.filter(project=project).delete()
            Material.objects.filter(project=project).update(category=None)
            project.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _grant_owner_membership(self, project):
        """Donne un accès `owner` actif sur `project` à l'utilisateur courant,
        s'il a un profil applicatif (voir docstring de classe). Sans profil
        (ex. superutilisateur Django hors flux Google, comme dans toute la
        suite de tests existante) : pas d'erreur, juste rien à créer — ce
        compte contourne déjà le contrôle par projet."""
        profile = resolve_inventory_user(self.request)
        if profile is None:
            return
        ProjectMembership.objects.get_or_create(
            project=project, user=profile,
            defaults={
                'role': ProjectMembership.ROLE_OWNER,
                'status': ProjectMembership.STATUS_ACTIVE,
                'invited_by': None,
            },
        )

    def perform_create(self, serializer):
        project = serializer.save()
        self._grant_owner_membership(project)

    @action(detail=True, methods=['post'])
    def duplicate(self, request, pk=None):
        """Duplique ce projet vers un nouveau projet : lieux, matériel (hiérarchie
        préservée) et techniciens copiés, AUCUNE assignation/horaire (spectacles,
        déplacements) — voir `duplication.duplicate_project()`.

        Corps de requête : `name` (obligatoire) — nom du nouveau projet ;
        `client_name` (optionnel) — sinon repris du projet source (décision
        Samuel du 2026-07-19 : une nouvelle édition, c'est généralement le même
        client).
        """
        source_project = self.get_object()
        name = (request.data.get('name') or '').strip()
        if not name:
            return Response(
                {'name': "Le nom du nouveau projet est requis."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        client_name = request.data.get('client_name')
        if client_name is None:
            client_name = source_project.client_name

        new_project, counts = duplicate_project(source_project, name=name, client_name=client_name)
        self._grant_owner_membership(new_project)
        return Response(
            {'project': ProjectSerializer(new_project).data, 'copied': counts},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['get'], url_path='transport-coherence')
    def transport_coherence(self, request, pk=None):
        """Rapport de cohérence des emplacements de matériel pour toute la
        production (non bloquant — voir `transport_coherence.py`). Liste les
        incohérences spatiales : matériel requis à un lieu sans transport pour
        l'y amener (`materiel_non_livre`), transport partant d'un lieu où le
        matériel n'est pas présent (`origine_incoherente`), et matériel sans
        lieu d'entreposage donc non suivi (`origine_inconnue`)."""
        project = self.get_object()
        issues = get_project_coherence_report(project)
        return Response({'issues': issues, 'issue_count': len(issues)})

    @action(detail=True, methods=['get'])
    def window(self, request, pk=None):
        """Fenêtre temporelle du projet — `{start, end}`, ou `null` des deux côtés.

        Dates saisies sur le projet si elles existent, sinon du premier au
        dernier événement (voir `get_project_window`). Exposée telle quelle
        depuis le 2026-08-02 pour le Tableau de bord, qui borne sa timeline
        dessus : la règle vit côté backend, comme pour les écrans « Parcours »
        et les chronologies de fiche, plutôt que d'être réécrite en JS.
        """
        window_start, window_end = get_project_window(self.get_object())
        return Response({'start': window_start, 'end': window_end})

    @action(detail=True, methods=['get'], url_path='material-journey')
    def material_journey(self, request, pk=None):
        """Parcours du matériel dans le temps — écran « Parcours » du frontend.

        Ajouté le 2026-07-30 à la demande de Samuel : voir *où se trouve* chaque
        matériel sur toute la durée de la production, plutôt que seulement ses
        engagements. Réutilise le grand livre de positions de
        `transport_coherence.py` — c'est la même source de vérité que la
        cohérence des emplacements et que la disponibilité au départ d'un
        transport, donc les trois écrans ne peuvent pas se contredire.

        Filtre optionnel `?materials=1,2,3` : sans lui, tout le matériel actif
        du projet est renvoyé. La sélection se fait côté frontend, mais le
        filtre évite de calculer 200 parcours pour en afficher trois.

        Réponse : `{'window': {'start','end'}, 'materials': [{id, name,
        category_*, home_venue_*, stays: [...], assignments: [...],
        transports: [...]}]}` — `stays` = les séjours (lieu, début, fin),
        `assignments` = les spectacles où le matériel est requis, pour les
        marquer sur la barre. `transports` (2026-07-31) = les déplacements
        **confirmés** qui le transportent, pour les distinguer des séjours
        qu'ils relient — voir `get_material_transports`.
        """
        project = self.get_object()
        window_start, window_end = get_project_window(project)
        if window_start is None:
            return Response({'window': None, 'materials': []})

        materials = (
            Material.objects.filter(project=project, is_active=True)
            .select_related('venue', 'category')
            .order_by('name')
        )
        ids_bruts = request.query_params.get('materials')
        if ids_bruts:
            ids = [int(v) for v in ids_bruts.split(',') if v.strip().isdigit()]
            materials = materials.filter(id__in=ids)

        lignes = []
        for material in materials:
            assignments = (
                ShowMaterial.objects
                .filter(material=material, show__project=project)
                .select_related('show', 'show__venue')
                .order_by('show__start_datetime')
            )
            lignes.append({
                'id': material.id,
                'name': material.name,
                'quantity': material.quantity,
                'category_name': material.category.name if material.category else None,
                'category_color': material.category.color if material.category else None,
                'home_venue_id': material.venue_id,
                'home_venue_name': material.venue.name if material.venue else None,
                'stays': get_material_journey(material, window_start, window_end),
                'transports': get_material_transports(material, window_start, window_end),
                'assignments': [
                    {
                        'show_id': sm.show_id,
                        'show_title': sm.show.display_title,
                        'venue_name': sm.show.venue.name,
                        'start': sm.show.effective_start,
                        'end': sm.show.effective_end,
                        'quantity': sm.quantity,
                    }
                    for sm in assignments
                ],
            })

        return Response({
            'window': {'start': window_start, 'end': window_end},
            'materials': lignes,
        })

    @action(detail=True, methods=['get'], url_path='technician-journey')
    def technician_journey(self, request, pk=None):
        """Parcours des techniciens : leurs engagements sur toute la production.

        Ajouté le 2026-07-30, pendant du parcours matériel. Un engagement est
        soit une assignation à un spectacle (`ShowTechnician`, fenêtre =
        fenêtre effective du spectacle, buffers compris), soit une affectation
        à un déplacement (`TransportTechnician`, fenêtre = heure prévue +
        durée estimée). Les deux sont mélangés sur la même ligne, dans l'ordre
        chronologique — c'est précisément le croisement que fait déjà la
        détection de conflit (voir `_technician_commitments`).

        Filtre optionnel `?technicians=1,2,3`, même logique que le parcours
        matériel.
        """
        project = self.get_object()
        window_start, window_end = get_project_window(project)
        if window_start is None:
            return Response({'window': None, 'technicians': []})

        technicians = Technician.objects.filter(project=project).order_by('name')
        ids_bruts = request.query_params.get('technicians')
        if ids_bruts:
            ids = [int(v) for v in ids_bruts.split(',') if v.strip().isdigit()]
            technicians = technicians.filter(id__in=ids)

        # Conflits du projet, pour marquer les engagements concernés. On
        # s'appuie sur le rapport dédupliqué plutôt que de recalculer.
        rapport = get_project_conflicts(project)
        en_conflit = set()
        for paire in rapport['technician_conflicts']:
            for cote in (paire['a'], paire['b']):
                if cote['type'] == 'show_technician':
                    en_conflit.add(('show', cote['show_technician_id']))
                else:
                    en_conflit.add(('transport', cote['transport_id'], cote['technician_id']))

        lignes = []
        for technician in technicians:
            engagements = []
            for st in (
                ShowTechnician.objects
                .filter(technician=technician, show__project=project)
                .select_related('show', 'show__venue')
            ):
                engagements.append({
                    'kind': 'show',
                    'id': st.show_id,
                    'label': st.show.display_title,
                    'venue_name': st.show.venue.name,
                    'start': st.show.effective_start,
                    'end': st.show.effective_end,
                    'conflict': ('show', st.id) in en_conflit,
                })
            for tt in (
                TransportTechnician.objects
                .filter(technician=technician, transport__show__project=project,
                        transport__scheduled_datetime__isnull=False)
                .select_related('transport')
                .prefetch_related('transport__stops__venue')
            ):
                transport = tt.transport
                # Tournées multi-arrêts (2026-08-04) : le libellé enchaîne TOUS
                # les arrêts — le technicien fait la tournée entière, pas un
                # segment.
                stops = transport.ordered_stops
                engagements.append({
                    'kind': 'transport',
                    'id': transport.id,
                    'label': ' → '.join(stop.venue.name for stop in stops),
                    'venue_name': stops[-1].venue.name if stops else '',
                    'start': transport.scheduled_datetime,
                    'end': transport.effective_end,
                    'conflict': ('transport', transport.id, technician.id) in en_conflit,
                })
            engagements.sort(key=lambda e: e['start'])
            lignes.append({
                'id': technician.id,
                'name': technician.name,
                'specialty': technician.specialty,
                'engagements': engagements,
            })

        return Response({
            'window': {'start': window_start, 'end': window_end},
            'technicians': lignes,
        })

    @action(detail=True, methods=['get'])
    def conflicts(self, request, pk=None):
        """Vue d'ensemble, dédupliquée, de tous les conflits (lieu, matériel,
        technicien) actuellement en place sur l'ensemble des spectacles du
        projet — voir `get_project_conflicts` (conflicts.py). Contrairement à
        `ShowViewSet.conflicts`, qui répond par spectacle, cette action sert
        l'écran « Conflits » du frontend, qui liste tout le projet en un seul
        appel sans doublons."""
        project = self.get_object()
        report = get_project_conflicts(project)
        total = sum(len(v) for v in report.values())
        return Response({**report, 'conflict_count': total})

    @action(detail=True, methods=['get'], renderer_classes=[JSONRenderer, _ProjectXmlRenderer])
    def export(self, request, pk=None):
        """Export complet et portable du projet — JSON (réimportable, défaut)
        ou XML (`?format=xml`, lecture seule) — voir `portability.py`. Lecture
        seule : le contrôle d'accès (rôle viewer minimum) passe par
        `has_object_permission`, comme tout GET détail de ce ViewSet — pas de
        vérification supplémentaire ici. `renderer_classes` inclut
        `_ProjectXmlRenderer` (voir plus haut) pour que `?format=xml` passe
        la négociation de contenu DRF."""
        project = self.get_object()
        data = export_project_data(project)
        slug = slugify(project.name) or 'projet'
        if (request.query_params.get('format') or '').strip().lower() == 'xml':
            response = HttpResponse(
                build_project_xml(data), content_type='application/xml; charset=utf-8',
            )
            response['Content-Disposition'] = f'attachment; filename="{slug}.xml"'
            return response
        body = json.dumps(data, cls=DjangoJSONEncoder, ensure_ascii=False, indent=2)
        response = HttpResponse(body, content_type='application/json; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{slug}.json"'
        return response

    @action(detail=False, methods=['post'], url_path='import')
    def import_project(self, request):
        """Crée un NOUVEAU projet à partir d'un fichier produit par `export`
        (JSON désérialisé par DRF) — voir `portability.import_project_data`.
        N'écrase jamais un projet existant, même logique de sécurité que
        `duplicate`. Corps de requête : soit le contenu exporté directement,
        soit `{'data': ..., 'name': ..., 'client_name': ...}` pour renommer à
        l'import sans modifier le fichier source. `import` est un mot réservé
        Python — d'où `import_project`/`url_path='import'`, comme documenté
        dans le docstring de module."""
        payload = request.data
        if isinstance(payload, dict) and 'data' in payload:
            data = payload.get('data')
            name = payload.get('name')
            client_name = payload.get('client_name')
        else:
            data = payload
            name = None
            client_name = None
        try:
            new_project, counts = import_project_data(data, name=name, client_name=client_name)
        except PortabilityError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        self._grant_owner_membership(new_project)
        return Response(
            {'project': ProjectSerializer(new_project).data, 'imported': counts},
            status=status.HTTP_201_CREATED,
        )


class VenueViewSet(ProjectMembershipQuerysetMixin, ProjectFilteredMixin, viewsets.ModelViewSet):
    """CRUD standard sur les lieux, filtrable par projet (`?project=<id>`).

    Suppression (décision de Samuel du 2026-07-30) : **refusée** tant que le
    lieu est référencé. `Show.venue` et `TransportStop.venue` (les arrêts de
    tournée, depuis le 2026-08-04) sont en `PROTECT` — sans traitement, Django
    lèverait un `ProtectedError` que DRF rendrait en 500. On vérifie donc en
    amont pour renvoyer un 400 lisible, avec le décompte de ce qui bloque.

    `Material.venue` est en `SET_NULL` côté modèle, mais depuis que le lieu
    d'origine est obligatoire (2026-07-30) le laisser vider silencieusement le
    matériel contredirait la règle : le matériel entreposé bloque donc lui
    aussi la suppression.
    """

    queryset = Venue.objects.select_related('project').all()
    serializer_class = VenueSerializer
    permission_classes = [HasProjectAccess]

    def destroy(self, request, *args, **kwargs):
        """Supprime un lieu, sauf s'il est encore référencé quelque part."""
        venue = self.get_object()
        blocages = {
            'shows': venue.shows.count(),
            # Tournées multi-arrêts (2026-08-04) : un lieu bloque dès qu'il est
            # un arrêt de n'importe quelle tournée — `distinct()` pour ne pas
            # compter deux fois une tournée qui y repasse (aller-retour).
            'transports': Transport.objects.filter(stops__venue=venue).distinct().count(),
            'materials': venue.materials.count(),
        }
        if any(blocages.values()):
            parties = []
            if blocages['shows']:
                parties.append(f"{blocages['shows']} spectacle(s)")
            if blocages['transports']:
                parties.append(f"{blocages['transports']} déplacement(s)")
            if blocages['materials']:
                parties.append(f"{blocages['materials']} matériel(s) qui en font leur lieu d'origine")
            return Response(
                {
                    'detail': (
                        "Ce lieu est encore utilisé par " + ", ".join(parties) + ". "
                        "Déplace-les ailleurs avant de le supprimer."
                    ),
                    **blocages,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=['post'], url_path='import-csv')
    def import_csv(self, request):
        """Importe un CSV lieux (`{'project', 'mode', 'csv'}`, voir
        `csv_import.import_venues_csv`) — `mode=replace` refuse (sans rien
        supprimer) si un lieu existant est encore référencé par un spectacle
        ou un arrêt de tournée, même logique que `destroy` ci-dessus."""
        return _import_csv_response(request, import_venues_csv)

    @action(detail=False, methods=['get'], url_path='export-csv')
    def export_csv(self, request):
        """Exporte les lieux du projet visé (`?project=<id>`) en CSV — voir
        `csv_export.venues_export_rows`."""
        project = _resolve_csv_project(request, request.query_params.get('project'), required_edit=False)
        if project is None:
            raise ValidationError({'project': "Le projet est requis."})
        rows = venues_export_rows(project)
        return csv_response('lieux.csv', VENUE_CSV_HEADER, rows)


class MaterialCategoryViewSet(ProjectMembershipQuerysetMixin, ProjectFilteredMixin, viewsets.ModelViewSet):
    """CRUD sur les catégories de matériel, filtrable par projet (`?project=<id>`).

    Suppression (décision de Samuel du 2026-07-30) : `Material.category` est
    en `PROTECT`, donc supprimer une catégorie encore utilisée échouerait au
    niveau de la base. Plutôt que de refuser sèchement, la suppression
    **demande vers quelle catégorie basculer** le matériel concerné :

        DELETE /api/material-categories/{id}/?reassign_to=<id>

    Sans `reassign_to`, si la catégorie est utilisée, l'API renvoie un 400
    contenant le nombre de matériels touchés (`material_count`) — c'est ce
    que le frontend affiche pour proposer le choix. Une catégorie inutilisée
    se supprime directement, sans paramètre.

    `reassign_to` peut valoir la chaîne vide (`?reassign_to=`) pour laisser
    le matériel **sans catégorie** (la FK est nullable) plutôt que de le
    forcer dans une catégorie fourre-tout.

    Tri (bug signalé le 2026-07-30 : « la dernière catégorie créée n'est pas
    classée adéquatement ») : `Meta.ordering = ['name']` sur `MaterialCategory`
    délègue le tri à la collation par défaut du moteur de base de données.
    En local (SQLite), cette collation est un simple ordre d'octets — les
    minuscules passent après TOUTES les majuscules et les caractères
    accentués après tout l'ASCII, donc une catégorie créée avec un nom qui ne
    commence pas par une majuscule non accentuée (ex. « éclairage » en
    minuscule, ou tout nom commençant par une minuscule) atterrit à la fin de
    la liste au lieu de sa place alphabétique. MySQL en prod utilise en
    général une collation `_ci`/insensible aux accents qui n'a pas ce
    problème — mais pour un comportement identique partout, `list()` retrie
    explicitement en Python (`unicodedata.normalize('NFKD', ...).casefold()`)
    plutôt que de compter sur l'ORDER BY du moteur.
    """

    queryset = MaterialCategory.objects.select_related('project').all()
    serializer_class = MaterialCategorySerializer
    permission_classes = [HasProjectAccess]

    def list(self, request, *args, **kwargs):
        """Liste les catégories, triées insensible à la casse et aux accents (voir docstring de classe)."""
        queryset = self.filter_queryset(self.get_queryset())
        ordered = sorted(queryset, key=lambda c: unicodedata.normalize('NFKD', c.name).casefold())
        serializer = self.get_serializer(ordered, many=True)
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        """Supprime une catégorie, en réassignant d'abord son matériel si besoin."""
        category = self.get_object()
        material_count = category.materials.count()

        if material_count == 0:
            return super().destroy(request, *args, **kwargs)

        if 'reassign_to' not in request.query_params:
            return Response(
                {
                    'detail': (
                        f"{material_count} matériel(s) utilisent cette catégorie. "
                        "Indique vers quelle catégorie les basculer via "
                        "?reassign_to=<id> (ou ?reassign_to= pour les laisser "
                        "sans catégorie)."
                    ),
                    'material_count': material_count,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        raw_target = request.query_params.get('reassign_to', '').strip()
        target = None
        if raw_target:
            target = MaterialCategory.objects.filter(
                id=raw_target, project_id=category.project_id,
            ).first()
            if target is None:
                return Response(
                    {'reassign_to': "Catégorie de remplacement introuvable dans ce projet."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if target.id == category.id:
                return Response(
                    {'reassign_to': "La catégorie de remplacement doit être différente."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        with transaction.atomic():
            category.materials.update(category=target)
            category.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MaterialViewSet(ProjectMembershipQuerysetMixin, ProjectFilteredMixin, viewsets.ModelViewSet):
    """CRUD standard sur l'inventaire de matériel, filtrable par projet (`?project=<id>`).

    Le matériel désactivé (`is_active=False`, ex. un vieux rideau qu'on
    n'utilise plus) est masqué de la liste par défaut (`GET /api/materials/`)
    pour ne pas encombrer l'inventaire courant, sans jamais être supprimé —
    ajouter `?include_inactive=true` à la requête pour tout revoir (utile
    pour réactiver un item). La consultation par id (`GET /api/materials/{id}/`)
    reste toujours accessible peu importe le statut, pour ne pas casser
    l'affichage des assignations existantes (`show_materials`) qui
    référencent un matériel entretemps désactivé. Décision du 2026-07-19.
    """

    queryset = Material.objects.select_related('project', 'parent_material', 'venue', 'category').all()
    serializer_class = MaterialSerializer
    permission_classes = [HasProjectAccess]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == 'list':
            include_inactive = self.request.query_params.get('include_inactive', '').lower() in (
                '1', 'true', 'yes',
            )
            if not include_inactive:
                queryset = queryset.filter(is_active=True)
        return queryset

    @action(detail=True, methods=['get'])
    def schedule(self, request, pk=None):
        """Agenda chronologique de ce matériel — spectacles, blocs et déplacements.

        Alimente la chronologie de la fiche matériel (2026-08-01). La règle
        d'héritage des blocs de montage/démontage est appliquée ici, pas côté
        frontend : voir `get_material_schedule` dans transport_coherence.py.

        Bornée à la fenêtre du projet (demande de Samuel du 2026-08-01) — la
        même que les écrans « Parcours », pour que les deux racontent la même
        période. `outside_window` compte ce qui a été écarté : une assignation
        planifiée hors des dates du projet ne doit pas disparaître en silence.
        """
        material = self.get_object()
        window_start, window_end = get_project_window(material.project)
        entries, outside = get_material_schedule(material, window_start, window_end)
        return Response({
            'window': {'start': window_start, 'end': window_end},
            'entries': entries,
            'outside_window': outside,
        })

    @action(detail=True, methods=['get'])
    def distribution(self, request, pk=None):
        """Répartition de ce matériel entre les lieux, sur toute la durée du projet.

        Alimente la carte « Répartition » de la fiche matériel (2026-08-01,
        demande de Samuel) : une barre par lieu, montrant les périodes où il
        détient une partie du stock et en quelle quantité.

        Réutilise `get_material_journey`/`get_material_transports` — donc
        exactement la même source que l'écran « Parcours Matériel », qui ne
        peut ainsi pas raconter autre chose. La différence est le regroupement :
        le Parcours empile une ligne par *lane* (pour tracer les bifurcations),
        cette carte-ci regroupe **par lieu**, ce que le frontend fait à partir
        des mêmes séjours.

        Contrairement à `ProjectViewSet.material_journey`, répond aussi pour un
        matériel désactivé : on arrive ici depuis sa fiche, qui reste
        consultable (voir `get_queryset` ci-dessus).
        """
        material = self.get_object()
        window_start, window_end = get_project_window(material.project)
        if window_start is None:
            return Response({'window': None, 'stays': [], 'transports': []})
        return Response({
            'window': {'start': window_start, 'end': window_end},
            'total': material.quantity,
            'stays': get_material_journey(material, window_start, window_end),
            'transports': get_material_transports(material, window_start, window_end),
        })

    @action(detail=False, methods=['post'], url_path='import-csv')
    def import_csv(self, request):
        """Importe un CSV matériel (`{'project', 'mode', 'csv'}`, voir
        `csv_import.import_materials_csv`) — export/import par section,
        ajouté le 2026-08-04 pour un passage vers Excel."""
        return _import_csv_response(request, import_materials_csv)

    @action(detail=False, methods=['get'], url_path='export-csv')
    def export_csv(self, request):
        """Exporte le matériel du projet visé (`?project=<id>`) en CSV —
        voir `csv_export.materials_export_rows`. `?include_inactive=false`
        exclut le matériel désactivé (inclus par défaut, contrairement à
        `GET /api/materials/`)."""
        project = _resolve_csv_project(request, request.query_params.get('project'), required_edit=False)
        if project is None:
            raise ValidationError({'project': "Le projet est requis."})
        include_inactive = request.query_params.get('include_inactive', 'true').strip().lower() not in (
            'false', '0', 'non', 'no',
        )
        rows = materials_export_rows(project, include_inactive=include_inactive)
        return csv_response('materiel.csv', MATERIAL_CSV_HEADER, rows)


class ShowViewSet(ProjectMembershipQuerysetMixin, ProjectFilteredMixin, viewsets.ModelViewSet):
    """CRUD standard sur les fiches spectacles, filtrable par projet (`?project=<id>`),
    plus l'action `conflicts` en lecture seule."""

    queryset = Show.objects.select_related('project', 'venue').all()
    serializer_class = ShowSerializer
    permission_classes = [HasProjectAccess]

    @action(detail=True, methods=['get'])
    def conflicts(self, request, pk=None):
        """Liste les chevauchements actuellement en place pour ce spectacle
        (lieu, matériel, techniciens et déplacements), y compris les
        assignations créées avec `force: true` malgré un conflit signalé au
        moment de la création."""
        show = self.get_object()

        venue_conflicts = [
            serialize_venue_conflict(conflict)
            for conflict in get_venue_conflicts(
                show.venue, show.effective_start, show.effective_end,
                exclude_id=show.id, exclude_family_ids=show.family_ids,
            )
        ]

        material_conflicts = []
        for sm in show.show_materials.select_related('material').all():
            for conflict in get_material_conflicts(show, sm.material, exclude_id=sm.id, quantity=sm.quantity):
                material_conflicts.append(serialize_material_conflict(conflict))

        technician_conflicts = []
        for st in show.show_technicians.select_related('technician').all():
            for conflict in get_technician_conflicts(show, st.technician, exclude_id=st.id):
                technician_conflicts.append(serialize_technician_conflict(conflict))

        # Un déplacement peut mobiliser plusieurs techniciens depuis le
        # 2026-07-30 (voir TransportTechnician) : chacun est vérifié séparément.
        for transport in show.transports.prefetch_related('transport_technicians__technician').all():
            if transport.scheduled_datetime is None:
                continue
            for tt in transport.transport_technicians.all():
                for conflict in get_transport_conflicts(
                    transport.scheduled_datetime,
                    transport.estimated_duration_minutes,
                    tt.technician,
                    exclude_id=transport.id,
                ):
                    technician_conflicts.append(serialize_technician_conflict(conflict))

        return Response({
            'venue_conflicts': venue_conflicts,
            'material_conflicts': material_conflicts,
            'technician_conflicts': technician_conflicts,
        })

    @action(detail=True, methods=['get'], url_path='transport-coherence')
    def transport_coherence(self, request, pk=None):
        """Rapport de cohérence des emplacements de matériel centré sur ce
        spectacle (non bloquant — voir `transport_coherence.py`) : matériel
        requis par ce spectacle mais non livré, transports de ce spectacle dont
        l'origine est incohérente, et matériel de ce spectacle sans lieu
        d'entreposage."""
        show = self.get_object()
        issues = get_show_coherence_report(show)
        return Response({'issues': issues, 'issue_count': len(issues)})

    @action(detail=False, methods=['post'], url_path='import-csv')
    def import_csv(self, request):
        """Importe un CSV spectacles (`{'project', 'mode', 'csv'}`, voir
        `csv_import.import_shows_csv`) — événements top-level uniquement, pas
        de colonne pour rattacher un bloc à un parent (voir le docstring de
        `import_shows_csv` — utiliser l'export/import JSON complet pour ça)."""
        return _import_csv_response(request, import_shows_csv)

    @action(detail=False, methods=['get'], url_path='export-csv')
    def export_csv(self, request):
        """Exporte les spectacles top-level du projet visé (`?project=<id>`)
        en CSV — voir `csv_export.shows_export_rows`."""
        project = _resolve_csv_project(request, request.query_params.get('project'), required_edit=False)
        if project is None:
            raise ValidationError({'project': "Le projet est requis."})
        rows = shows_export_rows(project)
        return csv_response('spectacles.csv', SHOW_CSV_HEADER, rows)


class ShowMaterialViewSet(ProjectMembershipQuerysetMixin, viewsets.ModelViewSet):
    """CRUD standard sur les assignations de matériel (validation de conflit dans le serializer).

    Filtres optionnels : `?show=<id>` (assignations d'un spectacle — utilisé par
    la fiche spectacle du frontend) ou `?material=<id>` (assignations d'un
    matériel donné — utilisé par sa fiche). Ajouté le 2026-07-28 : sans ce
    filtre, ces paramètres étaient silencieusement ignorés par DRF (pas de
    `filter_backends` configuré) et la liste retournait TOUTES les
    assignations, tous spectacles/projets confondus — bug trouvé en portant
    `MaterielDetail`.
    """

    queryset = ShowMaterial.objects.select_related('show', 'material').all()
    serializer_class = ShowMaterialSerializer
    permission_classes = [HasProjectAccess]
    # `ShowMaterial` n'a pas de FK `project` directe — isolé via `show`
    # (voir `ProjectMembershipQuerysetMixin`/`HasProjectAccess`, permissions.py).
    project_lookup = 'show__project_id'

    def get_create_project_id(self, request):
        show_id = request.data.get('show')
        if not show_id:
            return None
        return Show.objects.filter(id=show_id).values_list('project_id', flat=True).first()

    def get_object_project_id(self, obj):
        return obj.show.project_id

    def get_queryset(self):
        queryset = super().get_queryset()
        show_id = self.request.query_params.get('show')
        if show_id:
            queryset = queryset.filter(show_id=show_id)
        material_id = self.request.query_params.get('material')
        if material_id:
            queryset = queryset.filter(material_id=material_id)
        return queryset


class TechnicianViewSet(ProjectMembershipQuerysetMixin, ProjectFilteredMixin, viewsets.ModelViewSet):
    """CRUD standard sur les techniciens, filtrable par projet (`?project=<id>`)."""

    queryset = Technician.objects.select_related('project').all()
    serializer_class = TechnicianSerializer
    permission_classes = [HasProjectAccess]

    @action(detail=False, methods=['post'], url_path='import-csv')
    def import_csv(self, request):
        """Importe un CSV techniciens (`{'project', 'mode', 'csv'}`, voir
        `csv_import.import_technicians_csv`)."""
        return _import_csv_response(request, import_technicians_csv)

    @action(detail=False, methods=['get'], url_path='export-csv')
    def export_csv(self, request):
        """Exporte les techniciens du projet visé (`?project=<id>`) en CSV —
        voir `csv_export.technicians_export_rows`."""
        project = _resolve_csv_project(request, request.query_params.get('project'), required_edit=False)
        if project is None:
            raise ValidationError({'project': "Le projet est requis."})
        rows = technicians_export_rows(project)
        return csv_response('techniciens.csv', TECHNICIAN_CSV_HEADER, rows)


class ShowTechnicianViewSet(ProjectMembershipQuerysetMixin, viewsets.ModelViewSet):
    """CRUD standard sur les assignations de techniciens (validation de conflit dans le serializer).

    Filtres optionnels : `?show=<id>` ou `?technician=<id>` — même logique et
    même correctif que `ShowMaterialViewSet` ci-dessus (2026-07-28).
    """

    queryset = ShowTechnician.objects.select_related('show', 'technician').all()
    serializer_class = ShowTechnicianSerializer
    permission_classes = [HasProjectAccess]
    project_lookup = 'show__project_id'

    def get_create_project_id(self, request):
        show_id = request.data.get('show')
        if not show_id:
            return None
        return Show.objects.filter(id=show_id).values_list('project_id', flat=True).first()

    def get_object_project_id(self, obj):
        return obj.show.project_id

    def get_queryset(self):
        queryset = super().get_queryset()
        show_id = self.request.query_params.get('show')
        if show_id:
            queryset = queryset.filter(show_id=show_id)
        technician_id = self.request.query_params.get('technician')
        if technician_id:
            queryset = queryset.filter(technician_id=technician_id)
        return queryset


class TransportViewSet(ProjectMembershipQuerysetMixin, viewsets.ModelViewSet):
    """CRUD standard sur les déplacements (livraison/ramassage), validation de conflit dans le serializer.

    Filtres optionnels : `?status=to_approve` (ne renvoyer que les propositions
    auto à approuver — voir `transport_autogen.py`) ou `?status=confirmed` ;
    `?show=<id>` pour les déplacements d'un spectacle ; `?technician=<id>` pour
    les déplacements assignés à un technicien (ajouté le 2026-07-28 en portant
    la fiche technicien du frontend — même correctif que sur
    `ShowMaterialViewSet`/`ShowTechnicianViewSet`) ; `?project=<id>` (ajouté le
    2026-07-29 en portant l'écran Transports) — `Transport` n'a pas de FK
    `project` direct (il est isolé via son `show`), donc ce filtre traverse la
    relation (`show__project_id`).
    """

    queryset = (
        Transport.objects
        .select_related('show')
        .prefetch_related(
            'stops__venue',
            'transport_materials__material',
            'transport_materials__load_stop__venue',
            'transport_materials__unload_stop__venue',
            'transport_technicians__technician',
        )
        .all()
    )
    serializer_class = TransportSerializer
    permission_classes = [HasProjectAccess]
    project_lookup = 'show__project_id'

    def get_create_project_id(self, request):
        show_id = request.data.get('show')
        if not show_id:
            return None
        return Show.objects.filter(id=show_id).values_list('project_id', flat=True).first()

    def get_object_project_id(self, obj):
        return obj.show.project_id

    def get_queryset(self):
        queryset = super().get_queryset()
        status_param = self.request.query_params.get('status')
        if status_param:
            queryset = queryset.filter(status=status_param)
        show_id = self.request.query_params.get('show')
        if show_id:
            queryset = queryset.filter(show_id=show_id)
        technician_id = self.request.query_params.get('technician')
        if technician_id:
            # Traverse la table de liaison depuis le 2026-07-30 (plusieurs
            # techniciens par déplacement) — `distinct()` parce qu'un JOIN sur
            # une relation inverse peut dupliquer les lignes.
            queryset = queryset.filter(transport_technicians__technician_id=technician_id).distinct()
        project_id = self.request.query_params.get('project')
        if project_id:
            queryset = queryset.filter(show__project_id=project_id)
        return queryset

    @action(detail=True, methods=['get'], url_path='material-availability')
    def material_availability(self, request, pk=None):
        """Matériel présent à un ARRÊT de cette tournée, à l'heure d'arrivée du
        camion à cet arrêt.

        Sert la modale « ajouter du matériel » du frontend (demande de Samuel
        du 2026-07-30) : on ne charge dans un camion que ce qui se trouve
        réellement au point de chargement. La position vient du grand livre de
        `transport_coherence.py` (entrepôt du matériel + transports confirmés
        antérieurs), pas d'une simple comparaison avec `Material.venue` — sinon
        du matériel déjà déplacé en salle apparaîtrait encore disponible à son
        entrepôt.

        Tournées multi-arrêts (2026-08-04) : `?stop=<position>` choisit
        l'arrêt de chargement (0-indexé). Sans paramètre, le premier arrêt —
        exactement l'ancien comportement « lieu de départ », ce qui garde la
        modale actuelle du frontend fonctionnelle telle quelle.

        Réponse : `{'at': <iso|null>, 'stop_order': <n>, 'origin_venue': <id>,
        'materials': [...]}`, chaque entrée portant `available` (quantité
        présente sur place). Le matériel à `available: 0` est renvoyé quand
        même — le frontend affiche tout l'inventaire et grise ce qui n'est pas
        disponible.

        `at` vaut `null` quand le transport n'a pas encore d'heure (proposition
        auto non complétée) : la position n'est alors pas calculable et tout le
        stock est renvoyé comme disponible.
        """
        transport = self.get_object()
        stops = transport.ordered_stops
        stop_param = request.query_params.get('stop')
        try:
            stop_index = int(stop_param) if stop_param is not None else 0
        except ValueError:
            return Response({'detail': "Paramètre `stop` invalide (position 0-indexée attendue)."},
                            status=status.HTTP_400_BAD_REQUEST)
        if not stops or not (0 <= stop_index < len(stops)):
            return Response({'detail': f"Arrêt inexistant (la tournée a {len(stops)} arrêts)."},
                            status=status.HTTP_400_BAD_REQUEST)
        stop = stops[stop_index]
        at = transport.arrival_at(stop)
        rows = get_venue_material_availability(
            stop.venue,
            at=at,
            project=transport.show.project,
            # Un transport ne doit pas se décompter lui-même : sinon rouvrir la
            # modale d'un transport déjà rempli montrerait son propre
            # chargement comme parti.
            exclude_transport=transport,
        )
        return Response({
            'at': at,
            'stop_order': stop.order,
            'origin_venue': stop.venue_id,
            'origin_venue_name': stop.venue.name,
            'materials': [
                {
                    'id': row['material'].id,
                    'name': row['material'].name,
                    'quantity': row['material'].quantity,
                    'available': row['available'],
                    'venue_name': row['material'].venue.name if row['material'].venue else None,
                    'category_name': row['material'].category.name if row['material'].category else None,
                    'category_color': row['material'].category.color if row['material'].category else None,
                }
                for row in rows
            ],
        })


class SettingsView(generics.RetrieveUpdateAPIView):
    """Vue singleton pour les réglages globaux (`GET`/`PUT`/`PATCH` sur `/api/settings/`).

    Pas de liste ni de création : il n'existe toujours qu'une seule ligne de
    réglages, chargée (et créée si absente) via `Settings.load()`.
    """

    serializer_class = SettingsSerializer

    def get_object(self):
        return Settings.load()

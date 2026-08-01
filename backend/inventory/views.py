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

import unicodedata

from django.db import transaction
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
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
from .duplication import duplicate_project
from .transport_coherence import (
    get_material_journey,
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


class UserViewSet(viewsets.ModelViewSet):
    """CRUD standard sur les comptes applicatifs."""

    queryset = User.objects.all()
    serializer_class = UserSerializer


class ProjectViewSet(viewsets.ModelViewSet):
    """CRUD standard sur les productions — voir `Project` (models.py), plus
    l'action `duplicate` pour démarrer une nouvelle édition d'un mandat."""

    queryset = Project.objects.all()
    serializer_class = ProjectSerializer

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
                        'show_title': sm.show.title,
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
                    'label': st.show.title,
                    'venue_name': st.show.venue.name,
                    'start': st.show.effective_start,
                    'end': st.show.effective_end,
                    'conflict': ('show', st.id) in en_conflit,
                })
            for tt in (
                TransportTechnician.objects
                .filter(technician=technician, transport__show__project=project,
                        transport__scheduled_datetime__isnull=False)
                .select_related('transport', 'transport__origin_venue', 'transport__destination_venue')
            ):
                transport = tt.transport
                engagements.append({
                    'kind': 'transport',
                    'id': transport.id,
                    'label': f"{transport.origin_venue.name} → {transport.destination_venue.name}",
                    'venue_name': transport.destination_venue.name,
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


class VenueViewSet(ProjectFilteredMixin, viewsets.ModelViewSet):
    """CRUD standard sur les lieux, filtrable par projet (`?project=<id>`).

    Suppression (décision de Samuel du 2026-07-30) : **refusée** tant que le
    lieu est référencé. `Show.venue` et les deux FK de `Transport` sont en
    `PROTECT` — sans traitement, Django lèverait un `ProtectedError` que DRF
    rendrait en 500. On vérifie donc en amont pour renvoyer un 400 lisible,
    avec le décompte de ce qui bloque.

    `Material.venue` est en `SET_NULL` côté modèle, mais depuis que le lieu
    d'origine est obligatoire (2026-07-30) le laisser vider silencieusement le
    matériel contredirait la règle : le matériel entreposé bloque donc lui
    aussi la suppression.
    """

    queryset = Venue.objects.select_related('project').all()
    serializer_class = VenueSerializer

    def destroy(self, request, *args, **kwargs):
        """Supprime un lieu, sauf s'il est encore référencé quelque part."""
        venue = self.get_object()
        blocages = {
            'shows': venue.shows.count(),
            'transports': (
                Transport.objects.filter(origin_venue=venue).count()
                + Transport.objects.filter(destination_venue=venue).count()
            ),
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


class MaterialCategoryViewSet(ProjectFilteredMixin, viewsets.ModelViewSet):
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


class MaterialViewSet(ProjectFilteredMixin, viewsets.ModelViewSet):
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

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == 'list':
            include_inactive = self.request.query_params.get('include_inactive', '').lower() in (
                '1', 'true', 'yes',
            )
            if not include_inactive:
                queryset = queryset.filter(is_active=True)
        return queryset


class ShowViewSet(ProjectFilteredMixin, viewsets.ModelViewSet):
    """CRUD standard sur les fiches spectacles, filtrable par projet (`?project=<id>`),
    plus l'action `conflicts` en lecture seule."""

    queryset = Show.objects.select_related('project', 'venue').all()
    serializer_class = ShowSerializer

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


class ShowMaterialViewSet(viewsets.ModelViewSet):
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

    def get_queryset(self):
        queryset = super().get_queryset()
        show_id = self.request.query_params.get('show')
        if show_id:
            queryset = queryset.filter(show_id=show_id)
        material_id = self.request.query_params.get('material')
        if material_id:
            queryset = queryset.filter(material_id=material_id)
        return queryset


class TechnicianViewSet(ProjectFilteredMixin, viewsets.ModelViewSet):
    """CRUD standard sur les techniciens, filtrable par projet (`?project=<id>`)."""

    queryset = Technician.objects.select_related('project').all()
    serializer_class = TechnicianSerializer


class ShowTechnicianViewSet(viewsets.ModelViewSet):
    """CRUD standard sur les assignations de techniciens (validation de conflit dans le serializer).

    Filtres optionnels : `?show=<id>` ou `?technician=<id>` — même logique et
    même correctif que `ShowMaterialViewSet` ci-dessus (2026-07-28).
    """

    queryset = ShowTechnician.objects.select_related('show', 'technician').all()
    serializer_class = ShowTechnicianSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        show_id = self.request.query_params.get('show')
        if show_id:
            queryset = queryset.filter(show_id=show_id)
        technician_id = self.request.query_params.get('technician')
        if technician_id:
            queryset = queryset.filter(technician_id=technician_id)
        return queryset


class TransportViewSet(viewsets.ModelViewSet):
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
        .select_related('show', 'origin_venue', 'destination_venue')
        .prefetch_related('transport_materials__material', 'transport_technicians__technician')
        .all()
    )
    serializer_class = TransportSerializer

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
        """Matériel présent au lieu de DÉPART de ce transport, à son heure de départ.

        Sert la modale « ajouter du matériel » du frontend (demande de Samuel
        du 2026-07-30) : on ne charge dans un camion que ce qui se trouve
        réellement au point de départ. La position vient du grand livre de
        `transport_coherence.py` (entrepôt du matériel + transports confirmés
        antérieurs), pas d'une simple comparaison avec `Material.venue` — sinon
        du matériel déjà déplacé en salle apparaîtrait encore disponible à son
        entrepôt.

        Réponse : `{'at': <iso|null>, 'origin_venue': <id>, 'materials': [...]}`,
        chaque entrée portant `available` (quantité présente sur place). Le
        matériel à `available: 0` est renvoyé quand même — le frontend affiche
        tout l'inventaire et grise ce qui n'est pas disponible.

        `at` vaut `null` quand le transport n'a pas encore d'heure (proposition
        auto non complétée) : la position n'est alors pas calculable et tout le
        stock est renvoyé comme disponible.
        """
        transport = self.get_object()
        rows = get_venue_material_availability(
            transport.origin_venue,
            at=transport.scheduled_datetime,
            project=transport.show.project,
            # Un transport ne doit pas se décompter lui-même : sinon rouvrir la
            # modale d'un transport déjà rempli montrerait son propre
            # chargement comme parti.
            exclude_transport=transport,
        )
        return Response({
            'at': transport.scheduled_datetime,
            'origin_venue': transport.origin_venue_id,
            'origin_venue_name': transport.origin_venue.name,
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

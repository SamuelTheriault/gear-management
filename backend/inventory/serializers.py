"""
Serializers DRF — squelette API pour les tables de schema.md (8 tables initiales
+ `transports`, `settings` et `projects`, ajoutées respectivement le
2026-07-18 et le 2026-07-19).

La validation de conflit (voir conflicts.py) vit dans les serializers des
tables d'association/engagement (`ShowMaterialSerializer`,
`ShowTechnicianSerializer`, `TransportSerializer`) : bloquant par défaut, avec
possibilité de forcer via le champ `force` (décision prise avec Samuel le
2026-07-17 — voir recapitulatif_projet.md).

`TransportSerializer` pré-remplit aussi la durée de chaque segment de tournée
(`TransportStop.travel_minutes_from_previous`) via l'API Google Routes
(`inventory/maps.py`) quand le client ne la fournit pas explicitement et que
les deux lieux du segment ont des coordonnées GPS.

Isolation par projet (voir `Project` dans models.py) : `Venue`, `Material`,
`Technician` et `Show` portent chacun un FK `project` obligatoire. Le helper
`_same_project()` ci-dessous est utilisé dans les `validate()` concernés pour
bloquer tout mélange entre deux projets (ex. assigner du matériel du Projet A
à un spectacle du Projet B) — `Settings` reste global, non concerné par cette
vérification.
"""

from datetime import timedelta

from django.utils import timezone as django_timezone

from dj_rest_auth.serializers import UserDetailsSerializer
from rest_framework import serializers

from .conflicts import (
    get_material_conflicts,
    get_technician_conflicts,
    get_transport_conflicts,
    get_transport_reference_shows,
    get_truck_conflicts,
    get_venue_conflicts,
    serialize_material_conflict,
    serialize_reference_show,
    serialize_technician_conflict,
    serialize_truck_conflict,
    serialize_venue_conflict,
    validate_transport_window,
)
from .maps import estimate_travel, geocode_address

import logging as _logging

_geo_logger = _logging.getLogger('inventory.serializers.geocodage')
from .rich_text import clean_notes
from .models import (
    Material,
    MaterialCategory,
    Project,
    ProjectMembership,
    ReportShare,
    Settings,
    Show,
    ShowMaterial,
    ShowTechnician,
    Technician,
    Transport,
    TransportMaterial,
    TransportStop,
    TransportTechnician,
    Truck,
    User,
    Venue,
)


def _en_liste(serializer):
    """Sommes-nous en train de sérialiser une LISTE ?

    Sert à ne pas calculer, pour chaque ligne, des champs qui ne servent qu'en
    fiche (relecture du 2026-08-05 : `GET /transports/` montait à 245 requêtes
    pour 20 tournées, `GET /shows/` à 481). L'inversion est volontaire — on
    n'allège QUE la liste : sans vue dans le contexte (sérialisation manuelle,
    imbriquée, tests), le champ reste calculé, donc rien ne disparaît
    silencieusement d'un appelant qu'on n'aurait pas prévu.
    """
    view = serializer.context.get('view')
    return getattr(view, 'action', None) == 'list'


def _project_id_of(obj):
    """Id de projet d'un objet — l'objet peut être un `Project` lui-même (→ son
    propre id) ou tout modèle isolé par projet portant un FK `project` (→ son
    `project_id`). Voir `_same_project()`."""
    if obj is None:
        return None
    return obj.id if isinstance(obj, Project) else obj.project_id


def _same_project(*objects):
    """True si tous les objets non-None fournis appartiennent au même `Project`.

    Utilisé pour empêcher de mélanger des données de deux productions isolées
    (voir `Project` dans models.py) — ex. assigner du matériel du Projet A à un
    spectacle du Projet B. Accepte un mélange d'instances `Project` et
    d'objets portant un FK `project` (ex. `_same_project(project, venue)`).
    Ignore les objets None (champ optionnel non fourni).
    """
    project_ids = {_project_id_of(obj) for obj in objects if obj is not None}
    project_ids.discard(None)
    return len(project_ids) <= 1


class ProjectSerializer(serializers.ModelSerializer):
    """Sérialise les productions — voir `models.Project` pour la logique d'isolation."""

    # Décompte de ce qui disparaîtrait en cascade avec ce projet (2026-08-04,
    # voir la note « Suppression » sur `Project` — Venue/MaterialCategory/
    # Material/Show/Technician sont passés en CASCADE ce jour-là). `transports`
    # n'a pas de FK directe vers `project` (voir `Transport.show`), d'où le
    # passage par `show__project`.
    deletion_impact = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            'id', 'name', 'client_name', 'status', 'start_date', 'end_date', 'notes',
            'created_at', 'deletion_impact',
        ]
        read_only_fields = ['created_at']

    def get_deletion_impact(self, obj):
        return {
            'venues': obj.venues.count(),
            'materials': obj.materials.count(),
            'technicians': obj.technicians.count(),
            'shows': obj.shows.count(),
            'transports': Transport.objects.filter(project=obj).count(),
        }


class UserSerializer(serializers.ModelSerializer):
    """Sérialise les comptes applicatifs (voir `models.User`)."""

    class Meta:
        model = User
        fields = ['id', 'email', 'name', 'role', 'created_at']
        read_only_fields = ['created_at']


class CurrentUserDetailsSerializer(UserDetailsSerializer):
    """Étend le `/api/auth/user/` de dj-rest-auth (session courante) avec
    `is_staff_global` et l'id du profil `inventory.User` lié (2026-08-02).

    Sans ça, le frontend (voir `useAuth.js`) n'a aucun moyen de savoir si le
    compte connecté a l'accès de dépannage plateforme (`HasProjectAccess`,
    `permissions.py`) — nécessaire pour décider d'afficher les contrôles de
    gestion des accès d'un projet (inviter/retirer/changer un rôle) même sur
    un projet où ce compte n'a pas de `ProjectMembership` `owner`. `False`
    par défaut si le compte Django n'a pas (encore) de profil applicatif
    (`inventory_profile` absent — ex. superutilisateur créé hors du flux
    Google, voir `permissions.resolve_inventory_user`).
    """

    is_staff_global = serializers.SerializerMethodField()
    inventory_user_id = serializers.SerializerMethodField()

    class Meta(UserDetailsSerializer.Meta):
        fields = (*UserDetailsSerializer.Meta.fields, 'is_staff_global', 'inventory_user_id')

    def get_is_staff_global(self, obj):
        profile = getattr(obj, 'inventory_profile', None)
        return bool(profile and profile.is_staff_global)

    def get_inventory_user_id(self, obj):
        profile = getattr(obj, 'inventory_profile', None)
        return profile.id if profile else None


class ProjectMembershipSerializer(serializers.ModelSerializer):
    """Sérialise les accès par projet (voir `ProjectMembership`, models.py).

    Lecture seule pour `user`/`status`/`invited_by` : la création (invitation
    par email) et la modification (rôle, retrait) passent par des actions
    dédiées de `ProjectMembershipViewSet` qui ne s'appuient pas sur
    `.create()`/`.update()` de ce serializer (résolution d'un `User` par
    email, garde du dernier owner — voir `views.py`). Ce serializer ne sert
    donc qu'à représenter l'état d'un membership en lecture.
    """

    user_email = serializers.CharField(source='user.email', read_only=True)
    user_name = serializers.CharField(source='user.name', read_only=True)
    invited_by_email = serializers.CharField(source='invited_by.email', read_only=True, default=None)

    class Meta:
        model = ProjectMembership
        fields = [
            'id', 'project', 'user', 'user_email', 'user_name', 'role',
            'status', 'invited_by', 'invited_by_email', 'created_at',
        ]
        read_only_fields = ['user', 'status', 'invited_by', 'created_at']


class VenueSerializer(serializers.ModelSerializer):
    """Sérialise les lieux (salles, théâtres, sites de représentation, entrepôts), isolés par projet."""

    project_name = serializers.CharField(source='project.name', read_only=True)

    class Meta:
        model = Venue
        fields = [
            'id', 'project', 'project_name', 'name', 'code', 'address', 'contact_name', 'contact_info', 'notes',
            'is_storage', 'latitude', 'longitude', 'color', 'display_order',
        ]

    def validate_code(self, value):
        # Unicité par projet, pas en base : plusieurs lieux sans code (chaîne
        # vide) doivent pouvoir coexister normalement, ce qu'une contrainte
        # unique_together classique interdirait.
        value = value.strip()
        if not value:
            return value
        project = self.initial_data.get('project') or getattr(self.instance, 'project_id', None)
        if project is None:
            return value
        existing = Venue.objects.filter(project_id=project, code__iexact=value)
        if self.instance is not None:
            existing = existing.exclude(id=self.instance.id)
        if existing.exists():
            raise serializers.ValidationError(
                f'Le code "{value.upper()}" est déjà utilisé par un autre lieu de ce projet.',
            )
        return value

    def validate(self, attrs):
        """Géocodage automatique de l'adresse (2026-08-07, décision de
        Samuel) : les coordonnées GPS ne se saisissaient qu'à la main, donc
        la plupart des lieux n'en avaient pas — et durées, distances/km
        camion et suggestion d'ordre échouaient tous.

        Règles : on ne géocode que si l'utilisateur n'a PAS saisi de
        coordonnées lui-même (une saisie manuelle reste prioritaire), et
        seulement quand l'adresse change ou que les coordonnées sont vides —
        resauver une fiche intacte ne consomme pas d'appel Geocoding. Échec
        silencieux (clé absente, adresse introuvable) : la fiche
        s'enregistre sans coordonnées, comme avant ; le filet au vol de
        `maps._ensure_coordinates` retentera à la première estimation.

        « Saisi des coordonnées » se juge sur un CHANGEMENT DE VALEUR, pas
        sur la présence de la clé dans le payload (corrigé le 2026-08-07,
        retour de Samuel le jour même du merge) : la fiche Lieu du frontend
        renvoie TOUT son formulaire à chaque enregistrement —
        `latitude`/`longitude` sont donc toujours présents, à `null` quand
        les champs sont vides. Tester `'latitude' in attrs` bloquait
        silencieusement le géocodage sur exactement le flux recommandé
        (« ajoute une adresse à la fiche Lieu »). Corollaire assumé : des
        coordonnées RENVOYÉES TELLES QUELLES pendant que l'adresse change
        sont re-géocodées — les anciennes coordonnées décrivent l'ancienne
        adresse, les garder serait pire.
        """
        provided_lat = attrs.get('latitude')
        provided_lon = attrs.get('longitude')
        coords_typed = (provided_lat is not None or provided_lon is not None) and (
            self.instance is None
            or provided_lat != self.instance.latitude
            or provided_lon != self.instance.longitude
        )
        address = attrs.get('address', getattr(self.instance, 'address', '') if self.instance else '')
        address_changed = 'address' in attrs and (
            self.instance is None or attrs['address'] != self.instance.address
        )
        has_coords = (
            self.instance is not None
            and self.instance.latitude is not None
            and self.instance.longitude is not None
        )
        declenche = not coords_typed and bool(address.strip()) and (address_changed or not has_coords)
        _geo_logger.info(
            "Fiche Lieu %s : géocodage %s (coords_typed=%s, adresse=%s, address_changed=%s, has_coords=%s)",
            getattr(self.instance, 'id', 'nouvelle'),
            "déclenché" if declenche else "non déclenché",
            coords_typed, "oui" if address.strip() else "non", address_changed, has_coords,
        )
        if declenche:
            geocoded = geocode_address(address)
            if geocoded is not None:
                attrs['latitude'] = geocoded['latitude']
                attrs['longitude'] = geocoded['longitude']
        return attrs


class MaterialCategorySerializer(serializers.ModelSerializer):
    """Sérialise les catégories de matériel, isolées par projet (voir `MaterialCategory`).

    `material_count` est exposé pour que le frontend puisse prévenir avant une
    suppression (« 12 items utilisent cette catégorie ») et pré-remplir le
    choix de réassignation — voir `MaterialCategoryViewSet.destroy`.
    """

    project_name = serializers.CharField(source='project.name', read_only=True)
    material_count = serializers.SerializerMethodField()

    class Meta:
        model = MaterialCategory
        fields = ['id', 'project', 'project_name', 'name', 'color', 'material_count']

    def get_material_count(self, obj):
        """Nombre de matériels rattachés à cette catégorie (matériel inactif compris)."""
        return obj.materials.count()

    def validate_name(self, value):
        # La contrainte d'unicité est en base (project + name), mais un
        # IntegrityError donnerait un 500 : on valide donc en amont pour
        # renvoyer une erreur de champ exploitable par le formulaire.
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Le nom de la catégorie est requis.")
        project = self.initial_data.get('project') or getattr(self.instance, 'project_id', None)
        if project is None:
            return value
        existing = MaterialCategory.objects.filter(project_id=project, name__iexact=value)
        if self.instance is not None:
            existing = existing.exclude(id=self.instance.id)
        if existing.exists():
            raise serializers.ValidationError(
                f'La catégorie "{value}" existe déjà dans ce projet.',
            )
        return value


class MaterialSerializer(serializers.ModelSerializer):
    """Sérialise l'inventaire de matériel, isolé par projet, avec noms lisibles pour les FK
    (parent/venue/catégorie)."""

    project_name = serializers.CharField(source='project.name', read_only=True)
    parent_material_name = serializers.CharField(source='parent_material.name', read_only=True, default=None)
    venue_name = serializers.CharField(source='venue.name', read_only=True, default=None)
    # `category` est une FK depuis le 2026-07-30 (c'était un slug figé avant) :
    # le nom et la couleur sont dupliqués en lecture seule pour que le frontend
    # puisse afficher et colorer une liste sans requête supplémentaire.
    category_name = serializers.CharField(source='category.name', read_only=True, default=None)
    category_color = serializers.CharField(source='category.color', read_only=True, default=None)
    component_ids = serializers.PrimaryKeyRelatedField(source='components', many=True, read_only=True)
    # Décompte de ce qui disparaîtrait avec ce matériel (2026-08-04, même
    # esprit que `ShowSerializer.deletion_impact`) : `ShowMaterial`/
    # `TransportMaterial` sont en CASCADE — la suppression n'est PAS bloquée
    # même si le matériel a déjà servi (contrairement à `MaterialCategory`,
    # dont la FK reste `PROTECT`). `components` n'est PAS une perte : un
    # composant n'est que DÉTACHÉ (`parent_material` en `SET_NULL`), le
    # frontend l'annonce avec un libellé différent des deux autres.
    deletion_impact = serializers.SerializerMethodField()
    # Lieu d'origine OBLIGATOIRE depuis le 2026-07-30 (demande de Samuel) : sans
    # point de départ, la timeline de position (transport_coherence.py) ne peut
    # rien vérifier — ni la disponibilité au départ d'un transport, ni le retour
    # en fin de projet. Le champ reste nullable EN BASE pour ne pas invalider
    # l'historique déjà saisi ; c'est l'API qui l'exige désormais.
    venue = serializers.PrimaryKeyRelatedField(
        queryset=Venue.objects.all(),
        allow_null=False,
        required=True,
    )

    class Meta:
        model = Material
        fields = [
            'id', 'project', 'project_name', 'name', 'description',
            'category', 'category_name', 'category_color',
            'parent_material', 'parent_material_name', 'is_kit_parent',
            'venue', 'venue_name',
            'ownership_status', 'quantity', 'is_active', 'notes', 'component_ids',
            'deletion_impact',
        ]

    def get_deletion_impact(self, obj):
        return {
            'shows': obj.show_materials.count(),
            'transports': obj.transport_materials.count(),
            'components': obj.components.count(),
        }

    def validate_parent_material(self, value):
        if value is not None and self.instance is not None and value.id == self.instance.id:
            raise serializers.ValidationError("Un matériel ne peut pas être son propre parent.")
        if value is not None and value.quantity > 1:
            raise serializers.ValidationError(
                "Le matériel parent doit avoir une quantité de 1 — un kit ne peut "
                "pas lui-même être en plusieurs exemplaires."
            )
        # `is_kit_parent` (2026-08-02, demande de Samuel) : un matériel doit être
        # explicitement activé comme parent possible avant qu'un autre puisse le
        # choisir — limite ce que montre le sélecteur « Fait partie du kit » côté
        # frontend, et bloque ici toute tentative de contourner ce filtre par un
        # appel API direct.
        if value is not None and not value.is_kit_parent:
            raise serializers.ValidationError(
                "Ce matériel n'est pas activé comme parent de kit — coche "
                "« Peut être un parent (kit) » sur sa fiche d'abord."
            )
        return value

    def validate(self, attrs):
        # Un matériel de quantity > 1 (ex. 20 rallonges électriques) ne peut
        # pas faire partie d'une hiérarchie kit — voir Material.quantity et
        # conflicts.py, où la capacité partagée n'a de sens que pour un
        # matériel autonome, pas pour les membres d'un kit (toujours à
        # quantity=1). Décision prise avec Samuel le 2026-07-19.
        quantity = attrs.get('quantity', getattr(self.instance, 'quantity', 1))
        parent_material = attrs.get('parent_material', getattr(self.instance, 'parent_material', None))
        is_kit_parent = attrs.get('is_kit_parent', getattr(self.instance, 'is_kit_parent', False))

        if quantity > 1:
            if parent_material is not None:
                raise serializers.ValidationError({
                    'quantity': (
                        "Un matériel qui fait partie d'une hiérarchie kit "
                        "(parent_material renseigné) doit avoir une quantité de 1."
                    ),
                })
            if self.instance is not None and self.instance.components.exists():
                raise serializers.ValidationError({
                    'quantity': (
                        "Un matériel utilisé comme kit (qui a des composants) doit "
                        "avoir une quantité de 1."
                    ),
                })
            if is_kit_parent:
                raise serializers.ValidationError({
                    'is_kit_parent': (
                        "Un matériel en plusieurs exemplaires ne peut pas être un "
                        "parent de kit — la quantité doit être 1."
                    ),
                })

        # Isolation par projet (voir Project, models.py) : un matériel ne peut
        # référencer un parent ou un lieu d'entreposage que dans SON projet —
        # sinon deux productions isolées se retrouveraient mélangées.
        project = attrs.get('project', getattr(self.instance, 'project', None))
        venue = attrs.get('venue', getattr(self.instance, 'venue', None))
        if project is not None and parent_material is not None and not _same_project(project, parent_material):
            raise serializers.ValidationError({
                'parent_material': "Le matériel parent doit appartenir au même projet.",
            })
        if project is not None and venue is not None and not _same_project(project, venue):
            raise serializers.ValidationError({
                'venue': "Le lieu d'entreposage doit appartenir au même projet.",
            })
        category = attrs.get('category', getattr(self.instance, 'category', None))
        if project is not None and category is not None and not _same_project(project, category):
            raise serializers.ValidationError({
                'category': "La catégorie doit appartenir au même projet.",
            })
        return attrs

    def create(self, validated_data):
        instance = super().create(validated_data)
        if instance.parent_material_id:
            _mirror_parent_show_material_assignments(instance)
        return instance

    def update(self, instance, validated_data):
        # On ne mire les assignations que quand `parent_material` CHANGE vers
        # une nouvelle valeur — pas à chaque PATCH d'un composant déjà
        # rattaché (sinon retirer une assignation puis re-sauvegarder la
        # fiche la ferait réapparaître).
        previous_parent_id = instance.parent_material_id
        instance = super().update(instance, validated_data)
        if instance.parent_material_id and instance.parent_material_id != previous_parent_id:
            _mirror_parent_show_material_assignments(instance)
        return instance


def _mirror_parent_show_material_assignments(material):
    """Copie les assignations spectacle du parent sur un composant qui vient de
    lui être rattaché (création avec `parent_material` renseigné, ou
    rattachement ultérieur via le sélecteur « Fait partie du kit »).

    Décision prise avec Samuel le 2026-08-02 : si le kit est déjà assigné à un
    ou plusieurs spectacles au moment où on lui ajoute un composant, ce
    dernier doit suivre par défaut plutôt que de rester invisible tant que
    personne n'y pense — assignations complètes (pas seulement la position
    physique), toujours à quantity=1 (un composant reste une unité unique,
    voir Material.quantity). Ces `ShowMaterial` sont des lignes normales,
    éditables/retirables ensuite exactement comme n'importe quelle
    assignation existante (voir `SpectacleDetailView.vue`) — rien ne les
    distingue après coup. Passe par l'ORM directement (pas
    `ShowMaterialSerializer`) : les conflits que ça pourrait répliquer sont
    déjà ceux du parent (accepté ou forcé), pas de nouveaux — ils restent
    visibles et forçables comme d'habitude sur l'écran Conflits si le parent
    avait lui-même été forcé sur un chevauchement.
    """
    already_assigned_show_ids = set(
        ShowMaterial.objects.filter(material=material).values_list('show_id', flat=True)
    )
    parent_assignments = ShowMaterial.objects.filter(material_id=material.parent_material_id)
    for assignment in parent_assignments:
        if assignment.show_id in already_assigned_show_ids:
            continue
        ShowMaterial.objects.create(
            show_id=assignment.show_id,
            material=material,
            quantity=1,
            is_rental=assignment.is_rental,
            rental_vendor=assignment.rental_vendor,
        )


class ShowSerializer(serializers.ModelSerializer):
    """Sérialise les fiches spectacles, isolées par projet, en exposant la fenêtre
    effective calculée (buffers inclus).

    Blocs rattachés (2026-07-31, demande de Samuel) : `parent_show` permet
    d'accrocher un montage/une répétition en amont et un démontage en aval de
    l'événement principal. Un bloc est un `Show` complet — il a son lieu, ses
    horaires, son matériel, ses techniciens, et participe aux conflits comme
    tout le reste : c'était le but, ne rien réécrire en parallèle. Contraintes :
    un seul niveau de hiérarchie, même projet et même lieu que le parent.

    Validation de conflit de lieu (voir `conflicts.get_venue_conflicts`,
    décision du 2026-07-19) : deux spectacles ne peuvent pas se chevaucher
    dans le même lieu, indépendamment du matériel ou des techniciens assignés
    — bloquant par défaut, overridable via `force` (même pattern que les
    autres conflits)."""

    force = serializers.BooleanField(write_only=True, required=False, default=False)
    project_name = serializers.CharField(source='project.name', read_only=True)
    venue_name = serializers.CharField(source='venue.name', read_only=True)
    effective_start = serializers.DateTimeField(read_only=True)
    effective_end = serializers.DateTimeField(read_only=True)
    # Fenêtre d'ENGAGEMENT (2026-08-01) : contrairement à `effective_start`/
    # `effective_end` (le seul créneau de cet événement, buffers compris),
    # celle-ci s'étend au montage/démontage rattachés — voir
    # `Show.engagement_start`. Exposée pour que la fiche affiche la période
    # réellement mobilisée plutôt que le seul créneau de l'événement ; ne
    # remplace PAS effective_start/end, qui restent la référence pour le
    # conflit de LIEU (`get_venue_conflicts`).
    engagement_start = serializers.DateTimeField(read_only=True)
    engagement_end = serializers.DateTimeField(read_only=True)
    # Titre affiché (2026-08-02) : dynamique pour un bloc rattaché — voir
    # `Show.display_title`. `title`, lui, reste modifiable (nom complet pour
    # un événement, précision optionnelle pour un bloc) mais n'est plus ce
    # qu'il faut afficher tel quel dès qu'un bloc est en jeu.
    display_title = serializers.CharField(read_only=True)
    # Décompte de ce qui disparaîtrait avec le spectacle (2026-07-30) :
    # supprimer un `Show` supprime en cascade ses assignations ET ses
    # déplacements (FK en CASCADE). Le frontend l'annonce dans sa
    # confirmation plutôt que de laisser Samuel le découvrir après coup.
    deletion_impact = serializers.SerializerMethodField()
    # Blocs rattachés (montage/répétition en amont, démontage en aval —
    # 2026-07-31). Lecture seule et non récursif : un bloc ne peut pas lui-même
    # en avoir, la liste s'arrête donc à un niveau.
    phases = serializers.SerializerMethodField()
    parent_show_title = serializers.CharField(source='parent_show.title', read_only=True, default=None)
    # Noms des techniciens assignés, à plat (2026-08-05) — pour l'info-bulle
    # du Tableau de bord, qui les affichait déjà pour un déplacement mais pas
    # pour un événement. Sur un bloc qui HÉRITE (montage/démontage), ce sont
    # ceux de l'événement : il n'a pas d'assignation propre, mais c'est bien
    # cette équipe qui y travaille (voir `Show.inherits_resources`).
    technician_names = serializers.SerializerMethodField()

    class Meta:
        model = Show
        fields = [
            'id', 'project', 'project_name', 'title', 'display_title', 'venue', 'venue_name',
            'event_type', 'start_datetime', 'end_datetime',
            'buffer_before_minutes', 'buffer_after_minutes',
            'notes', 'effective_start', 'effective_end',
            'engagement_start', 'engagement_end', 'deletion_impact',
            'parent_show', 'parent_show_title', 'phases', 'technician_names', 'force',
        ]

    def get_technician_names(self, obj):
        """Noms des techniciens qui travaillent sur cet événement.

        `.all()` et non `.select_related(...)` : le second REFAIT une requête
        et contourne le `prefetch_related` du ViewSet, ce qui redonnait un
        appel par ligne de liste (relecture du 2026-08-05). Ce champ, lui,
        sert bien en liste — le Tableau de bord l'affiche dans ses
        info-bulles.
        """
        source = obj.parent_show if obj.inherits_resources else obj
        return [st.technician.name for st in source.show_technicians.all()]

    def get_phases(self, obj):
        """Blocs rattachés à cet événement, dans l'ordre chronologique.

        `None` en liste : chaque entrée porte son propre `deletion_impact`,
        donc plusieurs requêtes par bloc — et aucun écran de liste ne les
        affiche (seule la fiche le fait). Voir `_en_liste`.

        Renvoie une liste vide pour un bloc (pas de récursion) — la hiérarchie
        est volontairement limitée à un niveau.
        """
        if _en_liste(self):
            return None
        if obj.parent_show_id is not None:
            return []
        return [
            {
                'id': phase.id,
                # Titre dynamique (voir `Show.display_title`) — cette liste
                # n'est que de l'affichage en lecture seule, pas d'édition.
                'title': phase.display_title,
                'event_type': phase.event_type,
                'start_datetime': phase.start_datetime,
                'end_datetime': phase.end_datetime,
                'effective_start': phase.effective_start,
                'effective_end': phase.effective_end,
                'venue': phase.venue_id,
                'venue_name': phase.venue.name,
                # Un montage/démontage utilise les ressources de l'événement et
                # n'a donc rien à décompter. Un bloc de répétition est autonome
                # (2026-07-31) : le frontend affiche ses propres décomptes.
                'inherits_resources': phase.inherits_resources,
                # Ce que coûterait le retrait de ce bloc — la confirmation du
                # ✕ de la chronologie l'annonce (2026-08-05), comme celle de
                # l'entête le fait pour la fiche affichée.
                'deletion_impact': self.get_deletion_impact(phase),
                'material_count': (
                    None if phase.inherits_resources else phase.show_materials.count()
                ),
                'technician_count': (
                    None if phase.inherits_resources else phase.show_technicians.count()
                ),
            }
            for phase in obj.phases.select_related('venue').order_by('start_datetime')
        ]

    def validate_notes(self, value):
        """Assainit le HTML des notes — voir `rich_text.clean_notes`.

        À l'ÉCRITURE plutôt qu'à l'affichage : ce qui est en base est donc
        déjà propre, et un client qui passerait outre l'éditeur (PATCH direct)
        ne peut pas y déposer de script.
        """
        return clean_notes(value)

    def get_deletion_impact(self, obj):
        """Ce qui arriverait vraiment si ce spectacle était supprimé.

        `None` en liste : `plan_show_deletion` interroge les tournées une par
        une, et seule la fenêtre de confirmation d'une fiche s'en sert.

        `transports` ne compte que les déplacements qui DISPARAÎTRAIENT ;
        `transports_shortened` ceux qui survivraient, amputés de l'arrêt de ce
        lieu et du matériel qui y est manipulé (2026-08-05, voir
        `transport_detach.py`) ; `transports_detached` (2026-08-06) ceux qui
        survivraient SANS spectacle (aucun candidat de réancrage — `show`
        est devenu optionnel, migration 0028). Avant ces distinctions, la
        confirmation annonçait la suppression de tournées qui, en réalité,
        desservent aussi d'autres salles.
        """
        from .transport_detach import plan_show_deletion

        if _en_liste(self):
            return None
        supprimes, raccourcis, detachees = plan_show_deletion(obj)
        return {
            'materials': obj.show_materials.count(),
            'technicians': obj.show_technicians.count(),
            'transports': len(supprimes),
            'transports_shortened': len(raccourcis),
            'transports_detached': len(detachees),
        }

    def validate(self, attrs):
        force = attrs.pop('force', False)

        # Blocs rattachés (2026-07-31) : un seul niveau, même projet et même
        # lieu que l'événement principal — un montage se fait forcément là où
        # le spectacle a lieu.
        parent = attrs.get('parent_show', getattr(self.instance, 'parent_show', None))
        if parent is not None:
            if self.instance is not None and parent.id == self.instance.id:
                raise serializers.ValidationError({
                    'parent_show': "Un événement ne peut pas être rattaché à lui-même.",
                })
            if parent.parent_show_id is not None:
                raise serializers.ValidationError({
                    'parent_show': (
                        "Impossible de rattacher un bloc à un autre bloc — la "
                        "hiérarchie est limitée à un niveau."
                    ),
                })
            if self.instance is not None and self.instance.phases.exists():
                raise serializers.ValidationError({
                    'parent_show': (
                        "Cet événement a déjà des blocs rattachés : il ne peut pas "
                        "devenir lui-même un bloc."
                    ),
                })

        # `title` obligatoire seulement pour un événement top-level (2026-08-02) :
        # `Show.title` devient `blank=True` en base pour permettre à un bloc de
        # n'en porter aucun — voir `Show.display_title`, qui le calcule depuis
        # le titre COURANT de l'événement plutôt que d'en garder une copie
        # figée. Le champ modèle seul (`blank=True`) rendrait `title`
        # optionnel PARTOUT ; cette validation le garde requis là où il reste
        # le nom réel.
        if parent is None:
            title = attrs.get('title', getattr(self.instance, 'title', None))
            if not (title or '').strip():
                raise serializers.ValidationError({
                    'title': "Le titre est requis pour un événement (facultatif seulement sur un bloc rattaché).",
                })

        start = attrs.get('start_datetime', getattr(self.instance, 'start_datetime', None))
        end = attrs.get('end_datetime', getattr(self.instance, 'end_datetime', None))
        if start and end and end <= start:
            raise serializers.ValidationError({
                'end_datetime': "Doit être après start_datetime.",
            })

        # Isolation par projet (voir Project, models.py) : le lieu du spectacle
        # doit appartenir au même projet que le spectacle lui-même.
        project = attrs.get('project', getattr(self.instance, 'project', None))
        venue = attrs.get('venue', getattr(self.instance, 'venue', None))
        if parent is not None:
            if not _same_project(project, parent):
                raise serializers.ValidationError({
                    'parent_show': "Le bloc doit appartenir au même projet que son événement.",
                })
            if venue is not None and venue.id != parent.venue_id:
                raise serializers.ValidationError({
                    'venue': (
                        "Un bloc rattaché se déroule dans le même lieu que son "
                        f"événement (« {parent.venue.name} »)."
                    ),
                })
        if not _same_project(project, venue):
            raise serializers.ValidationError({
                'venue': "Le lieu doit appartenir au même projet que le spectacle.",
            })

        # Conflit de lieu : deux spectacles ne peuvent pas se chevaucher dans
        # le même venue. Les buffers non fournis explicitement retombent sur
        # le défaut Settings (à la création) ou la valeur déjà en base (à la
        # mise à jour), pour refléter fidèlement la fenêtre qui sera
        # réellement enregistrée.
        buffer_before = attrs.get('buffer_before_minutes', getattr(self.instance, 'buffer_before_minutes', None))
        if buffer_before is None:
            buffer_before = Settings.load().default_buffer_before_minutes
        buffer_after = attrs.get('buffer_after_minutes', getattr(self.instance, 'buffer_after_minutes', None))
        if buffer_after is None:
            buffer_after = Settings.load().default_buffer_after_minutes

        if venue and start and end and not force:
            effective_start = start - timedelta(minutes=buffer_before)
            effective_end = end + timedelta(minutes=buffer_after)
            exclude_id = self.instance.id if self.instance else None
            # Les blocs rattachés (montage/démontage) sont collés à leur
            # événement : on les exclut du contrôle de lieu (2026-07-31).
            famille = self.instance.family_ids if self.instance else None
            parent = attrs.get('parent_show', getattr(self.instance, 'parent_show', None))
            if famille is None and parent is not None:
                famille = parent.family_ids
            conflicts = get_venue_conflicts(
                venue, effective_start, effective_end,
                exclude_id=exclude_id, exclude_family_ids=famille,
            )
            if conflicts:
                raise serializers.ValidationError({
                    'conflicts': [serialize_venue_conflict(c) for c in conflicts],
                    'detail': (
                        "Chevauchement d'horaire détecté avec un autre spectacle dans le "
                        "même lieu. "
                        'Ajoute "force": true dans la requête pour forcer la création '
                        'malgré le conflit.'
                    ),
                })
        return attrs

    def create(self, validated_data):
        """Crée le spectacle — et amorce un bloc de répétition avec les
        ressources de son événement.

        Un montage ou un démontage n'a rien à recopier : il utilise en
        permanence le matériel et l'équipe de l'événement (fenêtre
        d'engagement, voir `Show.engagement_start`). Une répétition rattachée
        est autonome, mais part rarement de zéro — d'où cette copie de
        départ, demandée par Samuel le 2026-07-31, qu'on ajuste ensuite comme
        n'importe quelle assignation.

        La copie prend l'état des assignations à cet instant précis : ce qu'on
        ajoute à l'événement plus tard ne redescend pas dans le bloc. C'est le
        prix de l'autonomie — sans ça, éditer le bloc n'aurait pas de sens.

        Les lignes sont créées une à une (pas de `bulk_create`) pour que les
        signaux de `regenerate_signals.py` voient passer chaque assignation et
        régénèrent les propositions de transport.
        """
        show = super().create(validated_data)
        if show.parent_show_id is None or show.inherits_resources:
            return show

        parent = show.parent_show
        for sm in parent.show_materials.all():
            ShowMaterial.objects.create(
                show=show,
                material=sm.material,
                quantity=sm.quantity,
                is_rental=sm.is_rental,
                rental_vendor=sm.rental_vendor,
            )
        for st in parent.show_technicians.all():
            ShowTechnician.objects.create(show=show, technician=st.technician)
        return show


class ShowMaterialSerializer(serializers.ModelSerializer):
    """Sérialise l'assignation de matériel à un spectacle, avec validation de conflit bloquante (voir `force`)."""

    force = serializers.BooleanField(write_only=True, required=False, default=False)
    # `show` peut être une répétition rattachée, autonome (voir `validate`
    # ci-dessous) — `display_title` plutôt que `title` pour ne pas afficher
    # une précision de bloc sans son contexte (2026-08-02, voir `Show.display_title`).
    show_title = serializers.CharField(source='show.display_title', read_only=True)
    material_name = serializers.CharField(source='material.name', read_only=True)
    # Catégorie du matériel, dupliquée ici en lecture seule pour que le frontend puisse
    # colorer l'assignation sans requête supplémentaire (voir `Material.category` — a
    # remplacé `department_color`, retiré le 2026-07-29 avec le modèle `Department`).
    # `material_category` était le slug figé jusqu'au 2026-07-30 ; c'est
    # maintenant l'id de la catégorie, doublé de son nom et de sa couleur —
    # le frontend n'a plus de table de correspondance codée en dur.
    material_category = serializers.PrimaryKeyRelatedField(
        source='material.category', read_only=True, default=None,
    )
    material_category_name = serializers.CharField(
        source='material.category.name', read_only=True, default=None,
    )
    material_category_color = serializers.CharField(
        source='material.category.color', read_only=True, default=None,
    )

    class Meta:
        model = ShowMaterial
        fields = [
            'id', 'show', 'material', 'quantity', 'is_rental', 'rental_vendor',
            'show_title', 'material_name',
            'material_category', 'material_category_name', 'material_category_color',
            'force',
        ]

    def validate(self, attrs):
        force = attrs.pop('force', False)
        show = attrs.get('show', getattr(self.instance, 'show', None))
        material = attrs.get('material', getattr(self.instance, 'material', None))
        quantity = attrs.get('quantity', getattr(self.instance, 'quantity', 1))

        # Blocs de montage/démontage (2026-07-31) : ils utilisent le matériel
        # et l'équipe de l'événement principal. On refuse l'assignation directe
        # plutôt que de laisser coexister deux vérités — la fenêtre
        # d'engagement de l'événement les couvre déjà, voir
        # `Show.engagement_start`. Un bloc de RÉPÉTITION, lui, est autonome :
        # il reçoit une copie à sa création et s'ajuste ensuite librement.
        if show is not None and show.inherits_resources:
            raise serializers.ValidationError({
                'show': (
                    "Ce bloc utilise le matériel et l'équipe de son événement "
                    f"(« {show.parent_show.title} ») — fais l'assignation sur "
                    "l'événement, elle couvrira le montage et le démontage."
                ),
            })

        # Isolation par projet (voir Project, models.py) : impossible d'assigner
        # du matériel d'un projet à un spectacle d'un autre projet.
        if show and material and not _same_project(show, material):
            raise serializers.ValidationError({
                'material': "Ce matériel appartient à un autre projet que le spectacle.",
            })

        # Vérification indépendante de `force` : demander plus d'unités qu'on
        # en possède au total n'est pas un conflit d'horaire à arbitrer, c'est
        # une erreur de données — pas overridable.
        if material and quantity > material.quantity:
            raise serializers.ValidationError({
                'quantity': (
                    f"Quantité demandée ({quantity}) supérieure à la quantité "
                    f"totale possédée de ce matériel ({material.quantity})."
                ),
            })

        if show and material and not force:
            exclude_id = self.instance.id if self.instance else None
            conflicts = get_material_conflicts(show, material, exclude_id=exclude_id, quantity=quantity)
            if conflicts:
                raise serializers.ValidationError({
                    'conflicts': [serialize_material_conflict(c) for c in conflicts],
                    'detail': (
                        "Chevauchement d'horaire détecté : capacité insuffisante compte "
                        "tenu de la quantité déjà assignée sur cette période (ou conflit "
                        "avec un matériel parent/enfant lié). "
                        'Ajoute "force": true dans la requête pour forcer l\'assignation '
                        'malgré le conflit.'
                    ),
                })
        return attrs


class TechnicianSerializer(serializers.ModelSerializer):
    """Sérialise les techniciens disponibles pour assignation, isolés par projet."""

    project_name = serializers.CharField(source='project.name', read_only=True)
    # Décompte de ce qui disparaîtrait avec ce technicien (2026-08-04, même
    # esprit que `ShowSerializer.deletion_impact`) : `ShowTechnician`/
    # `TransportTechnician` sont en CASCADE — la suppression n'est PAS
    # bloquée même si déjà assigné par le passé.
    deletion_impact = serializers.SerializerMethodField()

    class Meta:
        model = Technician
        fields = [
            'id', 'project', 'project_name', 'name', 'contact_info', 'specialty', 'notes',
            'deletion_impact',
        ]

    def get_deletion_impact(self, obj):
        return {
            'shows': obj.show_technicians.count(),
            'transports': obj.transport_technicians.count(),
        }


class ShowTechnicianSerializer(serializers.ModelSerializer):
    """Sérialise l'assignation de techniciens à un spectacle, avec validation de conflit bloquante (voir `force`)."""

    force = serializers.BooleanField(write_only=True, required=False, default=False)
    # Même raison que `ShowMaterialSerializer.show_title` (2026-08-02).
    show_title = serializers.CharField(source='show.display_title', read_only=True)
    technician_name = serializers.CharField(source='technician.name', read_only=True)

    class Meta:
        model = ShowTechnician
        fields = ['id', 'show', 'technician', 'show_title', 'technician_name', 'force']

    def validate(self, attrs):
        force = attrs.pop('force', False)
        show = attrs.get('show', getattr(self.instance, 'show', None))
        technician = attrs.get('technician', getattr(self.instance, 'technician', None))

        # Blocs de montage/démontage (2026-07-31) : voir le commentaire
        # équivalent sur `ShowMaterialSerializer`. Un bloc de répétition est
        # autonome et accepte donc ses propres assignations.
        if show is not None and show.inherits_resources:
            raise serializers.ValidationError({
                'show': (
                    "Ce bloc utilise le matériel et l'équipe de son événement "
                    f"(« {show.parent_show.title} ») — fais l'assignation sur "
                    "l'événement, elle couvrira le montage et le démontage."
                ),
            })

        # Isolation par projet (voir Project, models.py) : impossible d'assigner
        # un technicien d'un projet à un spectacle d'un autre projet.
        if show and technician and not _same_project(show, technician):
            raise serializers.ValidationError({
                'technician': "Ce technicien appartient à un autre projet que le spectacle.",
            })

        if show and technician and not force:
            exclude_id = self.instance.id if self.instance else None
            conflicts = get_technician_conflicts(show, technician, exclude_id=exclude_id)
            if conflicts:
                raise serializers.ValidationError({
                    'conflicts': [serialize_technician_conflict(c) for c in conflicts],
                    'detail': (
                        "Chevauchement d'horaire détecté avec une ou plusieurs autres "
                        "assignations de ce technicien. "
                        'Ajoute "force": true dans la requête pour forcer l\'assignation '
                        'malgré le conflit.'
                    ),
                })
        return attrs


class TruckSerializer(serializers.ModelSerializer):
    """Sérialise un camion de production (voir `Truck`, models.py —
    chantier Camion du 2026-08-06).

    `estimated_km` : somme des distances des segments des tournées CONFIRMÉES
    du camion (« km estimé calculé selon les trajets Google Maps approuvés »,
    demande de Samuel), arrondie au dixième. `km_is_partial` signale des
    segments sans distance connue (lieux sans GPS, durée saisie à la main) —
    l'affichage doit alors dire « au moins X km ». `transport_count` sert à
    la garde de suppression côté frontend (PROTECT côté modèle).
    """

    project_name = serializers.CharField(source='project.name', read_only=True)
    estimated_km = serializers.SerializerMethodField()
    km_is_partial = serializers.SerializerMethodField()
    transport_count = serializers.SerializerMethodField()

    class Meta:
        model = Truck
        fields = [
            'id', 'project', 'project_name', 'name',
            'reservation_start', 'reservation_end',
            'reservation_number', 'contract_number', 'notes',
            'estimated_km', 'km_is_partial', 'transport_count',
        ]

    def validate_notes(self, value):
        """Assainit le HTML des notes — même règle que les autres fiches."""
        return clean_notes(value)

    def validate(self, attrs):
        """La période de réservation doit être dans le bon sens."""
        start = attrs.get('reservation_start', getattr(self.instance, 'reservation_start', None))
        end = attrs.get('reservation_end', getattr(self.instance, 'reservation_end', None))
        if start and end and end < start:
            raise serializers.ValidationError({
                'reservation_end': "Doit être après le début de la réservation.",
            })
        return attrs

    def get_estimated_km(self, obj):
        meters, _missing = obj.estimated_distance()
        return round(meters / 1000, 1)

    def get_km_is_partial(self, obj):
        _meters, missing = obj.estimated_distance()
        return missing > 0

    def get_transport_count(self, obj):
        return obj.transports.count()


class TransportStopSerializer(serializers.ModelSerializer):
    """Sérialise un arrêt de tournée (voir `TransportStop`, models.py —
    tournées multi-arrêts du 2026-08-04).

    Utilisée en écriture imbriquée dans `TransportSerializer.stops` : l'ordre
    d'un arrêt est sa POSITION dans la liste envoyée (`order` est dérivé,
    lecture seule), et `travel_minutes_from_previous` est optionnel — absent,
    le segment est estimé via Google Routes, sinon le défaut de `Settings`
    (voir `TransportSerializer.validate`). `arrival_datetime` (dérivée de
    l'heure de départ + le cumul des segments, voir `Transport.arrival_at`)
    est exposée pour afficher la séquence sans recalcul côté client.
    """

    venue_name = serializers.CharField(source='venue.name', read_only=True)
    venue_code = serializers.CharField(source='venue.code', read_only=True, default='')
    is_storage = serializers.BooleanField(source='venue.is_storage', read_only=True)
    arrival_datetime = serializers.DateTimeField(read_only=True)

    class Meta:
        model = TransportStop
        fields = [
            'id', 'venue', 'venue_name', 'venue_code', 'is_storage', 'order',
            'travel_minutes_from_previous', 'travel_distance_meters', 'arrival_datetime',
        ]
        extra_kwargs = {
            'order': {'read_only': True},
            'travel_minutes_from_previous': {'required': False},
            # La distance n'est jamais saisie : remplie par Google Routes en
            # même temps que la durée (2026-08-06, km estimé du camion).
            'travel_distance_meters': {'read_only': True},
        }


class TransportMaterialSerializer(serializers.ModelSerializer):
    """Sérialise une ligne « matériel transporté » d'un `Transport` (voir
    `TransportMaterial`, models.py). Utilisée en écriture imbriquée dans
    `TransportSerializer.materials` et exposée en lecture avec le nom du
    matériel pour l'affichage.

    Tournées multi-arrêts (2026-08-04) : chaque ligne porte sa PORTION de la
    séquence — `load_stop_order`/`unload_stop_order`, la position (0-indexée)
    des arrêts de chargement et de déchargement dans la tournée. À l'écriture
    ces deux champs sont optionnels : absents, la ligne couvre la tournée
    entière (chargement au premier arrêt, déchargement au dernier) — ce qui
    garde l'ancien contrat `{material, quantity}` fonctionnel tel quel.
    `source='load_stop.order'` fait la traversée en lecture ; en écriture la
    valeur arrive sous `{'load_stop': {'order': n}}` dans `validated_data`,
    dénormalisée par `TransportSerializer._normalized_material_lines`.
    """

    material_name = serializers.CharField(source='material.name', read_only=True)
    load_stop_order = serializers.IntegerField(source='load_stop.order', required=False, min_value=0)
    unload_stop_order = serializers.IntegerField(source='unload_stop.order', required=False, min_value=0)
    load_venue_name = serializers.CharField(source='load_stop.venue.name', read_only=True, default='')
    unload_venue_name = serializers.CharField(source='unload_stop.venue.name', read_only=True, default='')

    class Meta:
        model = TransportMaterial
        fields = [
            'id', 'material', 'material_name', 'quantity',
            'load_stop_order', 'unload_stop_order',
            'load_venue_name', 'unload_venue_name',
        ]


class TransportTechnicianSerializer(serializers.ModelSerializer):
    """Sérialise une affectation « technicien » d'un `Transport` (voir
    `TransportTechnician`, models.py — ajouté le 2026-07-30).

    Utilisée en écriture imbriquée dans `TransportSerializer.technicians`, sur
    le même modèle que `materials`, et exposée en lecture avec le nom du
    technicien pour l'affichage."""

    technician_name = serializers.CharField(source='technician.name', read_only=True)
    technician_specialty = serializers.CharField(
        source='technician.specialty', read_only=True, default='',
    )

    class Meta:
        model = TransportTechnician
        fields = ['id', 'technician', 'technician_name', 'technician_specialty']


class TransportSerializer(serializers.ModelSerializer):
    """Sérialise une tournée de matériel (séquence d'arrêts), avec validation
    de conflit bloquante sur les techniciens affectés (voir `force`).

    Chaque technicien affecté à un `Transport` est croisé avec ses engagements
    `ShowTechnician` ET ses autres déplacements — voir `conflicts.py`. Sa
    fenêtre d'engagement couvre toute la tournée (départ du premier arrêt →
    arrivée au dernier).

    **Arrêts** (`stops`, tournées multi-arrêts du 2026-08-04) : liste ordonnée
    de `{venue, travel_minutes_from_previous?}` — la position dans la liste
    fait foi (`order` est dérivé). Obligatoire à la création (≥ 2 arrêts),
    remplacement intégral de la séquence en mise à jour, inchangée si omise.
    Les arrêts existants sont mis à jour EN PLACE par position (mêmes ids) —
    les lignes de matériel qui pointent ces arrêts survivent à une simple
    retouche de lieu ou de durée. Une durée de segment absente est estimée
    via Google Routes (repli : défaut de `Settings`) ; en mise à jour, un
    segment dont le couple de lieux n'a pas changé garde sa durée actuelle
    (même règle que l'ancienne non-réestimation sur PATCH sans rapport).

    **Compat ancien contrat A → B** : `origin_venue`/`destination_venue`
    restent acceptés en écriture SANS `stops` — à la création, ils créent une
    tournée à 2 arrêts ; en mise à jour, ils retouchent le lieu du premier/
    dernier arrêt (sans toucher aux arrêts intermédiaires). En lecture, ce
    sont les lieux dérivés des premier/dernier arrêts.
    `estimated_duration_minutes` (lecture : durée TOTALE, somme des segments)
    n'est plus un champ éditable qu'au travers de ce chemin de compat — voir
    `validate` ; le glisser-redimensionner du Dashboard en dépend.

    Les techniciens sont gérés en écriture imbriquée via `technicians` (liste
    de `{technician}`) : depuis le 2026-07-30 un déplacement peut en mobiliser
    plusieurs. Fournir `technicians` lors d'une mise à jour remplace
    intégralement la liste ; l'omettre la laisse inchangée.

    Le matériel transporté est géré en écriture imbriquée via `materials`
    (liste de `{material, quantity, load_stop_order?, unload_stop_order?}`) —
    voir `TransportMaterialSerializer` et `transport_coherence.py`. Fournir
    `materials` lors d'une mise à jour remplace intégralement la liste des
    lignes du transport ; l'omettre la laisse inchangée.
    """

    force = serializers.BooleanField(write_only=True, required=False, default=False)
    stops = TransportStopSerializer(many=True, required=False)
    materials = TransportMaterialSerializer(many=True, source='transport_materials', required=False)
    technicians = TransportTechnicianSerializer(
        many=True, source='transport_technicians', required=False,
    )
    # `show` (« desservi » par ce transport — l'ARRIVÉE de la tournée) peut
    # être n'importe quel Show, blocs compris — `display_title` plutôt que
    # `title` (2026-08-02, voir `Show.display_title`). OPTIONNEL depuis le
    # 2026-08-06 (« Aucun spectacle » — retours d'entrepôt, logistique) :
    # `show_title` vaut alors None, et `project` (FK directe) porte seul
    # l'isolation par projet.
    show_title = serializers.CharField(source='show.display_title', read_only=True, default=None)
    # Lecture : lieux dérivés des premier/dernier arrêts (propriétés du
    # modèle). Écriture : chemin de compat ancien contrat — voir docstring.
    origin_venue = serializers.PrimaryKeyRelatedField(
        queryset=Venue.objects.all(), required=False, allow_null=True,
    )
    destination_venue = serializers.PrimaryKeyRelatedField(
        queryset=Venue.objects.all(), required=False, allow_null=True,
    )
    origin_venue_name = serializers.CharField(source='origin_venue.name', read_only=True, default='')
    destination_venue_name = serializers.CharField(source='destination_venue.name', read_only=True, default='')
    # Code court (voir Venue.code) pour un affichage compact départ/arrivée
    # (ex. "CHAP -> Salle principale") — vide si le lieu n'a pas de code.
    origin_venue_code = serializers.CharField(source='origin_venue.code', read_only=True, default='')
    destination_venue_code = serializers.CharField(source='destination_venue.code', read_only=True, default='')
    # Durée TOTALE de la tournée (somme des segments) — la clé garde son nom
    # historique pour le frontend (Dashboard, listes). Lecture seule : la
    # durée s'édite segment par segment via `stops` (ou via le chemin de
    # compat, voir `validate`).
    estimated_duration_minutes = serializers.IntegerField(
        source='total_duration_minutes', read_only=True,
    )
    # Camion (2026-08-06, chantier 2) : chaque tournée en a un — défaut à la
    # création = premier camion du projet (voir validate). Conflit d'horaire
    # entre tournées du même camion : bloquant + `force`, comme les
    # techniciens ; `truck_reservation_warning` est, lui, un simple
    # AVERTISSEMENT (tournée hors de la période de réservation).
    truck_name = serializers.CharField(source='truck.name', read_only=True, default='')
    has_truck_conflict = serializers.SerializerMethodField()
    truck_reservation_warning = serializers.SerializerMethodField()
    # Noms des techniciens affectés, à plat — évite au frontend de recomposer
    # la chaîne d'affichage à partir de `technicians` dans chaque liste.
    technician_names = serializers.SerializerMethodField()
    effective_end = serializers.DateTimeField(read_only=True)
    # Indicateur (orange) pour le frontend : ce déplacement met-il le technicien
    # assigné en conflit d'horaire (spectacle ou autre déplacement) ? La
    # détection de conflit reste bloquante à l'assignation (voir `validate` et
    # décision Samuel du 2026-07-24 : garder bloquant + exposer l'indicateur) ;
    # ce champ sert juste à colorer l'affichage, y compris pour les assignations
    # créées avec `force: true`.
    has_technician_conflict = serializers.SerializerMethodField()
    # Indicateur (lecture seule) : ce déplacement ne transporte aucun matériel.
    # Sert à signaler un « camion vide » côté frontend ; le contenu détaillé
    # reste visible via `materials`.
    is_empty = serializers.SerializerMethodField()
    # Spectacles de référence (départ/arrivée), déduits automatiquement — voir
    # `get_transport_reference_shows` (conflicts.py) et la note de module
    # 2026-07-30. `None` côté départ ou arrivée si ce bout est un entrepôt (ou
    # si aucun spectacle ne s'y trouve à proximité) : pas de borne ce côté-là.
    # Exposés pour affichage ET pour que le frontend propose par défaut
    # `departure_show.effective_end` comme heure de déplacement suggérée.
    departure_show = serializers.SerializerMethodField()
    arrival_show = serializers.SerializerMethodField()
    # Spectacles des lieux DESSERVIS par la tournée (2026-08-05, demande de
    # Samuel : « l'info Spectacle, on affiche tous les spectacles que le
    # transport touche »). `show` seul ne suffisait plus depuis les tournées
    # multi-arrêts : un déplacement peut passer par trois salles alors qu'il
    # n'a qu'un spectacle explicitement rattaché.
    #
    # Portée choisie avec Samuel : TOUS les spectacles qui se tiennent dans
    # les lieux visités, sur la fenêtre du projet — pas seulement ceux que le
    # transport dessert au sens strict (cette notion-là n'existe pas dans le
    # modèle pour un arrêt intermédiaire). C'est donc une liste de contexte,
    # volontairement large : à ne pas confondre avec `departure_show`/
    # `arrival_show`, qui bornent l'horaire et restent, eux, déduits.
    touched_shows = serializers.SerializerMethodField()

    class Meta:
        model = Transport
        # `project` : optionnel à l'écriture quand `show` est fourni (déduit
        # du spectacle et verrouillé sur lui) ; obligatoire pour une tournée
        # « sans spectacle » — voir validate().
        extra_kwargs = {'project': {'required': False}, 'truck': {'required': False}}
        fields = [
            'id', 'project', 'show', 'show_title', 'status', 'stops',
            'truck', 'truck_name', 'has_truck_conflict', 'truck_reservation_warning',
            'origin_venue', 'origin_venue_name', 'origin_venue_code',
            'destination_venue', 'destination_venue_name', 'destination_venue_code',
            'scheduled_datetime', 'estimated_duration_minutes', 'effective_end',
            'technicians', 'technician_names', 'has_technician_conflict',
            'materials', 'is_empty', 'departure_show', 'arrival_show',
            'touched_shows', 'notes', 'force',
        ]

    def validate_notes(self, value):
        """Assainit le HTML des notes — même règle que `ShowSerializer`."""
        return clean_notes(value)

    def get_technician_names(self, obj):
        """Noms des techniciens affectés, dans l'ordre de la table de liaison."""
        return [tt.technician.name for tt in obj.transport_technicians.all()]

    def get_is_empty(self, obj):
        """True si le déplacement ne transporte aucun matériel (aucune ligne
        `TransportMaterial`). Utilise le cache de prefetch quand disponible."""
        return len(obj.transport_materials.all()) == 0

    def get_touched_shows(self, obj):
        """Spectacles des lieux visités, groupés par lieu dans l'ordre des arrêts.

        `None` en liste : une requête par lieu visité, pour une information
        que seule la fiche affiche.

        Retourne `[{venue_id, venue_name, shows: [{id, title, start, end,
        event_type}]}]`. Un lieu qui revient à plusieurs arrêts (tournée
        aller-retour) n'apparaît qu'une fois.

        Ne remonte que les événements de premier niveau : un montage ou un
        démontage rattaché appartient déjà à l'événement listé, et les faire
        figurer tripleraient la liste sans rien apprendre. Les blocs restent
        consultables depuis la fiche du spectacle.

        Bornée à `get_project_window` — la même fenêtre que les Parcours, le
        Tableau de bord et les chronologies de fiche.
        """
        from .transport_coherence import get_project_window

        if _en_liste(self):
            return None
        arrets = list(obj.stops.select_related('venue').order_by('order'))
        if not arrets:
            return []
        window_start, window_end = get_project_window(obj.project)

        groupes = []
        deja_vus = set()
        for arret in arrets:
            if arret.venue_id in deja_vus:
                continue
            deja_vus.add(arret.venue_id)
            spectacles = Show.objects.filter(
                venue_id=arret.venue_id, parent_show__isnull=True,
            ).order_by('start_datetime')
            if window_start is not None:
                spectacles = spectacles.filter(
                    end_datetime__gte=window_start, start_datetime__lte=window_end,
                )
            groupes.append({
                'venue_id': arret.venue_id,
                'venue_name': arret.venue.name,
                'shows': [
                    {
                        'id': show.id,
                        'title': show.display_title,
                        'event_type': show.event_type,
                        'start': show.start_datetime,
                        'end': show.end_datetime,
                    }
                    for show in spectacles
                ],
            })
        return groupes

    def get_departure_show(self, obj):
        # `None` en liste : la déduction interroge les spectacles du lieu, une
        # requête par bout et par tournée. Seule la fiche les affiche —
        # TransportsView.vue refait la déduction côté client à partir des
        # spectacles déjà chargés (voir sa note de tête).
        if _en_liste(self):
            return None
        departure_show, _arrival_show = get_transport_reference_shows(
            obj.show, obj.origin_venue, obj.destination_venue,
        )
        return serialize_reference_show(departure_show)

    def get_arrival_show(self, obj):
        if _en_liste(self):
            return None
        _departure_show, arrival_show = get_transport_reference_shows(
            obj.show, obj.origin_venue, obj.destination_venue,
        )
        return serialize_reference_show(arrival_show)

    def get_has_truck_conflict(self, obj):
        """True si une autre tournée confirmée du même camion chevauche
        celle-ci — indicateur d'affichage, la validation bloquante vit dans
        `validate` (même pattern que `has_technician_conflict`).

        `None` en liste (budget de requêtes constant — voir
        `ListQueryBudgetTests`) : la vérification interroge les tournées du
        camion, une requête par ligne. Seule la fiche affiche cet indicateur ;
        l'écran Conflits passe par le rapport project-wide, déjà groupé."""
        if _en_liste(self):
            return None
        if obj.scheduled_datetime is None or obj.truck_id is None:
            return False
        return bool(get_truck_conflicts(
            obj.scheduled_datetime, obj.total_duration_minutes, obj.truck, exclude_id=obj.id,
        ))

    def get_truck_reservation_warning(self, obj):
        """Message si la tournée sort de la période de réservation du camion
        (bornes de dates inclusives), `None` sinon. Non bloquant — décision de
        Samuel : c'est un rappel logistique, pas une règle d'horaire."""
        truck = obj.truck if obj.truck_id is not None else None
        if truck is None or obj.scheduled_datetime is None:
            return None
        if truck.reservation_start is None and truck.reservation_end is None:
            return None
        depart = django_timezone.localdate(obj.scheduled_datetime)
        fin = django_timezone.localdate(obj.effective_end) if obj.effective_end else depart
        if truck.reservation_start and depart < truck.reservation_start:
            return (
                f"Cette tournée démarre avant la réservation du camion "
                f"« {truck.name} » ({truck.reservation_start:%Y-%m-%d})."
            )
        if truck.reservation_end and fin > truck.reservation_end:
            return (
                f"Cette tournée se termine après la fin de la réservation du camion "
                f"« {truck.name} » ({truck.reservation_end:%Y-%m-%d})."
            )
        return None

    def get_has_technician_conflict(self, obj):
        """True si AU MOINS UN des techniciens affectés est en conflit d'horaire
        sur ce déplacement (pour l'indicateur orange). False si aucun technicien
        ou pas d'heure (proposition non complétée)."""
        if obj.scheduled_datetime is None:
            return False
        return any(
            get_transport_conflicts(
                obj.scheduled_datetime,
                obj.total_duration_minutes,
                tt.technician,
                exclude_id=obj.id,
            )
            for tt in obj.transport_technicians.all()
        )

    def _plan_from_request(self, attrs, legacy_duration):
        """Résout la séquence d'arrêts visée par la requête.

        Retourne `(plan, dirty)` : `plan` est une liste de dicts
        `{'venue': Venue, 'travel': int|None}` (None = durée à estimer), et
        `dirty` indique si la séquence doit être resynchronisée en base
        (arrêts fournis, ou chemin de compat origin/destination). Trois cas :
        `stops` fourni (remplacement intégral), champs de compat fournis
        (création 2 arrêts / retouche premier-dernier arrêt), sinon la
        séquence actuelle telle quelle (aucune écriture).
        """
        stops_data = attrs.pop('stops', None)
        legacy_origin_given = 'origin_venue' in attrs
        legacy_destination_given = 'destination_venue' in attrs
        legacy_origin = attrs.pop('origin_venue', None)
        legacy_destination = attrs.pop('destination_venue', None)

        current_stops = list(self.instance.ordered_stops) if self.instance is not None else []

        if stops_data is not None:
            plan = [
                {'venue': s['venue'], 'travel': s.get('travel_minutes_from_previous'), 'distance': None}
                for s in stops_data
            ]
            return plan, True

        if legacy_origin_given or legacy_destination_given:
            if self.instance is None:
                if legacy_origin is None or legacy_destination is None:
                    raise serializers.ValidationError({
                        'stops': (
                            "Fournis la séquence d'arrêts (`stops`), ou les deux champs "
                            "origin_venue/destination_venue pour un simple A → B."
                        ),
                    })
                if legacy_origin.id == legacy_destination.id:
                    raise serializers.ValidationError({
                        'destination_venue': "Doit être différent du lieu de départ.",
                    })
                return (
                    [
                        {'venue': legacy_origin, 'travel': 0, 'distance': None},
                        {'venue': legacy_destination, 'travel': legacy_duration, 'distance': None},
                    ],
                    True,
                )
            # Mise à jour par le chemin de compat : on retouche le lieu du
            # premier/dernier arrêt, sans toucher aux arrêts intermédiaires.
            # Un segment dont le lieu change réellement voit sa durée remise à
            # None → réestimée par `_resolve_travel_times` (même règle que
            # l'ancienne réestimation sur changement d'origine/destination) ;
            # un lieu renvoyé identique (l'ancienne fiche renvoie tout le
            # formulaire) ne réestime rien.
            plan = [
                {'venue': s.venue, 'travel': s.travel_minutes_from_previous, 'distance': s.travel_distance_meters}
                for s in current_stops
            ]
            if plan:
                if (
                    legacy_origin_given and legacy_origin is not None
                    and legacy_origin.id != plan[0]['venue'].id
                ):
                    plan[0] = {'venue': legacy_origin, 'travel': 0, 'distance': None}
                    if len(plan) > 1:
                        plan[1] = {'venue': plan[1]['venue'], 'travel': None, 'distance': None}
                if (
                    legacy_destination_given and legacy_destination is not None
                    and legacy_destination.id != plan[-1]['venue'].id
                ):
                    plan[-1] = {'venue': legacy_destination, 'travel': None, 'distance': None}
            return plan, True

        plan = [
            {'venue': s.venue, 'travel': s.travel_minutes_from_previous, 'distance': s.travel_distance_meters}
            for s in current_stops
        ]
        return plan, False

    def _apply_legacy_duration(self, plan, legacy_duration, dirty):
        """Applique une durée totale envoyée par l'ancien contrat
        (`estimated_duration_minutes` en écriture, sans `stops`).

        Sur une tournée à 2 arrêts, c'est sans ambiguïté : la durée de
        l'unique segment. Au-delà, impossible de savoir quel segment ajuster —
        on refuse SEULEMENT si la valeur change réellement quelque chose, pour
        qu'un PATCH de l'ancien frontend qui renvoie la durée inchangée (sa
        fiche renvoie tout le formulaire) continue de passer.
        """
        if legacy_duration is None or not plan:
            return dirty
        if len(plan) == 2:
            if plan[1]['travel'] != legacy_duration:
                plan[1]['travel'] = legacy_duration
                return True
            return dirty
        known = [p['travel'] for p in plan if p['travel'] is not None]
        if len(known) == len(plan) and sum(known) == legacy_duration:
            return dirty
        raise serializers.ValidationError({
            'estimated_duration_minutes': (
                "Cette tournée a plus de 2 arrêts : la durée totale est la somme des "
                "segments — ajuste `travel_minutes_from_previous` arrêt par arrêt (liste `stops`)."
            ),
        })

    def _resolve_travel_times(self, plan, dirty):
        """Complète les durées (et distances) de segment manquantes du plan.

        Premier arrêt : toujours 0 (et pas de distance). Segment inchangé
        (même couple de lieux à la même position qu'avant) : garde sa durée
        ET sa distance actuelles — même règle que l'ancienne non-réestimation
        sur un PATCH sans rapport (revue de code du 2026-07-18). Sinon :
        estimation Google Routes (durée + distance dans le même appel, voir
        `maps.estimate_travel` — la distance alimente le km estimé du camion,
        2026-08-06), repli sur le défaut de `Settings` (durée seulement, la
        distance reste inconnue : `Truck.estimated_distance` la signale
        plutôt que de compter 0).
        """
        if not dirty:
            return
        current_stops = list(self.instance.ordered_stops) if self.instance is not None else []
        for i, p in enumerate(plan):
            if i == 0:
                p['travel'] = 0
                p['distance'] = None
                continue
            pair_unchanged = (
                i < len(current_stops)
                and current_stops[i - 1].venue_id == plan[i - 1]['venue'].id
                and current_stops[i].venue_id == p['venue'].id
            )
            if p['travel'] is not None:
                # Durée explicite : on la respecte (pause dîner, détour
                # prévu…). La distance, elle, ne dépend que des lieux : couple
                # inchangé → on garde celle en base ; couple changé sans
                # distance connue → un appel Routes remplit la distance SEULE
                # (les minutes de l'utilisateur restent intactes) — corrigé le
                # 2026-08-07 (chantier 3) : avant, ce cas laissait la distance
                # à NULL et trouait le km estimé du camion.
                if pair_unchanged:
                    p['distance'] = current_stops[i].travel_distance_meters
                elif p.get('distance') is None:
                    estimated = estimate_travel(plan[i - 1]['venue'], p['venue'])
                    p['distance'] = estimated['meters'] if estimated else None
                continue
            if pair_unchanged:
                p['travel'] = current_stops[i].travel_minutes_from_previous
                p['distance'] = current_stops[i].travel_distance_meters
                continue
            estimated = estimate_travel(plan[i - 1]['venue'], p['venue'])
            if estimated is None:
                p['travel'] = Settings.load().default_transport_duration_minutes
                p['distance'] = None
            else:
                p['travel'] = estimated['minutes']
                p['distance'] = estimated['meters']

    def _normalized_material_lines(self, material_lines, plan, project):
        """Valide et normalise les lignes de matériel en dicts
        `{'material', 'quantity', 'load': index, 'unload': index}`.

        Défauts (compat ancien contrat `{material, quantity}`) : chargement au
        premier arrêt, déchargement au dernier. La quantité est vérifiée PAR
        LIGNE contre le stock possédé — pas en somme par matériel : deux
        lignes du même matériel peuvent décrire un relais (A → B puis B → C)
        des mêmes unités physiques dans la même tournée, c'est le rapport de
        cohérence qui juge le réalisme spatial (voir transport_coherence.py).
        """
        plan_len = len(plan)
        normalized = []
        seen = set()
        for line in material_lines:
            material = line['material']
            if not _same_project(project, material):
                raise serializers.ValidationError({
                    'materials': f"Le matériel « {material.name} » appartient à un autre projet que le déplacement.",
                })
            load = (line.get('load_stop') or {}).get('order')
            unload = (line.get('unload_stop') or {}).get('order')
            if load is None:
                load = 0
            if unload is None:
                unload = plan_len - 1
            if load >= plan_len or unload >= plan_len:
                raise serializers.ValidationError({
                    'materials': (
                        f"« {material.name} » référence un arrêt inexistant "
                        f"(la tournée a {plan_len} arrêts, positions 0 à {plan_len - 1})."
                    ),
                })
            if load >= unload:
                raise serializers.ValidationError({
                    'materials': (
                        f"« {material.name} » : l'arrêt de chargement doit précéder "
                        "l'arrêt de déchargement dans la séquence."
                    ),
                })
            key = (material.id, load, unload)
            if key in seen:
                raise serializers.ValidationError({
                    'materials': (
                        f"Le matériel « {material.name} » est listé deux fois sur la même "
                        "portion de tournée — regroupe la quantité sur une seule ligne."
                    ),
                })
            seen.add(key)
            quantity = line.get('quantity', 1)
            if quantity > material.quantity:
                raise serializers.ValidationError({
                    'materials': (
                        f"Quantité transportée ({quantity}) supérieure à la quantité "
                        f"totale possédée de « {material.name} » ({material.quantity})."
                    ),
                })
            normalized.append({
                'material': material, 'quantity': quantity,
                'load': load, 'unload': unload,
            })
        return normalized

    def validate(self, attrs):
        show = attrs.get('show', getattr(self.instance, 'show', None))

        # Résolution du PROJET (2026-08-06, `show` optionnel — migration
        # 0028) : avec un spectacle, le projet est LE SIEN (fourni différent
        # → erreur, absent → déduit) ; sans spectacle, `project` devient
        # obligatoire — c'est lui qui porte l'isolation par projet.
        project = attrs.get('project', getattr(self.instance, 'project', None))
        if show is not None:
            if project is not None and project.id != show.project_id:
                raise serializers.ValidationError({
                    'project': "Doit être le projet du spectacle desservi (ou laisse le champ vide, il est déduit).",
                })
            project = show.project
        if project is None:
            raise serializers.ValidationError({
                'project': (
                    "Une tournée sans spectacle doit indiquer sa production "
                    "(champ `project`)."
                ),
            })
        attrs['project'] = project

        # Camion (2026-08-06) : défaut = premier camion du projet (chaque
        # projet en reçoit un à sa création — signals.creer_camion_par_defaut
        # et migration 0029), même projet exigé sinon.
        truck = attrs.get('truck', getattr(self.instance, 'truck', None))
        if truck is None:
            truck = project.trucks.order_by('id').first()
            if truck is None:
                raise serializers.ValidationError({
                    'truck': "Ce projet n'a aucun camion — crée-en un dans l'écran Camions.",
                })
        elif not _same_project(project, truck):
            raise serializers.ValidationError({
                'truck': f"Le camion « {truck.name} » appartient à un autre projet.",
            })
        attrs['truck'] = truck

        # Durée envoyée par l'ancien contrat (le champ déclaré est en lecture
        # seule — la valeur se lit dans le payload brut). Ignorée si `stops`
        # est fourni : la séquence fait foi.
        legacy_duration = None
        if (
            isinstance(self.initial_data, dict)
            and 'estimated_duration_minutes' in self.initial_data
            and 'stops' not in self.initial_data
            and self.initial_data['estimated_duration_minutes'] is not None
        ):
            try:
                legacy_duration = int(self.initial_data['estimated_duration_minutes'])
            except (TypeError, ValueError):
                raise serializers.ValidationError({
                    'estimated_duration_minutes': "Un nombre entier de minutes est attendu.",
                })
            # Le chemin moderne (`stops`) est protégé par le validateur
            # `min_value=0` généré pour `travel_minutes_from_previous`
            # (PositiveIntegerField) — ce chemin de compat écrit directement
            # dans le plan sans repasser par ce serializer, donc sans ce
            # garde-fou. Revue code-reviewer du 2026-08-04 : une valeur
            # négative passait silencieusement et corrompait `arrival_at`.
            if legacy_duration < 0:
                raise serializers.ValidationError({
                    'estimated_duration_minutes': "Doit être un nombre de minutes positif.",
                })

        plan, stops_dirty = self._plan_from_request(attrs, legacy_duration)

        if len(plan) < 2:
            raise serializers.ValidationError({
                'stops': (
                    "Une tournée doit avoir au moins 2 arrêts — fournis la liste `stops` "
                    "(ou origin_venue/destination_venue pour un simple A → B)."
                ),
            })

        stops_dirty = self._apply_legacy_duration(plan, legacy_duration, stops_dirty)

        # Deux arrêts consécutifs au même lieu n'ont pas de sens (un même lieu
        # peut en revanche revenir plus loin — tournée aller-retour).
        for prev, cur in zip(plan, plan[1:]):
            if prev['venue'].id == cur['venue'].id:
                raise serializers.ValidationError({
                    'stops': (
                        f"Deux arrêts consécutifs au même lieu (« {cur['venue'].name} ») — "
                        "retire l'un des deux."
                    ),
                })

        # Un déplacement confirmé doit avoir une heure. Une proposition
        # ('to_approve') peut rester sans heure tant qu'elle n'est pas complétée
        # — c'est justement ce qui la garde en orange (voir Transport.status).
        new_status = attrs.get('status', getattr(self.instance, 'status', Transport.STATUS_CONFIRMED))
        scheduled = attrs.get('scheduled_datetime', getattr(self.instance, 'scheduled_datetime', None))
        if new_status == Transport.STATUS_CONFIRMED and scheduled is None:
            raise serializers.ValidationError({
                'scheduled_datetime': "Obligatoire pour un déplacement confirmé (heure prévue du déplacement).",
            })

        # Isolation par projet (voir Project, models.py) : tous les lieux
        # d'arrêt et les techniciens/matériel fournis doivent appartenir au
        # même projet que la tournée — comparés à `project` (FK directe),
        # plus au spectacle, qui peut être absent (2026-08-06).
        for p in plan:
            if not _same_project(project, p['venue']):
                raise serializers.ValidationError(
                    "Les lieux d'un déplacement doivent tous appartenir au même projet que la tournée."
                )

        # Techniciens affectés (écriture imbriquée, plusieurs possibles depuis
        # le 2026-07-30) : même projet que le déplacement, et pas de doublon
        # dans la même requête (cf. unique_together).
        technician_lines = attrs.get('transport_technicians', None)
        if technician_lines is not None:
            seen_technician_ids = set()
            for line in technician_lines:
                technician = line['technician']
                if not _same_project(project, technician):
                    raise serializers.ValidationError({
                        'technicians': (
                            f"Le technicien « {technician.name} » appartient à un autre "
                            "projet que le déplacement."
                        ),
                    })
                if technician.id in seen_technician_ids:
                    raise serializers.ValidationError({
                        'technicians': f"Le technicien « {technician.name} » est listé deux fois.",
                    })
                seen_technician_ids.add(technician.id)

        # Complète les durées de segment manquantes (estimation Google Routes,
        # segment inchangé conservé, repli sur le défaut de Settings) — voir
        # `_resolve_travel_times`.
        self._resolve_travel_times(plan, stops_dirty)

        # Lignes de matériel transporté (écriture imbriquée) : validation et
        # normalisation vers des index d'arrêts — voir
        # `_normalized_material_lines`. La quantité par ligne ne peut pas
        # dépasser la quantité totale possédée (transporter 25 rallonges quand
        # on en possède 20 est une erreur de données, pas un arbitrage — non
        # overridable par `force`).
        material_lines = attrs.pop('transport_materials', None)
        if material_lines is not None:
            attrs['_material_lines'] = self._normalized_material_lines(material_lines, plan, project)
        elif self.instance is not None and stops_dirty:
            # La séquence change sans que les lignes soient refournies : les
            # lignes existantes doivent encore pointer des arrêts valides —
            # sinon la CASCADE de la FK les supprimerait en silence.
            for line in self.instance.transport_materials.select_related('load_stop', 'unload_stop'):
                if line.load_stop.order >= len(plan) or line.unload_stop.order >= len(plan):
                    raise serializers.ValidationError({
                        'stops': (
                            "Impossible de retirer un arrêt encore utilisé par une ligne de "
                            "matériel (chargement ou déchargement) — retire ou refournis "
                            "`materials` dans la même requête."
                        ),
                    })

        attrs['_stops_plan'] = plan
        attrs['_stops_dirty'] = stops_dirty

        force = attrs.pop('force', False)
        # Techniciens à vérifier : ceux fournis dans la requête si `technicians`
        # est présent, sinon ceux déjà affectés (un PATCH qui ne touche qu'aux
        # notes doit quand même revalider l'horaire s'il le change).
        if technician_lines is not None:
            technicians = [line['technician'] for line in technician_lines]
        elif self.instance is not None:
            technicians = [tt.technician for tt in self.instance.transport_technicians.all()]
        else:
            technicians = []
        scheduled_datetime = attrs.get('scheduled_datetime', getattr(self.instance, 'scheduled_datetime', None))
        # Durée totale de la tournée = somme des segments du plan résolu.
        duration = sum(p['travel'] or 0 for p in plan)

        if technicians and scheduled_datetime and duration and not force:
            exclude_id = self.instance.id if self.instance else None
            # Un seul bandeau d'erreur pour tout le déplacement, listant les
            # conflits de TOUS les techniciens affectés : côté frontend c'est
            # un seul bouton « Forcer », pas un par personne.
            conflicts = []
            for technician in technicians:
                conflicts.extend(
                    get_transport_conflicts(
                        scheduled_datetime, duration, technician, exclude_id=exclude_id,
                    )
                )
            if conflicts:
                raise serializers.ValidationError({
                    'conflicts': [serialize_technician_conflict(c) for c in conflicts],
                    'detail': (
                        "Chevauchement d'horaire détecté pour au moins un technicien "
                        "affecté (spectacle ou autre déplacement). "
                        'Ajoute "force": true dans la requête pour forcer l\'affectation '
                        'malgré le conflit.'
                    ),
                })

        # Conflit de CAMION (2026-08-06, décision de Samuel : même règle que
        # les techniciens) : le camion ne peut pas faire deux tournées qui se
        # chevauchent — bloquant + `force`, même bandeau côté frontend.
        if scheduled_datetime and duration and not force:
            exclude_id = self.instance.id if self.instance else None
            truck_overlaps = get_truck_conflicts(
                scheduled_datetime, duration, truck, exclude_id=exclude_id,
            )
            if truck_overlaps:
                raise serializers.ValidationError({
                    'conflicts': [serialize_truck_conflict(t) for t in truck_overlaps],
                    'detail': (
                        f"Le camion « {truck.name} » fait déjà une autre tournée sur cette "
                        'fenêtre. Ajoute "force": true dans la requête pour forcer malgré '
                        "le chevauchement."
                    ),
                })

        # Fenêtre départ/arrivée (décision Samuel du 2026-07-30, voir
        # conflicts.py) : la tournée doit avoir lieu entre la fin effective du
        # spectacle de départ (au PREMIER arrêt) et le début effectif du
        # spectacle d'arrivée (au DERNIER arrêt) — les arrêts intermédiaires
        # ne bornent rien. Même pattern bloquant + `force` que le conflit de
        # technicien ci-dessus.
        if show and not force:
            violation = validate_transport_window(
                show, plan[0]['venue'], plan[-1]['venue'], scheduled_datetime, duration,
            )
            if violation:
                raise serializers.ValidationError({
                    'detail': violation['detail'],
                    'departure_show': violation['departure_show'],
                    'arrival_show': violation['arrival_show'],
                })
        return attrs

    def _sync_stops(self, transport, plan):
        """Aligne les arrêts en base sur le plan résolu, EN PLACE par position :
        un arrêt existant garde son id (les lignes de matériel qui le pointent
        survivent), les positions en trop sont supprimées, les manquantes
        créées. Retourne la liste fraîche des arrêts, indexée par position."""
        existing = list(transport.stops.order_by('order'))
        for index, p in enumerate(plan):
            if index < len(existing):
                stop = existing[index]
                update_fields = []
                if stop.venue_id != p['venue'].id:
                    stop.venue = p['venue']
                    update_fields.append('venue')
                if stop.travel_minutes_from_previous != p['travel']:
                    stop.travel_minutes_from_previous = p['travel']
                    update_fields.append('travel_minutes_from_previous')
                if stop.travel_distance_meters != p.get('distance'):
                    stop.travel_distance_meters = p.get('distance')
                    update_fields.append('travel_distance_meters')
                if update_fields:
                    stop.save(update_fields=update_fields)
            else:
                existing.append(TransportStop.objects.create(
                    transport=transport, venue=p['venue'], order=index,
                    travel_minutes_from_previous=p['travel'],
                    travel_distance_meters=p.get('distance'),
                ))
        while len(existing) > len(plan):
            existing.pop().delete()
        return existing

    def create(self, validated_data):
        """Crée la tournée, puis ses arrêts, puis ses lignes de matériel et ses
        affectations de techniciens. Les clés privées `_stops_plan`/
        `_material_lines` (posées par `validate`) et les listes imbriquées
        sont retirées des données du modèle avant `super().create()`."""
        plan = validated_data.pop('_stops_plan')
        validated_data.pop('_stops_dirty', None)
        material_lines = validated_data.pop('_material_lines', [])
        technician_lines = validated_data.pop('transport_technicians', [])
        transport = super().create(validated_data)
        stops = [
            TransportStop.objects.create(
                transport=transport, venue=p['venue'], order=index,
                travel_minutes_from_previous=p['travel'],
                travel_distance_meters=p.get('distance'),
            )
            for index, p in enumerate(plan)
        ]
        for line in material_lines:
            TransportMaterial.objects.create(
                transport=transport, material=line['material'], quantity=line['quantity'],
                load_stop=stops[line['load']], unload_stop=stops[line['unload']],
            )
        for line in technician_lines:
            TransportTechnician.objects.create(transport=transport, **line)
        return transport

    def update(self, instance, validated_data):
        """Met à jour la tournée. Si `stops` (ou le chemin de compat) est
        fourni, resynchronise la séquence d'arrêts (voir `_sync_stops`) ; si
        `materials` est fourni, remplace intégralement les lignes — supprimées
        AVANT la resynchronisation des arrêts (une ligne ne doit jamais
        pointer un arrêt en cours de suppression), recréées après sur les
        arrêts frais. Omettre une liste la laisse inchangée (permet un PATCH
        qui ne touche qu'aux notes sans effacer le reste)."""
        plan = validated_data.pop('_stops_plan', None)
        stops_dirty = validated_data.pop('_stops_dirty', False)
        material_lines = validated_data.pop('_material_lines', None)
        technician_lines = validated_data.pop('transport_technicians', None)
        transport = super().update(instance, validated_data)

        if material_lines is not None:
            transport.transport_materials.all().delete()

        if stops_dirty and plan is not None:
            stops = self._sync_stops(transport, plan)
        else:
            stops = list(transport.stops.order_by('order'))

        if material_lines is not None:
            for line in material_lines:
                TransportMaterial.objects.create(
                    transport=transport, material=line['material'], quantity=line['quantity'],
                    load_stop=stops[line['load']], unload_stop=stops[line['unload']],
                )
        if technician_lines is not None:
            transport.transport_technicians.all().delete()
            for line in technician_lines:
                TransportTechnician.objects.create(transport=transport, **line)
        return transport


class SettingsSerializer(serializers.ModelSerializer):
    """Sérialise le singleton `Settings` (voir `views.SettingsView` — pas de liste ni de création).

    `event_type_order` est stocké en CSV côté modèle mais exposé comme une
    LISTE : c'est ce que le frontend manipule (glisser-déposer des lignes de
    réglages, puis puces de filtre dans le même ordre). La conversion vit ici
    plutôt que côté Vue, pour que la validation — pas de type inconnu, pas de
    doublon — soit faite une seule fois, au bon endroit.
    """

    event_type_order = serializers.ListField(
        child=serializers.ChoiceField(choices=Settings.EVENT_TYPE_ORDER_DEFAULT),
        required=False,
        allow_empty=False,
    )

    class Meta:
        model = Settings
        fields = [
            'default_buffer_before_minutes', 'default_buffer_after_minutes',
            'default_transport_duration_minutes', 'date_format', 'time_format',
            'transport_color', 'event_color_rehearsal', 'event_color_performance',
            'event_color_storage', 'event_color_setup', 'event_color_teardown',
            'event_type_order',
        ]

    def validate_event_type_order(self, value):
        """Refuse les doublons — un type ne peut pas occuper deux rangs.

        Une liste INCOMPLÈTE est acceptée : `Settings.event_type_order_list`
        rajoute les manquants à leur place canonique à la lecture. C'est
        volontaire, pour qu'un client qui ignore un futur 7e type ne l'efface
        pas en enregistrant l'ordre des six qu'il connaît.
        """
        if len(set(value)) != len(value):
            raise serializers.ValidationError("Un même type ne peut pas apparaître deux fois.")
        return value

    def to_representation(self, instance):
        """Renvoie l'ordre complet et assaini, jamais la chaîne CSV brute."""
        data = super().to_representation(instance)
        data['event_type_order'] = instance.event_type_order_list
        return data

    def update(self, instance, validated_data):
        ordre = validated_data.pop('event_type_order', None)
        if ordre is not None:
            instance.event_type_order = ','.join(ordre)
        return super().update(instance, validated_data)


class ReportShareSerializer(serializers.ModelSerializer):
    """Lien public d'une sortie de rapport — voir `ReportShare` (models.py).

    Le jeton et l'URL sont en lecture seule : on ne choisit pas son secret,
    et on ne le modifie pas non plus (voir la décision « un partage par cible,
    réutilisé » dans le docstring du modèle). Émettre un lien se fait par
    `POST` sur le ViewSet, qui délègue à `report_shares.get_or_create_share`
    et renvoie le partage existant s'il y en a déjà un actif.
    """

    url = serializers.SerializerMethodField()
    is_active = serializers.BooleanField(read_only=True)
    target_label = serializers.SerializerMethodField()

    class Meta:
        model = ReportShare
        fields = [
            'id', 'project', 'kind', 'token', 'url', 'is_active', 'target_label',
            'transport', 'show', 'technician', 'day',
            'created_by', 'created_at', 'expires_at', 'revoked_at',
            'last_accessed_at', 'access_count',
        ]
        read_only_fields = [
            'token', 'created_by', 'created_at', 'revoked_at',
            'last_accessed_at', 'access_count',
        ]

    def get_url(self, obj):
        from .report_shares import build_share_url
        request = self.context.get('request')
        try:
            return build_share_url(obj, request)
        except ValueError:
            # PUBLIC_BASE_URL absente ET pas de requête (ex. sérialisation
            # depuis un shell) : on renvoie le chemin relatif plutôt que de
            # faire échouer toute la réponse.
            return obj.path

    def get_target_label(self, obj):
        """Libellé lisible de la cible, pour la liste des liens émis côté
        réglages — sans quoi l'écran n'afficherait que des identifiants."""
        if obj.kind == ReportShare.KIND_TRANSPORT and obj.transport_id:
            return str(obj.transport)
        if obj.kind == ReportShare.KIND_SHOW and obj.show_id:
            return obj.show.display_title
        if obj.kind == ReportShare.KIND_TECHNICIAN and obj.technician_id:
            return obj.technician.name
        if obj.kind == ReportShare.KIND_DAY and obj.day:
            return obj.day.isoformat()
        return ''

    #: Champ cible attendu, et relation à remonter pour vérifier le projet.
    _CIBLES = {
        ReportShare.KIND_TRANSPORT: 'transport',
        ReportShare.KIND_SHOW: 'show',
        ReportShare.KIND_TECHNICIAN: 'technician',
        ReportShare.KIND_DAY: 'day',
    }

    def validate(self, attrs):
        """Une seule cible, cohérente avec `kind`, et dans le bon projet.

        La contrainte de base (`report_share_cible_coherente`) dit la même
        chose, mais elle remonterait en `IntegrityError` — donc en 500. On
        valide ici pour renvoyer une 400 exploitable.

        La vérification du projet est le vrai enjeu de sécurité : sans elle,
        un membre du projet A pourrait émettre un lien PUBLIC vers une
        tournée du projet B en postant simplement `{project: A, transport:
        <id de B>}`. `HasProjectAccess` ne l'attraperait pas — il ne
        contrôle que le champ `project` du corps de requête.
        """
        kind = attrs.get('kind') or getattr(self.instance, 'kind', None)
        if kind not in self._CIBLES:
            raise serializers.ValidationError({'kind': "Type de rapport inconnu."})

        attendu = self._CIBLES[kind]
        fournis = [
            champ for champ in self._CIBLES.values()
            if attrs.get(champ) is not None
        ]
        if fournis != [attendu]:
            raise serializers.ValidationError({
                attendu: (
                    f"Un partage de type « {dict(ReportShare.KIND_CHOICES)[kind]} » "
                    f"doit renseigner `{attendu}`, et lui seul."
                ),
            })

        project = attrs.get('project') or getattr(self.instance, 'project', None)
        cible = attrs.get(attendu)
        if attendu != 'day' and project is not None:
            cible_project_id = getattr(cible, 'project_id', None)
            if cible_project_id != project.id:
                raise serializers.ValidationError({
                    attendu: "Cette cible n'appartient pas au projet indiqué.",
                })
        return attrs

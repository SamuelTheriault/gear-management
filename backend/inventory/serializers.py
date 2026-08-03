"""
Serializers DRF — squelette API pour les tables de schema.md (8 tables initiales
+ `transports`, `settings` et `projects`, ajoutées respectivement le
2026-07-18 et le 2026-07-19).

La validation de conflit (voir conflicts.py) vit dans les serializers des
tables d'association/engagement (`ShowMaterialSerializer`,
`ShowTechnicianSerializer`, `TransportSerializer`) : bloquant par défaut, avec
possibilité de forcer via le champ `force` (décision prise avec Samuel le
2026-07-17 — voir recapitulatif_projet.md).

`TransportSerializer` pré-remplit aussi `estimated_duration_minutes` via
l'API Google Routes (`inventory/maps.py`) quand le client ne le fournit pas
explicitement et que les deux venues ont des coordonnées GPS.

Isolation par projet (voir `Project` dans models.py) : `Venue`, `Material`,
`Technician` et `Show` portent chacun un FK `project` obligatoire. Le helper
`_same_project()` ci-dessous est utilisé dans les `validate()` concernés pour
bloquer tout mélange entre deux projets (ex. assigner du matériel du Projet A
à un spectacle du Projet B) — `Settings` reste global, non concerné par cette
vérification.
"""

from datetime import timedelta

from dj_rest_auth.serializers import UserDetailsSerializer
from rest_framework import serializers

from .conflicts import (
    get_material_conflicts,
    get_technician_conflicts,
    get_transport_conflicts,
    get_transport_reference_shows,
    get_venue_conflicts,
    serialize_material_conflict,
    serialize_reference_show,
    serialize_technician_conflict,
    serialize_venue_conflict,
    validate_transport_window,
)
from .maps import estimate_travel_minutes
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
    TransportMaterial,
    TransportTechnician,
    User,
    Venue,
)


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

    class Meta:
        model = Project
        fields = ['id', 'name', 'client_name', 'status', 'start_date', 'end_date', 'notes', 'created_at']
        read_only_fields = ['created_at']


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
            'is_storage', 'latitude', 'longitude', 'color',
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
        ]

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

    class Meta:
        model = Show
        fields = [
            'id', 'project', 'project_name', 'title', 'display_title', 'venue', 'venue_name',
            'event_type', 'start_datetime', 'end_datetime',
            'buffer_before_minutes', 'buffer_after_minutes',
            'notes', 'effective_start', 'effective_end',
            'engagement_start', 'engagement_end', 'deletion_impact',
            'parent_show', 'parent_show_title', 'phases', 'force',
        ]

    def get_phases(self, obj):
        """Blocs rattachés à cet événement, dans l'ordre chronologique.

        Renvoie une liste vide pour un bloc (pas de récursion) — la hiérarchie
        est volontairement limitée à un niveau.
        """
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
                'material_count': (
                    None if phase.inherits_resources else phase.show_materials.count()
                ),
                'technician_count': (
                    None if phase.inherits_resources else phase.show_technicians.count()
                ),
            }
            for phase in obj.phases.select_related('venue').order_by('start_datetime')
        ]

    def get_deletion_impact(self, obj):
        """Ce qui serait supprimé en cascade avec ce spectacle."""
        return {
            'materials': obj.show_materials.count(),
            'technicians': obj.show_technicians.count(),
            'transports': obj.transports.count(),
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

    class Meta:
        model = Technician
        fields = ['id', 'project', 'project_name', 'name', 'contact_info', 'specialty', 'notes']


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


class TransportMaterialSerializer(serializers.ModelSerializer):
    """Sérialise une ligne « matériel transporté » d'un `Transport` (voir
    `TransportMaterial`, models.py). Utilisée en écriture imbriquée dans
    `TransportSerializer.materials` et exposée en lecture avec le nom du
    matériel pour l'affichage."""

    material_name = serializers.CharField(source='material.name', read_only=True)

    class Meta:
        model = TransportMaterial
        fields = ['id', 'material', 'material_name', 'quantity']


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
    """Sérialise un déplacement (livraison/ramassage) de matériel, avec
    validation de conflit bloquante sur les techniciens affectés (voir `force`).

    Chaque technicien affecté à un `Transport` est croisé avec ses engagements
    `ShowTechnician` ET ses autres déplacements — voir `conflicts.py`.

    Les techniciens sont gérés en écriture imbriquée via `technicians` (liste
    de `{technician}`), même pattern que `materials` : depuis le 2026-07-30 un
    déplacement peut en mobiliser plusieurs (l'ancien champ unique
    `Transport.technician` a disparu). Fournir `technicians` lors d'une mise à
    jour remplace intégralement la liste ; l'omettre la laisse inchangée.

    Le matériel transporté est géré en écriture imbriquée via `materials`
    (liste de `{material, quantity}`) — voir `TransportMaterial` et
    `transport_coherence.py`. Fournir `materials` lors d'une mise à jour
    remplace intégralement la liste des lignes du transport ; l'omettre la
    laisse inchangée.
    """

    force = serializers.BooleanField(write_only=True, required=False, default=False)
    materials = TransportMaterialSerializer(many=True, source='transport_materials', required=False)
    technicians = TransportTechnicianSerializer(
        many=True, source='transport_technicians', required=False,
    )
    # `show` (« desservi » par ce transport) peut être n'importe quel Show, blocs
    # compris — `display_title` plutôt que `title` (2026-08-02, voir `Show.display_title`).
    show_title = serializers.CharField(source='show.display_title', read_only=True)
    origin_venue_name = serializers.CharField(source='origin_venue.name', read_only=True)
    destination_venue_name = serializers.CharField(source='destination_venue.name', read_only=True)
    # Code court (voir Venue.code) pour un affichage compact départ/arrivée
    # (ex. "CHAP -> Salle principale") — vide si le lieu n'a pas de code.
    origin_venue_code = serializers.CharField(source='origin_venue.code', read_only=True, default='')
    destination_venue_code = serializers.CharField(source='destination_venue.code', read_only=True, default='')
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

    class Meta:
        model = Transport
        fields = [
            'id', 'show', 'show_title', 'transport_type', 'status',
            'origin_venue', 'origin_venue_name', 'origin_venue_code',
            'destination_venue', 'destination_venue_name', 'destination_venue_code',
            'scheduled_datetime', 'estimated_duration_minutes', 'effective_end',
            'technicians', 'technician_names', 'has_technician_conflict',
            'materials', 'is_empty', 'departure_show', 'arrival_show', 'notes', 'force',
        ]

    def get_technician_names(self, obj):
        """Noms des techniciens affectés, dans l'ordre de la table de liaison."""
        return [tt.technician.name for tt in obj.transport_technicians.all()]

    def get_is_empty(self, obj):
        """True si le déplacement ne transporte aucun matériel (aucune ligne
        `TransportMaterial`). Utilise le cache de prefetch quand disponible."""
        return len(obj.transport_materials.all()) == 0

    def get_departure_show(self, obj):
        departure_show, _arrival_show = get_transport_reference_shows(
            obj.show, obj.transport_type, obj.origin_venue, obj.destination_venue,
        )
        return serialize_reference_show(departure_show)

    def get_arrival_show(self, obj):
        _departure_show, arrival_show = get_transport_reference_shows(
            obj.show, obj.transport_type, obj.origin_venue, obj.destination_venue,
        )
        return serialize_reference_show(arrival_show)

    def get_has_technician_conflict(self, obj):
        """True si AU MOINS UN des techniciens affectés est en conflit d'horaire
        sur ce déplacement (pour l'indicateur orange). False si aucun technicien
        ou pas d'heure (proposition non complétée)."""
        if obj.scheduled_datetime is None:
            return False
        return any(
            get_transport_conflicts(
                obj.scheduled_datetime,
                obj.estimated_duration_minutes,
                tt.technician,
                exclude_id=obj.id,
            )
            for tt in obj.transport_technicians.all()
        )

    def validate(self, attrs):
        origin = attrs.get('origin_venue', getattr(self.instance, 'origin_venue', None))
        destination = attrs.get('destination_venue', getattr(self.instance, 'destination_venue', None))
        if origin and destination and origin.id == destination.id:
            raise serializers.ValidationError({
                'destination_venue': "Doit être différent du lieu de départ.",
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

        # Isolation par projet (voir Project, models.py) : le spectacle, les
        # deux lieux et le technicien (si fourni) doivent tous appartenir au
        # même projet.
        show = attrs.get('show', getattr(self.instance, 'show', None))
        if not _same_project(show, origin, destination):
            raise serializers.ValidationError(
                "Le spectacle et les lieux d'un déplacement doivent tous appartenir au même projet."
            )

        # Techniciens affectés (écriture imbriquée, plusieurs possibles depuis
        # le 2026-07-30) : même projet que le déplacement, et pas de doublon
        # dans la même requête (cf. unique_together).
        technician_lines = attrs.get('transport_technicians', None)
        if technician_lines is not None:
            seen_technician_ids = set()
            for line in technician_lines:
                technician = line['technician']
                if show is not None and not _same_project(show, technician):
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

        # Lignes de matériel transporté (écriture imbriquée) : chaque matériel
        # doit appartenir au même projet que le spectacle, ne pas apparaître en
        # double dans la même requête (une seule ligne par matériel, cf.
        # unique_together), et ne pas dépasser la quantité totale possédée
        # (transporter 25 rallonges quand on en possède 20 est une erreur de
        # données, pas un arbitrage — non overridable par `force`).
        material_lines = attrs.get('transport_materials', None)
        if material_lines is not None:
            seen_material_ids = set()
            for line in material_lines:
                material = line['material']
                if show is not None and not _same_project(show, material):
                    raise serializers.ValidationError({
                        'materials': f"Le matériel « {material.name} » appartient à un autre projet que le déplacement.",
                    })
                if material.id in seen_material_ids:
                    raise serializers.ValidationError({
                        'materials': f"Le matériel « {material.name} » est listé deux fois — regroupe la quantité sur une seule ligne.",
                    })
                seen_material_ids.add(material.id)
                if line.get('quantity', 1) > material.quantity:
                    raise serializers.ValidationError({
                        'materials': (
                            f"Quantité transportée ({line['quantity']}) supérieure à la quantité "
                            f"totale possédée de « {material.name} » ({material.quantity})."
                        ),
                    })

        # Auto-estimation via Google Routes : seulement si le client n'a pas
        # explicitement fourni de durée, et que les deux venues ont des
        # coordonnées GPS. Sinon estimate_travel_minutes renvoie None et on
        # garde la valeur déjà présente dans attrs (fournie par le client, ou
        # le défaut Settings.default_transport_duration_minutes appliqué par
        # le champ du modèle).
        #
        # À la création (self.instance is None) : on estime dès que le client
        # ne fournit pas de durée explicite.
        # À la mise à jour (PATCH/PUT) : on ne réestime QUE si l'origine ou la
        # destination a réellement changé dans cette requête — sinon un PATCH
        # qui ne touche ni au trajet ni à la durée (ex. changer `notes` ou
        # `technician`) écraserait silencieusement une durée déjà correcte
        # (éventuellement corrigée à la main) par un nouvel appel réseau à
        # chaque édition. Trouvé en revue de code (2026-07-18) avant le merge.
        no_explicit_duration = 'estimated_duration_minutes' not in self.initial_data
        if self.instance is None:
            should_estimate = no_explicit_duration
        else:
            origin_changed = (
                'origin_venue' in self.initial_data and origin and origin.id != self.instance.origin_venue_id
            )
            destination_changed = (
                'destination_venue' in self.initial_data
                and destination and destination.id != self.instance.destination_venue_id
            )
            should_estimate = no_explicit_duration and (origin_changed or destination_changed)

        if should_estimate and origin and destination:
            estimated = estimate_travel_minutes(origin, destination)
            if estimated is not None:
                attrs['estimated_duration_minutes'] = estimated

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
        duration = attrs.get(
            'estimated_duration_minutes',
            getattr(self.instance, 'estimated_duration_minutes', None),
        )

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

        # Fenêtre départ/arrivée (décision Samuel du 2026-07-30, voir
        # conflicts.py) : le déplacement doit avoir lieu entre la fin
        # effective du spectacle de départ et le début effectif du spectacle
        # d'arrivée (déduits automatiquement — voir `get_transport_reference_shows`).
        # Même pattern bloquant + `force` que le conflit de technicien ci-dessus.
        transport_type = attrs.get('transport_type', getattr(self.instance, 'transport_type', None))
        if show and origin and destination and not force:
            violation = validate_transport_window(
                show, transport_type, origin, destination, scheduled_datetime, duration,
            )
            if violation:
                raise serializers.ValidationError({
                    'detail': violation['detail'],
                    'departure_show': violation['departure_show'],
                    'arrival_show': violation['arrival_show'],
                })
        return attrs

    def create(self, validated_data):
        """Crée le déplacement puis ses lignes de matériel transporté (le cas
        échéant). `transport_materials` est retiré des données du modèle avant
        `super().create()` car ce sont des lignes d'une table liée, pas des
        champs de `Transport`."""
        material_lines = validated_data.pop('transport_materials', [])
        technician_lines = validated_data.pop('transport_technicians', [])
        transport = super().create(validated_data)
        for line in material_lines:
            TransportMaterial.objects.create(transport=transport, **line)
        for line in technician_lines:
            TransportTechnician.objects.create(transport=transport, **line)
        return transport

    def update(self, instance, validated_data):
        """Met à jour le déplacement. Si `materials` est fourni, remplace
        intégralement les lignes de matériel transporté ; s'il est absent, les
        laisse inchangées (permet un PATCH qui ne touche qu'aux notes ou au
        technicien sans effacer la liste)."""
        material_lines = validated_data.pop('transport_materials', None)
        technician_lines = validated_data.pop('transport_technicians', None)
        transport = super().update(instance, validated_data)
        if material_lines is not None:
            transport.transport_materials.all().delete()
            for line in material_lines:
                TransportMaterial.objects.create(transport=transport, **line)
        if technician_lines is not None:
            transport.transport_technicians.all().delete()
            for line in technician_lines:
                TransportTechnician.objects.create(transport=transport, **line)
        return transport


class SettingsSerializer(serializers.ModelSerializer):
    """Sérialise le singleton `Settings` (voir `views.SettingsView` — pas de liste ni de création)."""

    class Meta:
        model = Settings
        fields = [
            'default_buffer_before_minutes', 'default_buffer_after_minutes',
            'default_transport_duration_minutes', 'date_format', 'time_format',
            'transport_color', 'event_color_rehearsal', 'event_color_performance',
            'event_color_storage', 'event_color_setup', 'event_color_teardown',
        ]

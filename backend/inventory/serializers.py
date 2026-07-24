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
à un spectacle du Projet B) — `Department` et `Settings` restent globaux, non
concernés par cette vérification.
"""

from rest_framework import serializers

from .conflicts import (
    get_material_conflicts,
    get_technician_conflicts,
    get_transport_conflicts,
    serialize_material_conflict,
    serialize_technician_conflict,
)
from .maps import estimate_travel_minutes
from .models import (
    Department,
    Material,
    Project,
    Settings,
    Show,
    ShowMaterial,
    ShowTechnician,
    Technician,
    Transport,
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


class VenueSerializer(serializers.ModelSerializer):
    """Sérialise les lieux (salles, théâtres, sites de représentation, entrepôts), isolés par projet."""

    project_name = serializers.CharField(source='project.name', read_only=True)

    class Meta:
        model = Venue
        fields = [
            'id', 'project', 'project_name', 'name', 'code', 'address', 'contact_name', 'contact_info', 'notes',
            'is_storage', 'latitude', 'longitude',
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


class DepartmentSerializer(serializers.ModelSerializer):
    """Sérialise les départements responsables du matériel, couleur d'identification incluse."""

    class Meta:
        model = Department
        fields = ['id', 'name', 'contact_name', 'contact_info', 'notes', 'color']


class MaterialSerializer(serializers.ModelSerializer):
    """Sérialise l'inventaire de matériel, isolé par projet, avec noms lisibles pour les FK
    (parent/venue/département)."""

    project_name = serializers.CharField(source='project.name', read_only=True)
    parent_material_name = serializers.CharField(source='parent_material.name', read_only=True, default=None)
    venue_name = serializers.CharField(source='venue.name', read_only=True, default=None)
    department_name = serializers.CharField(source='department.name', read_only=True, default=None)
    # Couleur du département, dupliquée ici en lecture seule pour que le frontend puisse
    # colorer le matériel sans requête supplémentaire (voir `Department.color`).
    department_color = serializers.CharField(source='department.color', read_only=True, default=None)
    component_ids = serializers.PrimaryKeyRelatedField(source='components', many=True, read_only=True)

    class Meta:
        model = Material
        fields = [
            'id', 'project', 'project_name', 'name', 'description', 'category',
            'parent_material', 'parent_material_name',
            'venue', 'venue_name',
            'department', 'department_name', 'department_color',
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
        return value

    def validate(self, attrs):
        # Un matériel de quantity > 1 (ex. 20 rallonges électriques) ne peut
        # pas faire partie d'une hiérarchie kit — voir Material.quantity et
        # conflicts.py, où la capacité partagée n'a de sens que pour un
        # matériel autonome, pas pour les membres d'un kit (toujours à
        # quantity=1). Décision prise avec Samuel le 2026-07-19.
        quantity = attrs.get('quantity', getattr(self.instance, 'quantity', 1))
        parent_material = attrs.get('parent_material', getattr(self.instance, 'parent_material', None))

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
        return attrs


class ShowSerializer(serializers.ModelSerializer):
    """Sérialise les fiches spectacles, isolées par projet, en exposant la fenêtre
    effective calculée (buffers inclus)."""

    project_name = serializers.CharField(source='project.name', read_only=True)
    venue_name = serializers.CharField(source='venue.name', read_only=True)
    effective_start = serializers.DateTimeField(read_only=True)
    effective_end = serializers.DateTimeField(read_only=True)

    class Meta:
        model = Show
        fields = [
            'id', 'project', 'project_name', 'title', 'venue', 'venue_name', 'event_type',
            'start_datetime', 'end_datetime',
            'buffer_before_minutes', 'buffer_after_minutes',
            'notes', 'effective_start', 'effective_end',
        ]

    def validate(self, attrs):
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
        if not _same_project(project, venue):
            raise serializers.ValidationError({
                'venue': "Le lieu doit appartenir au même projet que le spectacle.",
            })
        return attrs


class ShowMaterialSerializer(serializers.ModelSerializer):
    """Sérialise l'assignation de matériel à un spectacle, avec validation de conflit bloquante (voir `force`)."""

    force = serializers.BooleanField(write_only=True, required=False, default=False)
    show_title = serializers.CharField(source='show.title', read_only=True)
    material_name = serializers.CharField(source='material.name', read_only=True)
    # Reflète la couleur du département responsable du matériel (voir `Department.color`)
    # jusque dans les assignations show/matériel, pour un code couleur cohérent dans tout
    # le planning de production.
    department_color = serializers.CharField(source='material.department.color', read_only=True, default=None)

    class Meta:
        model = ShowMaterial
        fields = [
            'id', 'show', 'material', 'quantity', 'is_rental', 'rental_vendor',
            'show_title', 'material_name', 'department_color', 'force',
        ]

    def validate(self, attrs):
        force = attrs.pop('force', False)
        show = attrs.get('show', getattr(self.instance, 'show', None))
        material = attrs.get('material', getattr(self.instance, 'material', None))
        quantity = attrs.get('quantity', getattr(self.instance, 'quantity', 1))

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
    show_title = serializers.CharField(source='show.title', read_only=True)
    technician_name = serializers.CharField(source='technician.name', read_only=True)

    class Meta:
        model = ShowTechnician
        fields = ['id', 'show', 'technician', 'show_title', 'technician_name', 'force']

    def validate(self, attrs):
        force = attrs.pop('force', False)
        show = attrs.get('show', getattr(self.instance, 'show', None))
        technician = attrs.get('technician', getattr(self.instance, 'technician', None))

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


class TransportSerializer(serializers.ModelSerializer):
    """Sérialise un déplacement (livraison/ramassage) de matériel, avec
    validation de conflit bloquante sur le technicien assigné (voir `force`).

    Un technicien assigné à un `Transport` est croisé avec ses engagements
    `ShowTechnician` ET ses autres `Transport` — voir `conflicts.py`.
    """

    force = serializers.BooleanField(write_only=True, required=False, default=False)
    show_title = serializers.CharField(source='show.title', read_only=True)
    origin_venue_name = serializers.CharField(source='origin_venue.name', read_only=True)
    destination_venue_name = serializers.CharField(source='destination_venue.name', read_only=True)
    # Code court (voir Venue.code) pour un affichage compact départ/arrivée
    # (ex. "CHAP -> Salle principale") — vide si le lieu n'a pas de code.
    origin_venue_code = serializers.CharField(source='origin_venue.code', read_only=True, default='')
    destination_venue_code = serializers.CharField(source='destination_venue.code', read_only=True, default='')
    technician_name = serializers.CharField(source='technician.name', read_only=True, default=None)
    effective_end = serializers.DateTimeField(read_only=True)

    class Meta:
        model = Transport
        fields = [
            'id', 'show', 'show_title', 'transport_type',
            'origin_venue', 'origin_venue_name', 'origin_venue_code',
            'destination_venue', 'destination_venue_name', 'destination_venue_code',
            'scheduled_datetime', 'estimated_duration_minutes', 'effective_end',
            'technician', 'technician_name', 'notes', 'force',
        ]

    def validate(self, attrs):
        origin = attrs.get('origin_venue', getattr(self.instance, 'origin_venue', None))
        destination = attrs.get('destination_venue', getattr(self.instance, 'destination_venue', None))
        if origin and destination and origin.id == destination.id:
            raise serializers.ValidationError({
                'destination_venue': "Doit être différent du lieu de départ.",
            })

        # Isolation par projet (voir Project, models.py) : le spectacle, les
        # deux lieux et le technicien (si fourni) doivent tous appartenir au
        # même projet.
        show = attrs.get('show', getattr(self.instance, 'show', None))
        technician_for_project_check = attrs.get('technician', getattr(self.instance, 'technician', None))
        if not _same_project(show, origin, destination, technician_for_project_check):
            raise serializers.ValidationError(
                "Le spectacle, les lieux et le technicien d'un déplacement doivent tous appartenir au même projet."
            )

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
        technician = attrs.get('technician', getattr(self.instance, 'technician', None))
        scheduled_datetime = attrs.get('scheduled_datetime', getattr(self.instance, 'scheduled_datetime', None))
        duration = attrs.get(
            'estimated_duration_minutes',
            getattr(self.instance, 'estimated_duration_minutes', None),
        )

        if technician and scheduled_datetime and duration and not force:
            exclude_id = self.instance.id if self.instance else None
            conflicts = get_transport_conflicts(scheduled_datetime, duration, technician, exclude_id=exclude_id)
            if conflicts:
                raise serializers.ValidationError({
                    'conflicts': [serialize_technician_conflict(c) for c in conflicts],
                    'detail': (
                        "Chevauchement d'horaire détecté pour ce technicien (spectacle ou "
                        "autre déplacement). "
                        'Ajoute "force": true dans la requête pour forcer l\'assignation '
                        'malgré le conflit.'
                    ),
                })
        return attrs


class SettingsSerializer(serializers.ModelSerializer):
    """Sérialise le singleton `Settings` (voir `views.SettingsView` — pas de liste ni de création)."""

    class Meta:
        model = Settings
        fields = [
            'default_buffer_before_minutes', 'default_buffer_after_minutes',
            'default_transport_duration_minutes', 'date_format', 'time_format',
        ]

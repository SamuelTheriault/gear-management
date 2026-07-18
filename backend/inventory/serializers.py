"""
Serializers DRF — squelette API pour les 8 tables de schema.md.

La validation de conflit (voir conflicts.py) vit dans les serializers des deux
tables d'association (`ShowMaterialSerializer`, `ShowTechnicianSerializer`) :
bloquant par défaut, avec possibilité de forcer via le champ `force` (décision
prise avec Samuel le 2026-07-17 — voir recapitulatif_projet.md).
"""

from rest_framework import serializers

from .conflicts import (
    get_material_conflicts,
    get_technician_conflicts,
    serialize_material_conflict,
    serialize_technician_conflict,
)
from .models import (
    Department,
    Material,
    Show,
    ShowMaterial,
    ShowTechnician,
    Technician,
    User,
    Venue,
)


class UserSerializer(serializers.ModelSerializer):
    """Sérialise les comptes applicatifs (voir `models.User`)."""

    class Meta:
        model = User
        fields = ['id', 'email', 'name', 'role', 'created_at']
        read_only_fields = ['created_at']


class VenueSerializer(serializers.ModelSerializer):
    """Sérialise les lieux (salles, théâtres, sites de représentation)."""

    class Meta:
        model = Venue
        fields = ['id', 'name', 'address', 'contact_name', 'contact_info', 'notes']


class DepartmentSerializer(serializers.ModelSerializer):
    """Sérialise les départements responsables du matériel."""

    class Meta:
        model = Department
        fields = ['id', 'name', 'contact_name', 'contact_info', 'notes']


class MaterialSerializer(serializers.ModelSerializer):
    """Sérialise l'inventaire de matériel, avec noms lisibles pour les FK (parent/venue/département)."""

    parent_material_name = serializers.CharField(source='parent_material.name', read_only=True, default=None)
    venue_name = serializers.CharField(source='venue.name', read_only=True, default=None)
    department_name = serializers.CharField(source='department.name', read_only=True, default=None)
    component_ids = serializers.PrimaryKeyRelatedField(source='components', many=True, read_only=True)

    class Meta:
        model = Material
        fields = [
            'id', 'name', 'description', 'category',
            'parent_material', 'parent_material_name',
            'venue', 'venue_name',
            'department', 'department_name',
            'ownership_status', 'notes', 'component_ids',
        ]

    def validate_parent_material(self, value):
        if value is not None and self.instance is not None and value.id == self.instance.id:
            raise serializers.ValidationError("Un matériel ne peut pas être son propre parent.")
        return value


class ShowSerializer(serializers.ModelSerializer):
    """Sérialise les fiches spectacles, en exposant la fenêtre effective calculée (buffers inclus)."""

    venue_name = serializers.CharField(source='venue.name', read_only=True)
    effective_start = serializers.DateTimeField(read_only=True)
    effective_end = serializers.DateTimeField(read_only=True)

    class Meta:
        model = Show
        fields = [
            'id', 'title', 'venue', 'venue_name', 'event_type',
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
        return attrs


class ShowMaterialSerializer(serializers.ModelSerializer):
    """Sérialise l'assignation de matériel à un spectacle, avec validation de conflit bloquante (voir `force`)."""

    force = serializers.BooleanField(write_only=True, required=False, default=False)
    show_title = serializers.CharField(source='show.title', read_only=True)
    material_name = serializers.CharField(source='material.name', read_only=True)

    class Meta:
        model = ShowMaterial
        fields = [
            'id', 'show', 'material', 'is_rental', 'rental_vendor',
            'show_title', 'material_name', 'force',
        ]

    def validate(self, attrs):
        force = attrs.pop('force', False)
        show = attrs.get('show', getattr(self.instance, 'show', None))
        material = attrs.get('material', getattr(self.instance, 'material', None))

        if show and material and not force:
            exclude_id = self.instance.id if self.instance else None
            conflicts = get_material_conflicts(show, material, exclude_id=exclude_id)
            if conflicts:
                raise serializers.ValidationError({
                    'conflicts': [serialize_material_conflict(c) for c in conflicts],
                    'detail': (
                        "Chevauchement d'horaire détecté avec une ou plusieurs autres "
                        "assignations de ce matériel (ou d'un matériel parent/enfant lié). "
                        'Ajoute "force": true dans la requête pour forcer l\'assignation '
                        'malgré le conflit.'
                    ),
                })
        return attrs


class TechnicianSerializer(serializers.ModelSerializer):
    """Sérialise les techniciens disponibles pour assignation."""

    class Meta:
        model = Technician
        fields = ['id', 'name', 'contact_info', 'specialty', 'notes']


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

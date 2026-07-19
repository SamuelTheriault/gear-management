"""
Duplication de projet — voir `Project` (models.py) et `architecture.md`,
section 4quater. Ajouté le 2026-07-19 à la demande de Samuel : démarrer une
nouvelle édition d'un mandat (même client, même matériel/lieux/techniciens de
base) sans repartir de zéro, sans traîner l'horaire de l'édition précédente.

Copie `Venue`, `Material` (hiérarchie parent/enfant préservée, remappée vers
les nouvelles lignes) et `Technician` du projet source vers un nouveau
projet. Exclut volontairement toute donnée d'assignation/horaire (`Show`,
`ShowMaterial`, `ShowTechnician`, `Transport`) — une nouvelle édition a son
propre calendrier. `Department` n'est jamais remappé : c'est un référentiel
commun à tous les projets (voir `Department`, models.py), pas une donnée de
projet à dupliquer.
"""

from django.db import transaction

from .models import Material, Project, Technician, Venue


def duplicate_project(source_project, name, client_name=''):
    """Crée un nouveau `Project` et y copie le contenu non assigné de
    `source_project` : lieux, matériel (avec hiérarchie), techniciens.

    `name` : nom du nouveau projet (obligatoire, fourni par l'appelant).
    `client_name` : repris du projet source par défaut côté vue
    (`ProjectViewSet.duplicate`) si l'appelant n'en fournit pas — décision
    Samuel du 2026-07-19 : une nouvelle édition, c'est généralement le même
    client. `status` reparts à `active` et `start_date`/`end_date`/`notes`
    restent vides quel que soit l'état du projet source — une nouvelle
    édition a ses propres dates et ne doit pas hériter des notes d'une
    édition précédente.

    Le projet source n'est jamais modifié. Toute l'opération est atomique :
    en cas d'erreur, rien n'est créé.

    Retourne `(nouveau_projet, counts)` où `counts` est un dict
    `{'venues': n, 'materials': n, 'technicians': n}`.
    """
    with transaction.atomic():
        new_project = Project.objects.create(name=name, client_name=client_name)

        venue_id_map = {}
        for venue in source_project.venues.all():
            new_venue = Venue.objects.create(
                project=new_project,
                name=venue.name,
                address=venue.address,
                contact_name=venue.contact_name,
                contact_info=venue.contact_info,
                notes=venue.notes,
                is_storage=venue.is_storage,
                latitude=venue.latitude,
                longitude=venue.longitude,
            )
            venue_id_map[venue.id] = new_venue

        # Matériel — deux passes : la hiérarchie parent/enfant (`parent_material`,
        # self-FK) ne peut être remappée qu'une fois TOUTES les copies créées.
        material_id_map = {}
        source_materials = list(source_project.materials.all())
        for material in source_materials:
            new_material = Material.objects.create(
                project=new_project,
                name=material.name,
                description=material.description,
                category=material.category,
                venue=venue_id_map.get(material.venue_id),
                # `department` est un référentiel commun à tous les projets — on
                # garde la même ligne, jamais remappée (voir docstring de module).
                department=material.department,
                ownership_status=material.ownership_status,
                is_active=material.is_active,
                quantity=material.quantity,
                notes=material.notes,
            )
            material_id_map[material.id] = new_material

        for material in source_materials:
            if material.parent_material_id:
                new_material = material_id_map[material.id]
                new_material.parent_material = material_id_map[material.parent_material_id]
                new_material.save(update_fields=['parent_material'])

        technician_count = 0
        for technician in source_project.technicians.all():
            Technician.objects.create(
                project=new_project,
                name=technician.name,
                contact_info=technician.contact_info,
                specialty=technician.specialty,
                notes=technician.notes,
            )
            technician_count += 1

        counts = {
            'venues': len(venue_id_map),
            'materials': len(material_id_map),
            'technicians': technician_count,
        }
        return new_project, counts

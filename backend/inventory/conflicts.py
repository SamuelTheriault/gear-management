"""
Logique de détection de conflits d'horaire — voir architecture.md, section 4,
et schema.md, sections 6, 8 et 9.

Deux types de conflits, même logique sous-jacente :

- Matériel (`show_materials`) : un matériel parent/enfant lié dans la
  hiérarchie kit ne peut pas être assigné à deux spectacles dont les fenêtres
  effectives se chevauchent (binaire — ces matériels sont toujours à
  quantity=1, imposé par MaterialSerializer). Le matériel exact demandé, lui,
  a une capacité partagée : `Material.quantity` unités au total, réparties
  entre les `ShowMaterial` dont les fenêtres se chevauchent (voir
  `get_material_conflicts`, ajouté le 2026-07-19 à la demande de Samuel pour
  gérer du matériel identique en plusieurs exemplaires — ex. 20 rallonges
  électriques dont 5 assignées à un spectacle sans créer 20 items).
- Techniciens (`show_technicians` + `transports`) : un technicien ne peut pas
  être engagé sur deux choses dont les fenêtres se chevauchent — que ce soit
  deux spectacles, un spectacle et un déplacement, ou deux déplacements.

La fenêtre effective d'un spectacle = [start_datetime - buffer_before_minutes,
end_datetime + buffer_after_minutes] (voir Show.effective_start / effective_end
dans models.py). La fenêtre d'un déplacement (`Transport`) = [scheduled_datetime,
scheduled_datetime + estimated_duration_minutes] (voir Transport.effective_end).
Le chevauchement est strict : deux fenêtres qui se touchent exactement à leur
limite (la fin de l'une == le début de l'autre) ne sont PAS considérées en
conflit — convention standard d'intervalles, et ça permet d'enchaîner deux
engagements dos-à-dos sans déclencher un faux positif.

Entreposage (décision prise avec Samuel le 2026-07-18) : un `Show` dont le
`venue` a `is_storage=True` représente une période où le matériel est
simplement rangé, disponible, pas « en usage ». Ce type de Show est donc
totalement ignoré par la détection de conflits matériel : assigner du
matériel à un Show d'entrepôt ne déclenche jamais de conflit, et une
assignation existante à un Show d'entrepôt n'est jamais comptée comme
conflit pour un autre Show (réel, lui). Cette exemption ne s'applique qu'au
matériel — un technicien assigné à un Show d'entrepôt (ex. pour faire de
l'inventaire) reste soumis à la détection de conflits normale, puisque ça
représente un vrai engagement d'horaire pour lui.

Transport (décision prise avec Samuel le 2026-07-18) : livraison/ramassage de
matériel vers/depuis un lieu de spectacle, avec un technicien assigné. Un
technicien ne peut pas être sur un spectacle ET faire un déplacement en même
temps — `get_technician_conflicts` (assignation à un Show) et
`get_transport_conflicts` (assignation à un Transport) vérifient donc
désormais l'une contre l'autre, via `_technician_commitments`.
"""

from datetime import timedelta

from .models import Material, ShowMaterial, ShowTechnician, Transport


def _collect_material_family(material, _seen=None):
    """IDs du matériel donné + tous ses ancêtres + tous ses descendants.

    Récursif pour supporter une hiérarchie à plus d'un niveau (un kit peut
    en théorie contenir un sous-kit), même si l'usage courant décrit dans
    schema.md est à un seul niveau (kit -> composants).
    """
    if _seen is None:
        _seen = set()
    if material.id in _seen:
        return _seen
    _seen.add(material.id)

    if material.parent_material_id and material.parent_material_id not in _seen:
        parent = material.parent_material
        if parent is not None:
            _collect_material_family(parent, _seen)

    for child in material.components.all():
        if child.id not in _seen:
            _collect_material_family(child, _seen)

    return _seen


def windows_overlap(start_a, end_a, start_b, end_b):
    """Chevauchement strict entre deux intervalles [start, end)."""
    return start_a < end_b and start_b < end_a


def get_material_conflicts(show, material, exclude_id=None, quantity=1):
    """Retourne la liste des `ShowMaterial` existants qui entreraient en
    conflit si on assignait `quantity` unités de `material` à `show`.

    Deux mécanismes distincts, tous deux vérifiés :

    - Hiérarchie (parent/enfant) : tout chevauchement avec un autre membre de
      la famille est un conflit binaire — ces matériels sont toujours à
      quantity=1 (imposé par MaterialSerializer.validate()), donc pas de
      notion de capacité partagée à calculer pour eux.
    - Matériel exact (même material_id) : les fenêtres qui chevauchent
      celle de `show` partagent la capacité totale `material.quantity`. On
      additionne les quantités déjà assignées sur ces fenêtres ; si `quantity`
      ferait dépasser `material.quantity`, les assignations existantes qui y
      contribuent sont retournées comme conflits.

    Une demande dont `quantity` dépasse à elle seule `material.quantity`
    (aucune assignation existante nécessaire pour que ce soit déjà trop) est
    rejetée en amont par `ShowMaterialSerializer.validate()`, pas ici — ce
    cas ne dépend d'aucune fenêtre à comparer.

    `exclude_id` : à fournir lors d'une mise à jour, pour exclure
    l'assignation elle-même de la comparaison.

    Un `show` dont le venue est un entrepôt (`venue.is_storage=True`) n'a
    jamais de conflit matériel : ni comme nouvelle assignation (on renvoie
    tout de suite une liste vide), ni comme candidat existant (les
    assignations à un Show d'entrepôt sont exclues des candidats).
    """
    if show.venue.is_storage:
        return []

    family_ids = _collect_material_family(material)
    other_family_ids = family_ids - {material.id}
    new_start, new_end = show.effective_start, show.effective_end
    conflicts = []

    if other_family_ids:
        family_candidates = (
            ShowMaterial.objects.filter(material_id__in=other_family_ids)
            .exclude(show_id=show.id)
            .exclude(show__venue__is_storage=True)
            .select_related('show', 'material', 'show__venue')
        )
        if exclude_id is not None:
            family_candidates = family_candidates.exclude(id=exclude_id)
        conflicts += [
            sm for sm in family_candidates
            if windows_overlap(new_start, new_end, sm.show.effective_start, sm.show.effective_end)
        ]

    same_material_candidates = (
        ShowMaterial.objects.filter(material_id=material.id)
        .exclude(show_id=show.id)
        .exclude(show__venue__is_storage=True)
        .select_related('show', 'material', 'show__venue')
    )
    if exclude_id is not None:
        same_material_candidates = same_material_candidates.exclude(id=exclude_id)

    overlapping_same_material = [
        sm for sm in same_material_candidates
        if windows_overlap(new_start, new_end, sm.show.effective_start, sm.show.effective_end)
    ]
    already_allocated = sum(sm.quantity for sm in overlapping_same_material)
    if already_allocated + quantity > material.quantity:
        conflicts += overlapping_same_material

    return conflicts


def _technician_commitments(technician_id, exclude_show_technician_id=None, exclude_transport_id=None):
    """Liste de `(objet, début, fin)` pour tous les engagements d'un technicien
    (assignations à des spectacles ET déplacements), utilisée pour croiser les
    deux types d'engagement dans une seule vérification de conflit."""
    show_technicians = ShowTechnician.objects.filter(technician_id=technician_id).select_related('show')
    if exclude_show_technician_id is not None:
        show_technicians = show_technicians.exclude(id=exclude_show_technician_id)

    transports = Transport.objects.filter(technician_id=technician_id).select_related('show')
    if exclude_transport_id is not None:
        transports = transports.exclude(id=exclude_transport_id)

    commitments = [(st, st.show.effective_start, st.show.effective_end) for st in show_technicians]
    commitments += [(t, t.scheduled_datetime, t.effective_end) for t in transports]
    return commitments


def get_technician_conflicts(show, technician, exclude_id=None):
    """Retourne la liste des engagements existants (`ShowTechnician` ou
    `Transport`) qui entreraient en conflit si `technician` était assigné à
    `show`.

    `exclude_id` : id du `ShowTechnician` à exclure lors d'une mise à jour.
    """
    new_start, new_end = show.effective_start, show.effective_end
    conflicts = []
    for obj, start, end in _technician_commitments(technician.id, exclude_show_technician_id=exclude_id):
        if isinstance(obj, ShowTechnician) and obj.show_id == show.id:
            continue  # même spectacle : jamais un conflit avec soi-même
        if windows_overlap(new_start, new_end, start, end):
            conflicts.append(obj)
    return conflicts


def get_transport_conflicts(scheduled_datetime, duration_minutes, technician, exclude_id=None):
    """Retourne la liste des engagements existants (`ShowTechnician` ou
    `Transport`) qui entreraient en conflit si `technician` était assigné à un
    déplacement démarrant à `scheduled_datetime` et durant `duration_minutes`.

    `exclude_id` : id du `Transport` à exclure lors d'une mise à jour.
    """
    new_start = scheduled_datetime
    new_end = scheduled_datetime + timedelta(minutes=duration_minutes)
    conflicts = []
    for obj, start, end in _technician_commitments(technician.id, exclude_transport_id=exclude_id):
        if windows_overlap(new_start, new_end, start, end):
            conflicts.append(obj)
    return conflicts


def serialize_material_conflict(show_material):
    """Représentation compacte d'un `ShowMaterial` en conflit, pour la réponse API."""
    sm = show_material
    return {
        'type': 'show_material',
        'show_material_id': sm.id,
        'show_id': sm.show_id,
        'show_title': sm.show.title,
        'show_start': sm.show.start_datetime,
        'show_end': sm.show.end_datetime,
        'material_id': sm.material_id,
        'material_name': sm.material.name,
    }


def serialize_technician_conflict(obj):
    """Représentation compacte d'un conflit technicien, pour la réponse API.

    `obj` peut être un `ShowTechnician` (assignation à un spectacle) ou un
    `Transport` (livraison/ramassage) — les deux sont désormais croisés
    ensemble par `get_technician_conflicts`/`get_transport_conflicts`.
    """
    if isinstance(obj, Transport):
        return {
            'type': 'transport',
            'transport_id': obj.id,
            'show_id': obj.show_id,
            'show_title': obj.show.title,
            'transport_type': obj.transport_type,
            'scheduled_datetime': obj.scheduled_datetime,
            'estimated_duration_minutes': obj.estimated_duration_minutes,
            'technician_id': obj.technician_id,
            'technician_name': obj.technician.name if obj.technician_id else None,
        }

    st = obj
    return {
        'type': 'show_technician',
        'show_technician_id': st.id,
        'show_id': st.show_id,
        'show_title': st.show.title,
        'show_start': st.show.start_datetime,
        'show_end': st.show.end_datetime,
        'technician_id': st.technician_id,
        'technician_name': st.technician.name,
    }

"""
Logique de détection de conflits d'horaire — voir architecture.md, section 4,
et schema.md, sections 6 et 8.

Deux types de conflits, même logique sous-jacente :

- Matériel (`show_materials`) : un même matériel — ou un matériel parent/enfant
  qui lui est lié dans la hiérarchie — ne peut pas être assigné à deux
  spectacles dont les fenêtres effectives se chevauchent.
- Techniciens (`show_technicians`) : un technicien ne peut pas être assigné à
  deux spectacles dont les fenêtres effectives se chevauchent.

La fenêtre effective d'un spectacle = [start_datetime - buffer_before_minutes,
end_datetime + buffer_after_minutes] (voir Show.effective_start / effective_end
dans models.py). Le chevauchement est strict : deux fenêtres qui se touchent
exactement à leur limite (la fin de l'une == le début de l'autre) ne sont PAS
considérées en conflit — convention standard d'intervalles, et ça permet
d'enchaîner deux spectacles dos-à-dos sans déclencher un faux positif.
"""

from .models import Material, ShowMaterial, ShowTechnician


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


def get_material_conflicts(show, material, exclude_id=None):
    """Retourne la liste des `ShowMaterial` existants qui entreraient en
    conflit si `material` était assigné à `show`.

    `exclude_id` : à fournir lors d'une mise à jour, pour exclure
    l'assignation elle-même de la comparaison.
    """
    family_ids = _collect_material_family(material)

    candidates = (
        ShowMaterial.objects.filter(material_id__in=family_ids)
        .exclude(show_id=show.id)
        .select_related('show', 'material')
    )
    if exclude_id is not None:
        candidates = candidates.exclude(id=exclude_id)

    new_start, new_end = show.effective_start, show.effective_end
    return [
        sm for sm in candidates
        if windows_overlap(new_start, new_end, sm.show.effective_start, sm.show.effective_end)
    ]


def get_technician_conflicts(show, technician, exclude_id=None):
    """Retourne la liste des `ShowTechnician` existants qui entreraient en
    conflit si `technician` était assigné à `show`."""
    candidates = (
        ShowTechnician.objects.filter(technician_id=technician.id)
        .exclude(show_id=show.id)
        .select_related('show', 'technician')
    )
    if exclude_id is not None:
        candidates = candidates.exclude(id=exclude_id)

    new_start, new_end = show.effective_start, show.effective_end
    return [
        st for st in candidates
        if windows_overlap(new_start, new_end, st.show.effective_start, st.show.effective_end)
    ]


def serialize_material_conflict(show_material):
    """Représentation compacte d'un `ShowMaterial` en conflit, pour la réponse API."""
    sm = show_material
    return {
        'show_material_id': sm.id,
        'show_id': sm.show_id,
        'show_title': sm.show.title,
        'show_start': sm.show.start_datetime,
        'show_end': sm.show.end_datetime,
        'material_id': sm.material_id,
        'material_name': sm.material.name,
    }


def serialize_technician_conflict(show_technician):
    """Représentation compacte d'un `ShowTechnician` en conflit, pour la réponse API."""
    st = show_technician
    return {
        'show_technician_id': st.id,
        'show_id': st.show_id,
        'show_title': st.show.title,
        'show_start': st.show.start_datetime,
        'show_end': st.show.end_datetime,
        'technician_id': st.technician_id,
        'technician_name': st.technician.name,
    }

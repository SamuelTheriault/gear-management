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
dans models.py). La fenêtre d'une tournée (`Transport`) = [scheduled_datetime,
scheduled_datetime + somme des durées de segment] (voir Transport.effective_end
et Transport.total_duration_minutes — tournées multi-arrêts depuis le
2026-08-04) : un technicien affecté est engagé du départ du premier arrêt à
l'arrivée au dernier.
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

Conflit de lieu (décision prise avec Samuel le 2026-07-19) : deux spectacles
ne peuvent jamais physiquement occuper le même lieu (`venue`) en même temps
— `get_venue_conflicts` vérifie ça directement entre `Show`, complètement
indépendamment du matériel ou des techniciens assignés (qui, eux, restent
interdits de chevauchement peu importe le lieu — voir plus haut). Même
exemption d'entreposage que pour le matériel : un lieu d'entrepôt peut
recevoir plusieurs fiches de rangement qui se chevauchent sans que ce soit
un vrai conflit d'occupation physique.

Fenêtre départ/arrivée d'un déplacement (décision Samuel du 2026-07-30,
adaptée aux tournées le 2026-08-04) : un `Transport` ne connaît qu'UN
spectacle explicite (`show`, le spectacle « desservi »). Les bornes de la
tournée sont ses PREMIER et DERNIER arrêts — les arrêts intermédiaires ne
bornent rien (on s'y arrête en passant, pas de spectacle à attendre ou à
devancer par construction). Si le lieu du spectacle desservi est le dernier
arrêt, `show` est le spectacle d'arrivée (l'ancienne « livraison ») ; si c'est
le premier, il est le spectacle de départ (l'ancien « ramassage ») — c'est ce
qui remplace le champ `transport_type`, retiré le 2026-08-04. L'autre bout est
déduit par `find_departure_show`/`find_arrival_show` (le spectacle le plus
proche chronologiquement à ce lieu) — un lieu d'entrepôt (`is_storage=True`)
n'a jamais de spectacle associé (le matériel y est toujours disponible), donc
pas de borne de ce côté. `get_transport_reference_shows` combine les deux pour
exposer, pour n'importe quelle tournée, le spectacle de départ ET d'arrivée
(utilisé par `TransportSerializer` pour l'affichage ET la validation — voir
`validate_transport_window`) : la tournée doit avoir lieu ENTRE la fin
effective du spectacle de départ et le début effectif du spectacle
d'arrivée (buffers inclus, comme partout ailleurs). Bloquant + `force`, même
pattern que les autres conflits.
"""

from datetime import timedelta

from .models import (
    Material,
    Show,
    ShowMaterial,
    ShowTechnician,
    TransportTechnician,
)


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
    # Fenêtre d'ENGAGEMENT (2026-07-31) : le matériel d'un événement est
    # mobilisé du montage au démontage, pas seulement sur le créneau du
    # spectacle — voir `Show.engagement_start`.
    new_start, new_end = show.engagement_start, show.engagement_end
    # Un événement ne se dispute pas son propre matériel avec ses blocs
    # rattachés (2026-07-31) : une répétition rattachée porte une copie des
    # assignations de l'événement, et elle lui est collée — avec un buffer,
    # les deux fenêtres se chevauchent forcément. Même raisonnement et même
    # mécanisme que l'exclusion de famille du conflit de LIEU. Sur un
    # spectacle sans bloc, `family_ids` se réduit à `{show.id}` : le
    # comportement d'origine (« jamais un conflit avec soi-même », dont dépend
    # l'assignation d'un kit ET de ses composants au même spectacle) est
    # inchangé.
    show_family_ids = show.family_ids
    conflicts = []

    if other_family_ids:
        family_candidates = (
            ShowMaterial.objects.filter(material_id__in=other_family_ids)
            .exclude(show_id__in=show_family_ids)
            .exclude(show__venue__is_storage=True)
            .select_related('show', 'material', 'show__venue')
        )
        if exclude_id is not None:
            family_candidates = family_candidates.exclude(id=exclude_id)
        conflicts += [
            sm for sm in family_candidates
            if windows_overlap(new_start, new_end, sm.show.engagement_start, sm.show.engagement_end)
        ]

    same_material_candidates = (
        ShowMaterial.objects.filter(material_id=material.id)
        .exclude(show_id__in=show_family_ids)
        .exclude(show__venue__is_storage=True)
        .select_related('show', 'material', 'show__venue')
    )
    if exclude_id is not None:
        same_material_candidates = same_material_candidates.exclude(id=exclude_id)

    overlapping_same_material = [
        sm for sm in same_material_candidates
        if windows_overlap(new_start, new_end, sm.show.engagement_start, sm.show.engagement_end)
    ]
    already_allocated = sum(sm.quantity for sm in overlapping_same_material)
    if already_allocated + quantity > material.quantity:
        conflicts += overlapping_same_material

    return conflicts


def get_venue_conflicts(venue, effective_start, effective_end, exclude_id=None, exclude_family_ids=None):
    """Retourne la liste des `Show` existants qui entreraient en conflit de
    lieu si un spectacle occupait `venue` sur la fenêtre
    `[effective_start, effective_end]` (déjà bufferisée par l'appelant).

    Deux spectacles ne peuvent jamais physiquement occuper le même lieu en
    même temps — vérification indépendante de tout matériel ou technicien
    partagé (voir `get_material_conflicts`/`get_technician_conflicts`, qui
    ignorent complètement le lieu).

    Un lieu d'entrepôt (`venue.is_storage=True`) n'est jamais soumis à cette
    règle : plusieurs fiches de rangement peuvent coexister au même entrepôt
    en même temps, ce n'est pas une occupation physique exclusive.

    `exclude_id` : id du `Show` à exclure lors d'une mise à jour (le
    spectacle qu'on modifie ne doit pas se comparer à lui-même).

    `exclude_family_ids` : ids de l'événement et de ses blocs rattachés
    (montage/démontage, voir `Show.parent_show`, 2026-07-31). Un bloc est
    collé à son événement : leurs fenêtres EFFECTIVES se chevauchent dès
    qu'un buffer est renseigné, et sans cette exclusion un montage serait
    signalé en conflit de lieu avec le spectacle qu'il prépare. C'est le
    « pas de double comptage » décidé avec Samuel — les buffers restent, mais
    ne se retournent pas contre les blocs explicites.
    """
    if venue.is_storage:
        return []

    candidates = Show.objects.filter(venue_id=venue.id).select_related('venue')
    if exclude_id is not None:
        candidates = candidates.exclude(id=exclude_id)
    if exclude_family_ids:
        candidates = candidates.exclude(id__in=exclude_family_ids)

    return [
        s for s in candidates
        if windows_overlap(effective_start, effective_end, s.effective_start, s.effective_end)
    ]


def _technician_commitments(technician_id, exclude_show_technician_id=None, exclude_transport_id=None):
    """Liste de `(objet, début, fin)` pour tous les engagements d'un technicien
    (assignations à des spectacles ET déplacements), utilisée pour croiser les
    deux types d'engagement dans une seule vérification de conflit."""
    show_technicians = ShowTechnician.objects.filter(technician_id=technician_id).select_related('show')
    if exclude_show_technician_id is not None:
        show_technicians = show_technicians.exclude(id=exclude_show_technician_id)

    # Une proposition auto ('to_approve') sans heure n'a pas de fenêtre
    # exploitable : on exclut les transports sans `scheduled_datetime` pour
    # ne jamais comparer une fenêtre incomplète (effective_end=None).
    #
    # Depuis le 2026-07-30, un déplacement peut mobiliser PLUSIEURS techniciens
    # (table `TransportTechnician`) : l'engagement unitaire est donc le couple
    # (transport, technicien), pas le transport lui-même.
    transport_technicians = (
        TransportTechnician.objects
        .filter(technician_id=technician_id, transport__scheduled_datetime__isnull=False)
        .select_related('transport', 'transport__show', 'technician')
        # `effective_end` somme les segments de la tournée (2026-08-04) — le
        # prefetch évite une requête par arrêt dans la boucle ci-dessous.
        .prefetch_related('transport__stops')
    )
    if exclude_transport_id is not None:
        transport_technicians = transport_technicians.exclude(transport_id=exclude_transport_id)

    # Même règle que pour le matériel : un technicien assigné à un
    # événement est engagé pendant son montage et son démontage.
    commitments = [(st, st.show.engagement_start, st.show.engagement_end) for st in show_technicians]
    commitments += [
        (tt, tt.transport.scheduled_datetime, tt.transport.effective_end)
        for tt in transport_technicians
    ]
    return commitments


def get_technician_conflicts(show, technician, exclude_id=None):
    """Retourne la liste des engagements existants (`ShowTechnician` ou
    `TransportTechnician`) qui entreraient en conflit si `technician` était
    assigné à `show`.

    `exclude_id` : id du `ShowTechnician` à exclure lors d'une mise à jour.
    """
    new_start, new_end = show.engagement_start, show.engagement_end
    # Voir `get_material_conflicts` : un événement et ses blocs rattachés
    # forment une seule unité de travail, ils ne se disputent pas leur propre
    # équipe. Sans bloc, `family_ids` vaut `{show.id}` — comportement d'origine.
    show_family_ids = show.family_ids
    conflicts = []
    for obj, start, end in _technician_commitments(technician.id, exclude_show_technician_id=exclude_id):
        if isinstance(obj, ShowTechnician) and obj.show_id in show_family_ids:
            continue  # même événement (ou l'un de ses blocs) : pas un conflit
        if windows_overlap(new_start, new_end, start, end):
            conflicts.append(obj)
    return conflicts


def get_transport_conflicts(scheduled_datetime, duration_minutes, technician, exclude_id=None):
    """Retourne la liste des engagements existants (`ShowTechnician` ou
    `TransportTechnician`) qui entreraient en conflit si `technician` était
    affecté à un déplacement démarrant à `scheduled_datetime` et durant
    `duration_minutes`.

    Reste par technicien : un déplacement pouvant en mobiliser plusieurs
    (2026-07-30), l'appelant boucle sur chacun — voir
    `TransportSerializer.validate`.

    `exclude_id` : id du `Transport` à exclure lors d'une mise à jour (toutes
    ses affectations, pas une seule).
    """
    new_start = scheduled_datetime
    new_end = scheduled_datetime + timedelta(minutes=duration_minutes)
    conflicts = []
    for obj, start, end in _technician_commitments(technician.id, exclude_transport_id=exclude_id):
        if windows_overlap(new_start, new_end, start, end):
            conflicts.append(obj)
    return conflicts


def find_departure_show(venue, before_datetime, exclude_show_id=None):
    """Déduit le « spectacle de départ » d'un déplacement : le spectacle le
    plus récent à `venue` dont la fenêtre effective se termine avant
    `before_datetime` (voir note de module 2026-07-30).

    Un lieu d'entrepôt (`venue.is_storage=True`) n'a jamais de spectacle de
    départ — le matériel y est toujours réputé disponible, retourne `None`.
    Retourne aussi `None` si aucun spectacle ne précède `before_datetime` à ce
    lieu (première utilisation, ou lieu jamais utilisé pour un spectacle).
    """
    if venue is None or venue.is_storage or before_datetime is None:
        return None
    candidates = Show.objects.filter(venue_id=venue.id)
    if exclude_show_id is not None:
        candidates = candidates.exclude(id=exclude_show_id)
    prior = [s for s in candidates if s.effective_end <= before_datetime]
    if not prior:
        return None
    return max(prior, key=lambda s: s.effective_end)


def find_arrival_show(venue, after_datetime, exclude_show_id=None):
    """Symétrique de `find_departure_show` : déduit le « spectacle d'arrivée »
    — le spectacle le plus proche à `venue` dont la fenêtre effective
    commence après `after_datetime`. Mêmes exemptions (entrepôt, aucun
    candidat trouvé → `None`)."""
    if venue is None or venue.is_storage or after_datetime is None:
        return None
    candidates = Show.objects.filter(venue_id=venue.id)
    if exclude_show_id is not None:
        candidates = candidates.exclude(id=exclude_show_id)
    upcoming = [s for s in candidates if s.effective_start >= after_datetime]
    if not upcoming:
        return None
    return min(upcoming, key=lambda s: s.effective_start)


def get_transport_reference_shows(show, origin_venue, destination_venue):
    """Retourne `(departure_show, arrival_show)` pour une tournée donnée.

    `origin_venue`/`destination_venue` sont les lieux des PREMIER et DERNIER
    arrêts (les arrêts intermédiaires ne bornent rien — voir la note de
    module, 2026-08-04). Le spectacle connu (`show`, toujours renseigné) est
    le point d'ancrage : s'il se joue au lieu d'arrivée, il EST le spectacle
    d'arrivée (l'ancienne « livraison ») ; s'il se joue au lieu de départ, il
    EST le spectacle de départ (l'ancien « ramassage ») — c'est ce test de
    lieu qui remplace le champ `transport_type`, retiré le 2026-08-04. Dans
    les deux cas l'autre bout est déduit par `find_departure_show`/
    `find_arrival_show` à partir de la fenêtre effective de `show`, PAS de
    `scheduled_datetime` (souvent encore vide pour une proposition
    'to_approve'). Si le spectacle ne se joue à aucun des deux bouts (il est
    desservi par un arrêt intermédiaire), les deux bouts sont déduits autour
    de sa fenêtre.
    """
    if show is None:
        return None, None
    if destination_venue is not None and show.venue_id == destination_venue.id:
        arrival_show = show
        departure_show = find_departure_show(
            origin_venue, before_datetime=show.effective_start, exclude_show_id=show.id,
        )
        return departure_show, arrival_show
    if origin_venue is not None and show.venue_id == origin_venue.id:
        departure_show = show
        arrival_show = find_arrival_show(
            destination_venue, after_datetime=show.effective_end, exclude_show_id=show.id,
        )
        return departure_show, arrival_show
    departure_show = find_departure_show(
        origin_venue, before_datetime=show.effective_start, exclude_show_id=show.id,
    )
    arrival_show = find_arrival_show(
        destination_venue, after_datetime=show.effective_end, exclude_show_id=show.id,
    )
    return departure_show, arrival_show


def validate_transport_window(show, origin_venue, destination_venue, scheduled_datetime, duration_minutes):
    """Vérifie qu'une tournée (fenêtre `[scheduled_datetime, scheduled_datetime
    + duration_minutes]`, du départ du premier arrêt à l'arrivée au dernier) a
    bien lieu ENTRE la fin effective du spectacle de départ et le début
    effectif du spectacle d'arrivée (décision Samuel du 2026-07-30 — voir note
    de module). Retourne `None` si la fenêtre est valide (ou si aucune borne
    ne s'applique des deux côtés — ex. entrepôt), sinon un dict `{'detail':
    ..., 'departure_show': ..., 'arrival_show': ...}` prêt à être renvoyé par
    le serializer.
    """
    if scheduled_datetime is None or duration_minutes is None:
        return None

    departure_show, arrival_show = get_transport_reference_shows(show, origin_venue, destination_venue)
    transport_end = scheduled_datetime + timedelta(minutes=duration_minutes)

    if departure_show is not None and scheduled_datetime < departure_show.effective_end:
        return {
            'detail': (
                f"Ce déplacement est prévu avant la fin de « {departure_show.display_title} » "
                f"({departure_show.effective_end:%Y-%m-%d %H:%M}, buffer inclus) — le matériel "
                "n'est pas encore disponible à ce moment."
            ),
            'departure_show': serialize_reference_show(departure_show),
            'arrival_show': serialize_reference_show(arrival_show),
        }
    if arrival_show is not None and transport_end > arrival_show.effective_start:
        return {
            'detail': (
                f"Ce déplacement se termine après le début de « {arrival_show.display_title} » "
                f"({arrival_show.effective_start:%Y-%m-%d %H:%M}, buffer inclus) — le matériel "
                "n'arriverait pas à temps."
            ),
            'departure_show': serialize_reference_show(departure_show),
            'arrival_show': serialize_reference_show(arrival_show),
        }
    return None


def serialize_reference_show(show):
    """Représentation compacte d'un spectacle de référence (départ/arrivée
    d'un déplacement) — `None` si non applicable (ex. entrepôt).

    `engagement_start`/`engagement_end` sont inclus en plus de
    `effective_start`/`effective_end` : la fiche transport affiche, côté
    arrivée, le début du bloc complet (montage compris) plutôt que le seul
    début de l'événement — voir la note du 2026-08-02 dans CLAUDE.md.
    """
    if show is None:
        return None
    return {
        'id': show.id,
        'title': show.display_title,
        'effective_start': show.effective_start,
        'effective_end': show.effective_end,
        'engagement_start': show.engagement_start,
        'engagement_end': show.engagement_end,
    }


def serialize_material_conflict(show_material):
    """Représentation compacte d'un `ShowMaterial` en conflit, pour la réponse API."""
    sm = show_material
    return {
        'type': 'show_material',
        'show_material_id': sm.id,
        'show_id': sm.show_id,
        'show_title': sm.show.display_title,
        'show_start': sm.show.start_datetime,
        'show_end': sm.show.end_datetime,
        'material_id': sm.material_id,
        'material_name': sm.material.name,
    }


def serialize_venue_conflict(show):
    """Représentation compacte d'un `Show` en conflit de lieu, pour la réponse API."""
    return {
        'type': 'show',
        'show_id': show.id,
        'show_title': show.display_title,
        'show_start': show.start_datetime,
        'show_end': show.end_datetime,
        'venue_id': show.venue_id,
        # Nom du lieu, ajouté le 2026-07-30 pour l'écran « Conflits » (vue
        # project-wide) : les deux côtés d'un conflit de lieu partagent
        # toujours le même lieu, utile à afficher sans requête supplémentaire.
        'venue_name': show.venue.name,
    }


def _technician_conflict_object_key(obj):
    """Clé stable pour dédupliquer une paire de conflit technicien, peu
    importe le type d'engagement (`ShowTechnician` ou `TransportTechnician`) —
    voir `get_project_conflicts`."""
    if isinstance(obj, ShowTechnician):
        return ('show_technician', obj.id)
    # Depuis le 2026-07-30 l'engagement est le couple (transport, technicien) :
    # deux personnes sur le même déplacement sont deux engagements distincts,
    # et donc deux conflits distincts s'ils chevauchent chacun autre chose.
    return ('transport_technician', obj.id)


def get_project_conflicts(project):
    """Agrège et déduplique tous les conflits (lieu, matériel, technicien) du
    projet entier, pour l'écran « Conflits » (ConflitDetail.dc.html porté en
    vue d'ensemble plutôt qu'un chevauchement précis — ajouté le 2026-07-30).

    `ShowViewSet.conflicts` (ci-dessus dans views.py) répond à l'échelle d'un
    seul spectacle et peut donc renvoyer la « même » paire deux fois (vue du
    côté A puis du côté B) si on l'appelait pour chaque spectacle du projet.
    Ici chaque paire n'apparaît qu'une seule fois, peu importe de quel côté
    elle a été détectée en premier, via une clé de dédoublonnage par
    frozenset des ids des deux objets impliqués.

    Retourne un dict à trois clés (`venue_conflicts`, `material_conflicts`,
    `technician_conflicts`), chaque entrée étant `{'a': ..., 'b': ...}` — les
    deux côtés du conflit, sérialisés avec les fonctions `serialize_*`
    existantes, pour que le frontend affiche la comparaison sans requête
    supplémentaire.
    """
    shows = list(Show.objects.filter(project_id=project.id).select_related('venue'))
    shows_by_id = {s.id: s for s in shows}

    seen_venue_pairs = set()
    venue_conflicts = []
    for show in shows:
        others = get_venue_conflicts(
            show.venue, show.effective_start, show.effective_end,
            exclude_id=show.id, exclude_family_ids=show.family_ids,
        )
        for other in others:
            if other.id not in shows_by_id:
                continue
            key = frozenset({show.id, other.id})
            if key in seen_venue_pairs:
                continue
            seen_venue_pairs.add(key)
            venue_conflicts.append({
                'a': serialize_venue_conflict(show),
                'b': serialize_venue_conflict(other),
            })

    show_materials = list(
        ShowMaterial.objects.filter(show__project_id=project.id)
        .select_related('show', 'material', 'show__venue')
    )
    seen_material_pairs = set()
    material_conflicts = []
    for sm in show_materials:
        others = get_material_conflicts(sm.show, sm.material, exclude_id=sm.id, quantity=sm.quantity)
        for other in others:
            key = frozenset({sm.id, other.id})
            if key in seen_material_pairs:
                continue
            seen_material_pairs.add(key)
            material_conflicts.append({
                'a': serialize_material_conflict(sm),
                'b': serialize_material_conflict(other),
            })

    show_technicians = list(
        ShowTechnician.objects.filter(show__project_id=project.id).select_related('show', 'technician')
    )
    transport_technicians = list(
        TransportTechnician.objects
        .filter(transport__show__project_id=project.id, transport__scheduled_datetime__isnull=False)
        .select_related('transport', 'transport__show', 'technician')
        .prefetch_related('transport__stops')
    )
    seen_tech_pairs = set()
    technician_conflicts = []

    for st in show_technicians:
        others = get_technician_conflicts(st.show, st.technician, exclude_id=st.id)
        for other in others:
            key = frozenset({_technician_conflict_object_key(st), _technician_conflict_object_key(other)})
            if key in seen_tech_pairs:
                continue
            seen_tech_pairs.add(key)
            technician_conflicts.append({
                'a': serialize_technician_conflict(st),
                'b': serialize_technician_conflict(other),
            })

    for tt in transport_technicians:
        transport = tt.transport
        others = get_transport_conflicts(
            transport.scheduled_datetime,
            transport.total_duration_minutes,
            tt.technician,
            exclude_id=transport.id,
        )
        for other in others:
            key = frozenset({_technician_conflict_object_key(tt), _technician_conflict_object_key(other)})
            if key in seen_tech_pairs:
                continue
            seen_tech_pairs.add(key)
            technician_conflicts.append({
                'a': serialize_technician_conflict(tt),
                'b': serialize_technician_conflict(other),
            })

    return {
        'venue_conflicts': venue_conflicts,
        'material_conflicts': material_conflicts,
        'technician_conflicts': technician_conflicts,
    }


def serialize_technician_conflict(obj):
    """Représentation compacte d'un conflit technicien, pour la réponse API.

    `obj` peut être un `ShowTechnician` (assignation à un spectacle) ou un
    `TransportTechnician` (affectation à un déplacement) — les deux sont
    croisés ensemble par `get_technician_conflicts`/`get_transport_conflicts`.

    Le type reste `'transport'` côté API malgré le passage à la table de
    liaison le 2026-07-30 : c'est bien un déplacement que le frontend affiche,
    la clé `transport_id` pointe toujours la fiche à ouvrir.
    """
    if isinstance(obj, TransportTechnician):
        transport = obj.transport
        return {
            'type': 'transport',
            'transport_id': transport.id,
            'show_id': transport.show_id,
            'show_title': transport.show.display_title,
            'scheduled_datetime': transport.scheduled_datetime,
            # La clé garde son nom historique pour le frontend, mais c'est la
            # durée TOTALE de la tournée (somme des segments — 2026-08-04).
            'estimated_duration_minutes': transport.total_duration_minutes,
            'technician_id': obj.technician_id,
            'technician_name': obj.technician.name,
        }

    st = obj
    return {
        'type': 'show_technician',
        'show_technician_id': st.id,
        'show_id': st.show_id,
        'show_title': st.show.display_title,
        'show_start': st.show.start_datetime,
        'show_end': st.show.end_datetime,
        'technician_id': st.technician_id,
        'technician_name': st.technician.name,
    }

"""
Cohérence des emplacements de matériel — module transport (ajouté le 2026-07-24
à la demande de Samuel). Complémentaire à `conflicts.py` : là où `conflicts.py`
vérifie les chevauchements d'horaire (capacité/techniciens), ce module-ci
vérifie la cohérence SPATIALE du matériel dans le temps.

Deux questions auxquelles il répond, toutes deux non bloquantes (rapport à la
demande, jamais un refus 400 — décision Samuel du 2026-07-24) :

1. « Tout est-il possible sur les emplacements prévus ? » — chaque `Transport`
   prétend transporter du matériel (via `TransportMaterial`) depuis un lieu de
   départ. On vérifie que ce matériel s'y trouve réellement au moment du départ,
   compte tenu de son point de départ (le lieu d'entreposage `Material.venue`)
   et des transports antérieurs qui l'ont éventuellement déjà déplacé. Sinon →
   `origine_incoherente`.

2. « Tout déplacement de matériel est-il associé à un transport ? » — chaque
   assignation de matériel à un spectacle (`ShowMaterial`) requiert que le
   matériel soit présent au lieu du spectacle à l'heure voulue. Si le matériel
   n'y est pas (jamais livré, ou pas en quantité suffisante) → `materiel_non_livre`.

Modèle de suivi (timeline par matériel) — un « grand livre » de positions :
- Position de départ : `Material.quantity` unités au lieu d'entreposage
  `Material.venue` (le « bercail »). Si `Material.venue` est vide, l'origine est
  inconnue et on ne peut rien vérifier → une seule issue `origine_inconnue` par
  matériel, plutôt que d'inonder le rapport de faux positifs.
- Chaque `Transport` transportant q unités du lieu O au lieu D déplace q unités
  de O vers D. Un transport est considéré « arrivé » (matériel présent à
  destination) à la fin de sa fenêtre : `effective_end` = scheduled_datetime +
  estimated_duration_minutes (voir Transport). C'est donc `effective_end` qui
  fait foi pour décider si le matériel est déjà en place à un instant donné.

Portée assumée (décision Samuel du 2026-07-24) : ALLER SEULEMENT. On ne vérifie
que la présence du matériel là où il est requis (livraisons) ; on ne contrôle
pas qu'un ramassage (`pickup`) le ramène à son entrepôt d'origine. Un `pickup`
est tout de même pris en compte dans la timeline comme n'importe quel
déplacement (il fait bouger du matériel), simplement on n'exige pas de boucle
de retour fermée.

Exemption d'entreposage : un `ShowMaterial` rattaché à un `Show` dont le venue
est un entrepôt (`venue.is_storage=True`) n'exige aucune livraison — le matériel
qui « dort » à l'entrepôt est réputé disponible, cohérent avec l'exemption déjà
appliquée dans `conflicts.py`.
"""

from .models import Material, ShowMaterial, Transport, TransportMaterial


def _material_events(material):
    """Événements de déplacement d'un matériel, triés chronologiquement.

    Un événement = un dict décrivant un `Transport` qui transporte `material` :
    l'objet transport, son heure de départ (`scheduled`), sa fin de fenêtre
    (`effective_end`, = arrivée), les lieux d'origine/destination et la quantité.
    Trié par `effective_end` (ordre dans lequel le matériel « arrive » quelque
    part), ce qui est l'ordre pertinent pour reconstruire les positions.
    """
    # Timeline AUTORITATIVE : seuls les transports confirmés ET horodatés
    # comptent comme des déplacements réels. Une proposition auto
    # ('to_approve', ou sans heure) ne « livre » rien tant qu'elle n'est pas
    # confirmée — décision Samuel du 2026-07-24 (l'alerte reste orange jusqu'à
    # confirmation).
    lines = (
        TransportMaterial.objects.filter(
            material=material,
            transport__status=Transport.STATUS_CONFIRMED,
            transport__scheduled_datetime__isnull=False,
        )
        .select_related('transport', 'transport__origin_venue', 'transport__destination_venue', 'transport__show')
    )
    events = []
    for line in lines:
        transport = line.transport
        events.append({
            'transport': transport,
            'scheduled': transport.scheduled_datetime,
            'effective_end': transport.effective_end,
            'origin_id': transport.origin_venue_id,
            'destination_id': transport.destination_venue_id,
            'quantity': line.quantity,
        })
    events.sort(key=lambda event: event['effective_end'])
    return events


def _ledger_before(events, cutoff, home_venue_id, total_quantity):
    """Positions du matériel (dict `venue_id -> quantité`) telles qu'établies
    juste avant l'instant `cutoff`.

    On part de `total_quantity` unités au lieu d'entreposage `home_venue_id`,
    puis on applique tous les transports déjà « arrivés » avant `cutoff`
    (`effective_end <= cutoff`) : chacun retire sa quantité de son origine et
    l'ajoute à sa destination. Un transport encore « en route » à `cutoff`
    (pas encore arrivé) n'est pas appliqué — son matériel n'est ni parti (au
    sens comptable, on le décompte au départ) ni arrivé pour l'instant.

    Note : le retrait à l'origine se fait à l'`effective_end` comme l'ajout à
    la destination — on modélise le déplacement comme atomique à l'arrivée.
    Cela suffit pour le niveau de vérification visé (présence/absence, quantité
    disponible) sans introduire un état « en transit » séparé.
    """
    ledger = {}
    if home_venue_id is not None:
        ledger[home_venue_id] = total_quantity
    for event in events:
        if event['effective_end'] <= cutoff:
            ledger[event['origin_id']] = ledger.get(event['origin_id'], 0) - event['quantity']
            ledger[event['destination_id']] = ledger.get(event['destination_id'], 0) + event['quantity']
    return ledger


def get_material_coherence_issues(material):
    """Liste des incohérences d'emplacement pour un `material` donné.

    Retourne une liste de dicts (voir les `serialize_*` ci-dessous). Vide si
    tout est cohérent. Trois types possibles : `origine_inconnue` (le matériel
    n'a pas de lieu d'entreposage, impossible à suivre), `origine_incoherente`
    (un transport part d'un lieu où le matériel n'est pas disponible en quantité
    suffisante) et `materiel_non_livre` (un spectacle requiert le matériel à un
    lieu où il n'est pas présent).
    """
    home_venue_id = material.venue_id
    total_quantity = material.quantity
    events = _material_events(material)

    # Sans lieu d'entreposage, la position de départ est inconnue : toute
    # vérification produirait des faux positifs. On signale ce cas une seule
    # fois — mais uniquement s'il y a quelque chose à suivre (au moins un
    # transport ou une assignation), sinon rien à signaler.
    if home_venue_id is None:
        has_transport = bool(events)
        has_assignment = ShowMaterial.objects.filter(material=material).exists()
        if has_transport or has_assignment:
            return [_serialize_unknown_home(material)]
        return []

    issues = []

    # 1. Origines incohérentes — chaque transport doit trouver son matériel au départ.
    for event in events:
        ledger = _ledger_before(events, event['scheduled'], home_venue_id, total_quantity)
        available = ledger.get(event['origin_id'], 0)
        if available < event['quantity']:
            issues.append(_serialize_origin_issue(material, event, available))

    # 2. Matériel non livré — chaque spectacle doit trouver son matériel sur place.
    show_materials = (
        ShowMaterial.objects.filter(material=material)
        .select_related('show', 'show__venue')
    )
    for show_material in show_materials:
        show = show_material.show
        # Exemption d'entreposage : ranger du matériel n'exige aucune livraison.
        if show.venue.is_storage:
            continue
        ledger = _ledger_before(events, show.effective_start, home_venue_id, total_quantity)
        present = ledger.get(show.venue_id, 0)
        if present < show_material.quantity:
            proposal = _pending_proposal_for(material, show)
            issues.append(_serialize_missing_issue(material, show_material, present, proposal))

    return issues


def _pending_proposal_for(material, show):
    """Proposition auto ('to_approve') en attente qui couvrirait la livraison de
    `material` à `show`, s'il en existe une (voir `transport_autogen.py`). Sert
    à distinguer un déplacement manquant SANS proposition (rouge) d'un
    déplacement couvert par une proposition à compléter (orange)."""
    return (
        Transport.objects.filter(
            status=Transport.STATUS_TO_APPROVE,
            show=show,
            destination_venue_id=show.venue_id,
            transport_materials__material=material,
        )
        .first()
    )


def get_project_coherence_report(project):
    """Rapport de cohérence pour toute une production : concatène les issues de
    chaque matériel du projet. Non bloquant — usage : `GET
    /api/projects/{id}/transport_coherence/`."""
    issues = []
    for material in Material.objects.filter(project=project).select_related('venue'):
        issues += get_material_coherence_issues(material)
    return issues


def get_show_coherence_report(show):
    """Rapport de cohérence centré sur un spectacle : ne garde que les issues
    qui le concernent — matériel requis par CE spectacle mais non livré,
    transports de CE spectacle dont l'origine est incohérente, et matériel de ce
    spectacle sans lieu d'entreposage.

    La timeline d'un matériel est calculée sur tout le projet (un matériel se
    déplace entre plusieurs spectacles), mais on filtre le résultat sur ce
    spectacle pour un affichage ciblé, comme `GET /api/shows/{id}/conflicts/`.
    Usage : `GET /api/shows/{id}/transport_coherence/`.
    """
    material_ids = set(show.show_materials.values_list('material_id', flat=True))
    material_ids |= set(
        TransportMaterial.objects.filter(transport__show=show).values_list('material_id', flat=True)
    )

    issues = []
    for material in Material.objects.filter(id__in=material_ids).select_related('venue'):
        for issue in get_material_coherence_issues(material):
            # `origine_inconnue` est propre au matériel (pas à un spectacle) : on
            # la garde dès que ce matériel touche ce spectacle. Les deux autres
            # types portent un `show_id` — on ne garde que celles de ce spectacle.
            if issue['type'] == 'origine_inconnue' or issue.get('show_id') == show.id:
                issues.append(issue)
    return issues


def _serialize_unknown_home(material):
    """Issue : matériel sans lieu d'entreposage, position de départ inconnue."""
    return {
        'type': 'origine_inconnue',
        'material_id': material.id,
        'material_name': material.name,
        'show_id': None,
        'detail': (
            "Ce matériel n'a pas de lieu d'entreposage (venue) défini : impossible "
            "de vérifier ses déplacements tant que sa position de départ est inconnue."
        ),
    }


def _serialize_origin_issue(material, event, available):
    """Issue : un transport part d'un lieu où le matériel n'est pas (assez) présent."""
    transport = event['transport']
    return {
        'type': 'origine_incoherente',
        'transport_id': transport.id,
        'transport_type': transport.transport_type,
        'scheduled_datetime': transport.scheduled_datetime,
        'show_id': transport.show_id,
        'show_title': transport.show.title,
        'material_id': material.id,
        'material_name': material.name,
        'origin_venue_id': transport.origin_venue_id,
        'origin_venue_name': transport.origin_venue.name,
        'quantite_demandee': event['quantity'],
        'quantite_disponible': max(available, 0),
        'detail': (
            f"Le déplacement prévu à {transport.scheduled_datetime:%Y-%m-%d %H:%M} "
            f"prétend transporter {event['quantity']} × « {material.name} » depuis "
            f"« {transport.origin_venue.name} », mais seulement {max(available, 0)} y "
            f"est/sont disponible(s) à ce moment (aucun transport antérieur ne l'y amène)."
        ),
    }


def _serialize_missing_issue(material, show_material, present, proposal=None):
    """Issue : un spectacle requiert du matériel non présent sur place à l'heure voulue.

    `etat` distingue deux situations visuelles :
    - 'propose' (orange) : une proposition auto en attente couvre le
      déplacement, il reste à la compléter (heure/technicien) et l'approuver.
    - 'manquant' (rouge) : aucun transport, même proposé, ne couvre le
      déplacement.
    `proposal_transport_id` pointe vers la proposition à compléter, le cas échéant.
    """
    show = show_material.show
    etat = 'propose' if proposal is not None else 'manquant'
    return {
        'type': 'materiel_non_livre',
        'etat': etat,
        'proposal_transport_id': proposal.id if proposal is not None else None,
        'show_material_id': show_material.id,
        'show_id': show.id,
        'show_title': show.title,
        'show_start': show.start_datetime,
        'venue_id': show.venue_id,
        'venue_name': show.venue.name,
        'material_id': material.id,
        'material_name': material.name,
        'quantite_requise': show_material.quantity,
        'quantite_presente': max(present, 0),
        'detail': (
            f"« {show.title} » requiert {show_material.quantity} × « {material.name} » "
            f"à « {show.venue.name} », mais seulement {max(present, 0)} y est/sont "
            f"présent(s) au début de la fenêtre : "
            + (
                "une proposition de transport à approuver couvre ce déplacement."
                if proposal is not None
                else "aucun transport ne l'y amène en quantité suffisante."
            )
        ),
    }

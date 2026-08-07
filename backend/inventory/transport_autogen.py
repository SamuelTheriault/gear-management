"""
Génération automatique des propositions de transport — module transport
(ajouté le 2026-07-24 à la demande de Samuel).

Principe : dès que du matériel est requis à un lieu où rien ne l'amène (un
« déplacement de matériel » non couvert), l'app crée automatiquement un
`Transport` en mode « à approuver » (`status='to_approve'`), pré-rempli avec
ce qu'on peut déduire — lieu de départ (dernière position connue du matériel),
lieu d'arrivée (le lieu du spectacle) et matériel transporté. Ce qu'on ne peut
PAS déduire (heure du déplacement, technicien) reste vide : l'utilisateur
complète puis confirme la proposition (`status='confirmed'`), ce qui la fait
passer de l'orange au vert.

Déclenchement : automatique, par signaux (voir `regenerate_signals.py`), à
chaque changement pertinent (assignation de matériel, transport confirmé,
horaire/lieu d'un spectacle). Décision Samuel du 2026-07-24 :
- automatique à chaque assignation (pas un bouton à la demande) ;
- pas de mémoire de rejet : chaque régénération recalcule l'ensemble des
  propositions nécessaires (on ne conserve pas trace d'une proposition
  écartée — elle réapparaîtra si le besoin est toujours là) ;
- une proposition ne « livre » rien tant qu'elle n'est pas confirmée : elle
  n'entre donc pas dans la timeline de position (voir `transport_coherence.py`)
  et le déplacement reste signalé en orange jusqu'à confirmation.

Position du matériel (timeline projetée) : départ au lieu d'entreposage
(`Material.venue`), puis application des transports CONFIRMÉS et, au fil du
calcul, des propositions qu'on génère (pour que l'origine du 2e déplacement
soit la destination du 1er — chaînage entrepôt→A puis A→B, pas entrepôt→B).

Idempotence : la régénération est un *resync* des seules propositions
`to_approve` d'un projet — les propositions encore nécessaires sont conservées
(on préserve la ligne, donc une heure/un technicien éventuellement déjà
saisis), celles devenues inutiles sont supprimées, les nouvelles sont créées.
Les transports confirmés ne sont JAMAIS touchés. Un déplacement déjà couvert
par un transport confirmé (même mal chronométré — c'est au rapport de
cohérence de le signaler) n'est pas reproposé.
"""

import threading

from django.db import transaction

from .models import Material, ShowMaterial, Transport, TransportMaterial, TransportStop

try:  # estimation optionnelle de durée (dégradation silencieuse — voir maps.py)
    from .maps import estimate_travel_minutes
except Exception:  # pragma: no cover - maps importe toujours, garde de robustesse
    def estimate_travel_minutes(origin, destination):
        """Repli si `maps` est indisponible — pas d'estimation."""
        return None


# Garde de réentrance : la régénération crée/supprime des Transport et
# TransportMaterial, ce qui redéclencherait les signaux. Ce drapeau (par
# thread) neutralise les signaux pendant qu'une régénération est en cours.
_state = threading.local()


def is_regenerating():
    """True si une régénération est en cours dans ce thread (les signaux doivent
    alors s'abstenir — voir `regenerate_signals.py`)."""
    return getattr(_state, 'active', False)


def _confirmed_material_events(material):
    """Déplacements CONFIRMÉS et horodatés transportant `material`, triés par
    heure d'arrivée (`effective_end`). Base de la timeline de position.

    Tournées multi-arrêts (2026-08-04) : l'unité est la LIGNE de matériel —
    origine = lieu de son arrêt de chargement, destination = lieu de son arrêt
    de déchargement, arrivée = arrivée de la tournée à ce dernier (même
    logique que `transport_coherence._material_events`).
    """
    lines = (
        TransportMaterial.objects.filter(
            material=material,
            transport__status=Transport.STATUS_CONFIRMED,
            transport__scheduled_datetime__isnull=False,
        )
        .select_related('transport', 'load_stop', 'unload_stop')
        .prefetch_related('transport__stops')
    )
    events = []
    for line in lines:
        transport = line.transport
        events.append({
            'effective_end': transport.arrival_at(line.unload_stop),
            'origin_id': line.load_stop.venue_id,
            'destination_id': line.unload_stop.venue_id,
            'quantity': line.quantity,
        })
    events.sort(key=lambda event: event['effective_end'])
    return events


def _pick_origin(ledger, exclude_venue_id, home_venue_id):
    """Choisit le lieu de départ d'un déplacement proposé : le lieu (≠ destination)
    qui détient le plus d'unités du matériel dans la position projetée. Repli sur
    le lieu d'entreposage si aucun autre lieu n'en détient."""
    best_venue_id = None
    best_qty = 0
    for venue_id, qty in ledger.items():
        if venue_id == exclude_venue_id:
            continue
        if qty > best_qty:
            best_qty = qty
            best_venue_id = venue_id
    if best_venue_id is None:
        return home_venue_id
    return best_venue_id


def _needed_moves_for_material(material, confirmed_cover):
    """Liste des déplacements à proposer pour `material` : dicts
    `{origin_id, show, quantity}`.

    Parcourt les assignations du matériel (spectacles non-entrepôt) dans l'ordre
    chronologique, en maintenant une position projetée (entrepôt de départ +
    transports confirmés + propositions déjà décidées ici). Pour chaque
    spectacle où le matériel manque, propose de combler le déficit depuis la
    meilleure origine, et met à jour la position projetée comme si le
    déplacement avait lieu (chaînage des origines).

    `confirmed_cover` : ensemble `{(show_id, material_id)}` déjà couvert par un
    transport confirmé — on ne repropose pas un déplacement déjà pris en charge
    (le rapport de cohérence se charge de signaler un éventuel problème
    d'horaire/quantité sur ces transports confirmés).
    """
    home_venue_id = material.venue_id
    if home_venue_id is None:
        # Sans lieu d'entreposage, position de départ inconnue : on ne génère
        # rien (le rapport de cohérence signale `origine_inconnue`).
        return []

    events = _confirmed_material_events(material)
    show_materials = (
        ShowMaterial.objects.filter(material=material)
        .select_related('show', 'show__venue')
        .order_by()
    )
    # Tri chronologique sur la fenêtre effective (buffers inclus), en excluant
    # les spectacles d'entrepôt (exemption d'entreposage — rien à livrer).
    assignments = sorted(
        (sm for sm in show_materials if not sm.show.venue.is_storage),
        key=lambda sm: sm.show.effective_start,
    )

    ledger = {home_venue_id: material.quantity}
    event_index = 0
    moves = []
    for show_material in assignments:
        show = show_material.show
        cutoff = show.effective_start
        # Applique les transports confirmés déjà arrivés avant ce spectacle.
        while event_index < len(events) and events[event_index]['effective_end'] <= cutoff:
            event = events[event_index]
            ledger[event['origin_id']] = ledger.get(event['origin_id'], 0) - event['quantity']
            ledger[event['destination_id']] = ledger.get(event['destination_id'], 0) + event['quantity']
            event_index += 1

        present = ledger.get(show.venue_id, 0)
        shortfall = show_material.quantity - present
        if shortfall <= 0:
            continue
        if (show.id, material.id) in confirmed_cover:
            # Un transport confirmé dessert déjà ce matériel pour ce spectacle —
            # on ne propose pas de doublon. On projette tout de même l'arrivée
            # pour le chaînage des spectacles suivants.
            ledger[show.venue_id] = ledger.get(show.venue_id, 0) + shortfall
            continue

        origin_id = _pick_origin(ledger, exclude_venue_id=show.venue_id, home_venue_id=home_venue_id)
        moves.append({'origin_id': origin_id, 'show': show, 'quantity': shortfall})
        # Projette le déplacement proposé (chaînage des origines).
        ledger[origin_id] = ledger.get(origin_id, 0) - shortfall
        ledger[show.venue_id] = ledger.get(show.venue_id, 0) + shortfall

    return moves


def _build_confirmed_cover(project):
    """Ensemble `{(show_id, material_id)}` des livraisons déjà couvertes par un
    transport confirmé.

    Tournées (2026-08-04) : la livraison est couverte si la LIGNE de ce
    matériel décharge au lieu du spectacle desservi — pas la destination
    finale de la tournée, qui peut continuer vers d'autres arrêts.
    """
    cover = set()
    lines = (
        TransportMaterial.objects.filter(
            transport__status=Transport.STATUS_CONFIRMED,
            transport__project=project,
        )
        .select_related('transport', 'transport__show', 'unload_stop')
    )
    for line in lines:
        transport = line.transport
        # Une tournée « sans spectacle » (2026-08-06) ne couvre aucune
        # livraison au sens de l'autogen — rien à ajouter.
        if transport.show_id is not None and line.unload_stop.venue_id == transport.show.venue_id:
            cover.add((transport.show_id, line.material_id))
    return cover


def regenerate_project_proposals(project):
    """Recalcule et resynchronise les propositions de transport (`to_approve`)
    d'un projet.

    Idempotent : à besoin identique, l'état final est identique. Ne touche
    jamais aux transports confirmés. Renvoie un dict de compteurs
    `{'created', 'updated', 'deleted'}` (utile pour les tests/diagnostic).
    """
    if is_regenerating():
        # Sécurité : jamais de régénération imbriquée (les écritures ci-dessous
        # redéclencheraient les signaux).
        return {'created': 0, 'updated': 0, 'deleted': 0}

    _state.active = True
    try:
        with transaction.atomic():
            confirmed_cover = _build_confirmed_cover(project)

            # 1. Déplacements souhaités, groupés par (show_id, origin_venue_id).
            desired = {}
            for material in Material.objects.filter(project=project).select_related('venue'):
                for move in _needed_moves_for_material(material, confirmed_cover):
                    key = (move['show'].id, move['origin_id'])
                    group = desired.setdefault(key, {'show': move['show'], 'origin_id': move['origin_id'], 'lines': {}})
                    group['lines'][material.id] = move['quantity']

            # 2. Propositions existantes du projet, indexées par la même clé.
            # `origin_venue` est dérivé du premier arrêt depuis la refonte en
            # tournées (2026-08-04) — d'où le prefetch des arrêts.
            existing = {}
            existing_qs = (
                Transport.objects.filter(status=Transport.STATUS_TO_APPROVE, project=project)
                .select_related('show')
                .prefetch_related('stops')
            )
            for transport in existing_qs:
                first_stop = transport.first_stop
                origin_id = first_stop.venue_id if first_stop is not None else None
                existing[(transport.show_id, origin_id)] = transport

            counts = {'created': 0, 'updated': 0, 'deleted': 0}

            # 3. Supprime les propositions devenues inutiles.
            for key, transport in existing.items():
                if key not in desired:
                    transport.delete()
                    counts['deleted'] += 1

            # 4. Crée/actualise les propositions souhaitées — des tournées
            # simples à 2 arrêts (origine → lieu du spectacle). Fusionner des
            # propositions en une vraie tournée multi-arrêts reste une action
            # manuelle de Samuel (décision du 2026-08-04, phase ultérieure).
            for key, group in desired.items():
                show = group['show']
                origin_id = group['origin_id']
                transport = existing.get(key)
                if transport is None:
                    duration = estimate_travel_minutes_by_id(origin_id, show.venue_id)
                    if duration is None:
                        from .models import Settings
                        duration = Settings.load().default_transport_duration_minutes
                    transport = Transport.objects.create(
                        project=show.project,
                        show=show,
                        status=Transport.STATUS_TO_APPROVE,
                        scheduled_datetime=None,
                    )
                    TransportStop.objects.create(
                        transport=transport, venue_id=origin_id, order=0,
                        travel_minutes_from_previous=0,
                    )
                    TransportStop.objects.create(
                        transport=transport, venue_id=show.venue_id, order=1,
                        travel_minutes_from_previous=duration,
                    )
                    counts['created'] += 1
                else:
                    # Conserve la ligne (et l'heure/technicien éventuellement déjà
                    # saisis) ; on ne fait que resynchroniser le matériel transporté.
                    counts['updated'] += 1
                _sync_transport_lines(transport, group['lines'])

            return counts
    finally:
        _state.active = False


def estimate_travel_minutes_by_id(origin_venue_id, destination_venue_id):
    """Estime la durée de trajet entre deux lieux (par id) via `maps`, ou None
    si non estimable (coordonnées manquantes, clé absente, erreur réseau)."""
    from .models import Venue
    try:
        origin = Venue.objects.get(id=origin_venue_id)
        destination = Venue.objects.get(id=destination_venue_id)
    except Venue.DoesNotExist:
        return None
    return estimate_travel_minutes(origin, destination)


def _sync_transport_lines(transport, desired_lines):
    """Aligne les lignes `TransportMaterial` d'un transport sur `desired_lines`
    (`{material_id: quantity}`) : met à jour les quantités, ajoute le manquant,
    supprime le superflu.

    Tournées (2026-08-04) : les lignes d'une proposition couvrent toujours la
    tournée entière — chargement au premier arrêt, déchargement au dernier.
    Si Samuel a ajouté des arrêts intermédiaires à une proposition avant de la
    confirmer, le resync réaligne quand même chargement/déchargement sur les
    extrémités : une proposition ne dessert qu'UN spectacle (sa raison
    d'être), le découpage fin par arrêt est un geste manuel post-confirmation.
    """
    first_stop = transport.first_stop
    last_stop = transport.last_stop
    existing = {line.material_id: line for line in transport.transport_materials.all()}
    for material_id, quantity in desired_lines.items():
        line = existing.get(material_id)
        if line is None:
            TransportMaterial.objects.create(
                transport=transport, material_id=material_id, quantity=quantity,
                load_stop=first_stop, unload_stop=last_stop,
            )
        else:
            update_fields = []
            if line.quantity != quantity:
                line.quantity = quantity
                update_fields.append('quantity')
            if line.load_stop_id != first_stop.id:
                line.load_stop = first_stop
                update_fields.append('load_stop')
            if line.unload_stop_id != last_stop.id:
                line.unload_stop = last_stop
                update_fields.append('unload_stop')
            if update_fields:
                line.save(update_fields=update_fields)
    for material_id, line in existing.items():
        if material_id not in desired_lines:
            line.delete()

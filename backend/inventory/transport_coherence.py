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
- Depuis la refonte en tournées multi-arrêts (2026-08-04), l'unité de
  déplacement est la LIGNE de matériel (`TransportMaterial`), pas la tournée :
  chaque ligne déplace q unités du lieu de son arrêt de chargement
  (`load_stop`) vers celui de son arrêt de déchargement (`unload_stop`). Le
  matériel quitte son origine à l'ARRIVÉE de la tournée à l'arrêt de
  chargement (`Transport.arrival_at(load_stop)` — c'est là qu'il monte dans le
  camion, il doit y être disponible à cet instant) et est considéré « arrivé »
  à destination à l'arrivée à l'arrêt de déchargement. Pour une tournée à 2
  arrêts (le cas migré depuis l'ancien modèle A → B), ces deux instants sont
  exactement l'ancien couple `scheduled_datetime`/`effective_end` — aucun
  changement de comportement.

3. « Tout est-il rentré à la fin ? » — ajouté le 2026-07-30 à la demande de
   Samuel. À la fin du projet (voir `get_project_horizon`), chaque matériel
   doit être revenu à son lieu d'origine (`Material.venue`) en totalité.
   Sinon → `retour_manquant`.

Portée (révisée le 2026-07-30) : la portée initiale était ALLER SEULEMENT —
on ne vérifiait que la présence du matériel là où il est requis (livraisons),
sans exiger qu'un ramassage (`pickup`) ferme la boucle. Le point 3 ci-dessus
revient partiellement là-dessus : on ne contrôle toujours pas qu'un `pickup`
précis existe pour chaque livraison, mais on vérifie le **résultat net** à la
fin du projet. Autrement dit : peu importe le chemin, tout doit être rentré au
bercail à l'horizon du projet.

Exemption d'entreposage : un `ShowMaterial` rattaché à un `Show` dont le venue
est un entrepôt (`venue.is_storage=True`) n'exige aucune livraison — le matériel
qui « dort » à l'entrepôt est réputé disponible, cohérent avec l'exemption déjà
appliquée dans `conflicts.py`.
"""

import heapq
from datetime import datetime, time, timedelta

from django.utils import timezone

from .models import Material, Show, ShowMaterial, Transport, TransportMaterial, Venue


def _material_events(material):
    """Événements de déplacement d'un matériel, triés chronologiquement.

    Un événement = un dict décrivant une LIGNE de tournée (`TransportMaterial`)
    qui transporte `material` : l'objet transport, l'instant où le matériel
    quitte son origine (`scheduled` = arrivée de la tournée à l'arrêt de
    chargement), l'instant où il est livré (`effective_end` = arrivée à
    l'arrêt de déchargement), les lieux de chargement/déchargement et la
    quantité. Trié par `effective_end` (ordre dans lequel le matériel
    « arrive » quelque part), ce qui est l'ordre pertinent pour reconstruire
    les positions.
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
        .select_related(
            'transport', 'transport__show',
            'load_stop__venue', 'unload_stop__venue',
        )
        # `arrival_at` cumule les segments de la tournée : le prefetch évite
        # une requête par ligne dans la boucle ci-dessous.
        .prefetch_related('transport__stops')
    )
    events = []
    for line in lines:
        transport = line.transport
        events.append({
            'transport': transport,
            'scheduled': transport.arrival_at(line.load_stop),
            'effective_end': transport.arrival_at(line.unload_stop),
            'origin_id': line.load_stop.venue_id,
            'origin_venue': line.load_stop.venue,
            'destination_id': line.unload_stop.venue_id,
            'destination_venue': line.unload_stop.venue,
            'quantity': line.quantity,
        })
    events.sort(key=lambda event: event['effective_end'])
    return events


def get_material_transports(material, window_start, window_end):
    """Portions de tournées **confirmées** qui déplacent `material`, dont la
    fenêtre croise `[window_start, window_end]` — ajouté le 2026-07-31 à la
    demande de Samuel, pour les superposer sur le Parcours Matériel (fenêtre
    du déplacement lui-même, pas seulement son arrivée comme
    `_material_events` le fait pour reconstruire les séjours).

    Depuis les tournées multi-arrêts (2026-08-04), chaque entrée est la
    PORTION de tournée qui concerne ce matériel : de son arrêt de chargement à
    son arrêt de déchargement — `origin_venue_*`/`destination_venue_*` et
    `start`/`end` portent sur cette portion, pas sur la tournée entière (le
    camion peut continuer sa route sans ce matériel à bord).

    Même filtre que `_material_events` (confirmé + horodaté seulement — une
    proposition à approuver n'a pas encore déplacé quoi que ce soit) mais
    retourne des dicts sérialisables directement, pas les objets `Transport`.
    """
    events = _material_events(material)
    resultats = []
    for event in events:
        if event['scheduled'] >= window_end or event['effective_end'] <= window_start:
            continue
        transport = event['transport']
        resultats.append({
            'transport_id': transport.id,
            'show_id': transport.show_id,
            # Tournée « sans spectacle » possible depuis le 2026-08-06.
            'show_title': transport.show.display_title if transport.show_id else None,
            'origin_venue_id': event['origin_id'],
            'origin_venue_name': event['origin_venue'].name,
            'destination_venue_id': event['destination_id'],
            'destination_venue_name': event['destination_venue'].name,
            'quantity': event['quantity'],
            'start': event['scheduled'],
            'end': event['effective_end'],
        })
    return resultats


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


def get_venue_material_availability(venue, at, project=None, exclude_transport=None):
    """Matériel physiquement présent au lieu `venue` à l'instant `at`.

    Ajouté le 2026-07-30 : la modale « ajouter du matériel » d'un transport ne
    doit proposer que ce qui se trouve réellement au lieu de DÉPART au moment
    du départ (demande de Samuel). Réutilise exactement le grand livre de
    positions du reste de ce module — `Material.venue` comme point de départ,
    puis chaque transport confirmé et horodaté qui déplace le matériel — plutôt
    que de comparer bêtement `Material.venue` au lieu de départ, ce qui serait
    faux dès qu'un transport antérieur a déjà bougé le matériel.

    Retourne une liste de dicts `{material, available}` pour TOUT le matériel
    actif du projet, y compris avec `available = 0` : le frontend affiche
    l'inventaire complet et grise ce qui n'est pas disponible, il a donc besoin
    des deux catégories.

    `exclude_transport` : le transport en cours d'édition ne doit pas se
    décompter lui-même. Sans ça, rouvrir la modale d'un transport déjà rempli
    montrerait son propre chargement comme « déjà parti ».

    `at` peut être `None` (proposition auto pas encore horodatée) : la position
    n'est alors pas calculable, on renvoie la quantité totale de chaque
    matériel — décision de Samuel du 2026-07-30, on n'invente pas de
    restriction sur une donnée manquante.
    """
    project = project or venue.project
    materials = (
        Material.objects.filter(project=project, is_active=True)
        .select_related('venue', 'category')
        .order_by('name')
    )

    rows = []
    for material in materials:
        if at is None:
            # Sans heure de référence : tout le stock est présenté comme
            # disponible, à charge pour le frontend d'expliquer pourquoi.
            rows.append({'material': material, 'available': material.quantity})
            continue

        events = [
            event for event in _material_events(material)
            if exclude_transport is None or event['transport'].id != exclude_transport.id
        ]
        ledger = _ledger_before(events, at, material.venue_id, material.quantity)
        rows.append({'material': material, 'available': max(0, ledger.get(venue.id, 0))})
    return rows


def get_project_horizon(project):
    """Instant qui fait office de « fin du projet », pour le contrôle de retour.

    Priorité (décision de Samuel du 2026-07-30) :
    1. `Project.end_date` si renseignée — la date de fin saisie fait foi, fin
       de journée (23h59:59) pour englober un démontage tardif.
    2. Sinon, la fin effective du dernier événement du projet (spectacle ou
       déplacement) — le projet « finit » quand plus rien n'est planifié.
    3. `None` si le projet n'a ni date de fin ni événement : il n'y a alors
       rien à contrôler.
    """
    if project.end_date is not None:
        fin_de_journee = datetime.combine(project.end_date, time.max)
        return timezone.make_aware(fin_de_journee) if timezone.is_naive(fin_de_journee) else fin_de_journee

    derniers = []
    dernier_show = (
        Show.objects.filter(project=project).order_by('-end_datetime').first()
    )
    if dernier_show is not None:
        derniers.append(dernier_show.effective_end)

    dernier_transport = (
        Transport.objects
        .filter(project=project, scheduled_datetime__isnull=False)
        .order_by('-scheduled_datetime')
        .first()
    )
    if dernier_transport is not None and dernier_transport.effective_end is not None:
        derniers.append(dernier_transport.effective_end)

    return max(derniers) if derniers else None


def get_material_return_issue(material, horizon):
    """Le matériel est-il revenu à son lieu d'origine à `horizon` ?

    Ajouté le 2026-07-30 à la demande de Samuel : « à la fin du dernier
    événement, le matériel doit être de retour à son origine ». C'est un
    **renversement partiel** de la portée « aller seulement » décidée le
    2026-07-24 — on ne se contentait alors que de vérifier les livraisons.

    Reste **non bloquant** : c'est une entrée de plus dans le rapport de
    cohérence, jamais un refus. Retourne `None` si tout est rentré, si le
    matériel n'a pas de lieu d'origine (déjà signalé par `origine_inconnue`),
    ou si le projet n'a pas d'horizon exploitable.
    """
    if horizon is None or material.venue_id is None:
        return None

    events = _material_events(material)
    if not events:
        # Jamais déplacé : il n'a pas bougé de son bercail, rien à signaler.
        return None

    # `_ledger_before` applique les transports arrivés AVANT la borne ; on
    # décale d'une microseconde pour inclure un retour qui se termine
    # exactement à l'horizon (cas courant quand `end_date` borne la journée).
    ledger = _ledger_before(
        events, horizon + timedelta(microseconds=1), material.venue_id, material.quantity,
    )
    a_la_maison = ledger.get(material.venue_id, 0)
    if a_la_maison >= material.quantity:
        return None

    ailleurs = sorted(
        (
            (venue_id, quantite)
            for venue_id, quantite in ledger.items()
            if venue_id != material.venue_id and quantite > 0
        ),
        key=lambda pair: -pair[1],
    )
    venues_par_id = {
        v.id: v for v in Venue.objects.filter(id__in=[venue_id for venue_id, _ in ailleurs])
    }
    return _serialize_return_issue(material, horizon, a_la_maison, ailleurs, venues_par_id)


def get_material_coherence_issues(material, horizon=None):
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

    # 3. Retour à l'origine — à la fin du projet, tout doit être rentré.
    if horizon is not None:
        retour = get_material_return_issue(material, horizon)
        if retour is not None:
            issues.append(retour)

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
            # Tournées (2026-08-04) : la proposition couvre la livraison si SA
            # LIGNE pour ce matériel décharge au lieu du spectacle — pas la
            # destination finale de la tournée, qui peut continuer plus loin.
            transport_materials__material=material,
            transport_materials__unload_stop__venue_id=show.venue_id,
        )
        .first()
    )


def get_project_coherence_report(project):
    """Rapport de cohérence pour toute une production : concatène les issues de
    chaque matériel du projet. Non bloquant — usage : `GET
    /api/projects/{id}/transport_coherence/`."""
    horizon = get_project_horizon(project)
    issues = []
    for material in Material.objects.filter(project=project).select_related('venue'):
        issues += get_material_coherence_issues(material, horizon=horizon)
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


def _serialize_return_issue(material, horizon, a_la_maison, ailleurs, venues_par_id):
    """Issue : du matériel n'est pas revenu à son lieu d'origine en fin de projet.

    `ailleurs` est une liste `(venue_id, quantité)` triée du plus gros reliquat
    au plus petit — le premier lieu suffit à orienter Samuel vers l'endroit à
    aller récupérer le matériel.
    """
    manquant = material.quantity - a_la_maison
    lieux = ', '.join(
        f"{venues_par_id[venue_id].name} ({quantite})"
        for venue_id, quantite in ailleurs
        if venue_id in venues_par_id
    )
    detail = (
        f"{manquant} unité(s) sur {material.quantity} ne sont pas revenues à "
        f"« {material.venue.name} » à la fin du projet."
    )
    if lieux:
        detail += f" Encore à : {lieux}."
    else:
        # Aucun lieu identifié : le reliquat est « en transit » ou perdu par un
        # transport dont l'origine était déjà incohérente (signalé à part).
        detail += " Aucun lieu de destination identifié — vérifie les déplacements."
    return {
        'type': 'retour_manquant',
        'material_id': material.id,
        'material_name': material.name,
        'show_id': None,
        'home_venue_id': material.venue_id,
        'home_venue_name': material.venue.name,
        'horizon': horizon,
        'quantity_total': material.quantity,
        'quantity_home': a_la_maison,
        'quantity_missing': manquant,
        'locations': [
            {
                'venue_id': venue_id,
                'venue_name': venues_par_id[venue_id].name,
                'quantity': quantite,
            }
            for venue_id, quantite in ailleurs
            if venue_id in venues_par_id
        ],
        'detail': detail,
    }


def _serialize_origin_issue(material, event, available):
    """Issue : une tournée charge le matériel à un lieu où il n'est pas (assez) présent.

    `origin_venue_*` et l'heure du message portent sur l'ARRÊT DE CHARGEMENT
    de la ligne concernée (tournées multi-arrêts, 2026-08-04), pas sur le
    point de départ de la tournée entière.
    """
    transport = event['transport']
    return {
        'type': 'origine_incoherente',
        'transport_id': transport.id,
        'scheduled_datetime': transport.scheduled_datetime,
        'show_id': transport.show_id,
        # Tournée « sans spectacle » possible depuis le 2026-08-06.
        'show_title': transport.show.display_title if transport.show_id else None,
        'material_id': material.id,
        'material_name': material.name,
        'origin_venue_id': event['origin_id'],
        'origin_venue_name': event['origin_venue'].name,
        'quantite_demandee': event['quantity'],
        'quantite_disponible': max(available, 0),
        'detail': (
            f"La tournée qui passe à « {event['origin_venue'].name} » à "
            f"{event['scheduled']:%Y-%m-%d %H:%M} prétend y charger "
            f"{event['quantity']} × « {material.name} », mais seulement "
            f"{max(available, 0)} y est/sont disponible(s) à ce moment "
            f"(aucun transport antérieur ne l'y amène)."
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
        'show_title': show.display_title,
        'show_start': show.start_datetime,
        'venue_id': show.venue_id,
        'venue_name': show.venue.name,
        'material_id': material.id,
        'material_name': material.name,
        'quantite_requise': show_material.quantity,
        'quantite_presente': max(present, 0),
        'detail': (
            f"« {show.display_title} » requiert {show_material.quantity} × « {material.name} » "
            f"à « {show.venue.name} », mais seulement {max(present, 0)} y est/sont "
            f"présent(s) au début de la fenêtre : "
            + (
                "une proposition de transport à approuver couvre ce déplacement."
                if proposal is not None
                else "aucun transport ne l'y amène en quantité suffisante."
            )
        ),
    }


def get_project_window(project):
    """Fenêtre temporelle d'affichage d'un projet : `(début, fin)`.

    Ajoutée le 2026-07-30 pour les écrans « parcours » (matériel et
    techniciens), qui affichent toute la durée de la production plutôt qu'une
    semaine glissante comme le tableau de bord.

    Début : `Project.start_date` si renseignée (début de journée), sinon le
    premier événement du projet. Fin : réutilise `get_project_horizon` (voir
    plus haut) — `end_date` fin de journée, sinon le dernier événement. Le
    couple est `(None, None)` si le projet n'a ni dates ni événement.
    """
    fin = get_project_horizon(project)

    if project.start_date is not None:
        debut_naif = datetime.combine(project.start_date, time.min)
        debut = timezone.make_aware(debut_naif) if timezone.is_naive(debut_naif) else debut_naif
    else:
        premiers = []
        premier_show = Show.objects.filter(project=project).order_by('start_datetime').first()
        if premier_show is not None:
            premiers.append(premier_show.effective_start)
        premier_transport = (
            Transport.objects
            .filter(project=project, scheduled_datetime__isnull=False)
            .order_by('scheduled_datetime')
            .first()
        )
        if premier_transport is not None:
            premiers.append(premier_transport.scheduled_datetime)
        debut = min(premiers) if premiers else None

    if debut is None or fin is None:
        return None, None
    return debut, fin


def get_material_journey(material, window_start, window_end):
    """Parcours d'un matériel : où il se trouve, dans le temps.

    Retourne une liste de **séjours** `{lane, venue_id, venue_name, start,
    end, quantity, parent_lane, merge_from_lane}` : le matériel — ou une
    partie de sa quantité — reste au lieu X de `start` à `end`, sur la ligne
    `lane`. Les transitions sont les transports confirmés qui le déplacent
    (voir `_material_events`).

    Révisé le 2026-08-01 à la demande de Samuel : l'ancienne version
    aplatissait au **lieu majoritaire**, perdant toute trace d'un matériel
    scindé entre plusieurs lieux à la fois. Ici, chaque position simultanée
    a sa propre `lane` (une ligne de la timeline) :

    - `parent_lane` est renseigné sur le tout premier séjour d'une ligne
      **née d'une bifurcation** (une partie de la quantité d'une autre ligne
      qui part vers un lieu pas encore occupé) — jamais sur les séjours
      suivants de cette même ligne, seulement celui où la bifurcation a lieu.
    - `merge_from_lane` est renseigné sur le séjour qui commence quand une
      autre ligne **fusionne** dans celle-ci (le lieu de destination était
      déjà occupé par cette ligne) — la ligne qui fusionne disparaît.
    - Un déplacement qui vide entièrement une ligne vers un lieu encore
      inoccupé ne crée ni bifurcation ni fusion : la même `lane` continue
      simplement sous le nouveau lieu (cas le plus fréquent — comportement
      identique à avant cette révision, `ParcoursAPITests` en dépend).
    - Les bifurcations et fusions s'enchaînent naturellement (une ligne née
      d'une bifurcation peut elle-même se scinder plus tard, ou fusionner
      dans une troisième) : rien dans l'algorithme ne suppose un seul niveau.
    - Les numéros de ligne sont réutilisés dès qu'ils se libèrent (une ligne
      qui se vide entièrement lors d'une fusion ou d'une bifurcation rend son
      numéro disponible) — ça garde le nombre de lignes affichées proche du
      nombre de positions réellement simultanées, plutôt que de grimper sans
      fin sur un matériel qui bifurque/fusionne souvent.

    On construit directement depuis `_material_events` (déjà filtré sur CE
    matériel) plutôt que de rejouer `_ledger_before` à chaque tranche comme
    avant : chaque événement dit explicitement quelle ligne il vide (son
    origine) et laquelle il alimente (sa destination), ce qui est le tracé
    même des bifurcations/fusions — reconstruire cette identité à partir des
    seuls totaux par lieu (ce que fait `_ledger_before`) serait ambigu dès
    que deux mouvements touchent le même lieu. `_ledger_before` reste
    utilisée telle quelle pour l'état initial (position juste avant le début
    de la fenêtre) et par les trois autres fonctions de ce module
    (disponibilité, cohérence, retour) — ne pas y toucher.
    """
    events = _material_events(material)
    if material.venue_id is None:
        return []

    venues_par_id = {
        v.id: v for v in Venue.objects.filter(project_id=material.project_id)
    }

    # État initial : position juste avant le début de la fenêtre. Une seule
    # ligne par lieu déjà occupé — on ne connaît pas l'historique des
    # bifurcations antérieures à la fenêtre (elles n'ont pas à être dessinées
    # hors champ), donc pas de parent_lane/merge_from_lane ici.
    initial_ledger = _ledger_before(
        events, window_start + timedelta(microseconds=1), material.venue_id, material.quantity,
    )
    initial_positions = sorted(
        ((vid, q) for vid, q in initial_ledger.items() if q > 0),
        key=lambda pair: (-pair[1], pair[0]),  # plus grosse quantité d'abord, ordre déterministe
    )

    events_in_window = [
        event for event in events
        if window_start < event['effective_end'] <= window_end
    ]

    sejours = []
    lanes = {}
    free_lanes = []
    next_lane_id = 0

    def allocate_lane():
        nonlocal next_lane_id
        if free_lanes:
            return heapq.heappop(free_lanes)
        lane_id = next_lane_id
        next_lane_id += 1
        return lane_id

    def open_lane(lane_id, venue_id, quantity, start, parent_lane=None, merge_from_lane=None):
        lanes[lane_id] = {
            'venue_id': venue_id,
            'quantity': quantity,
            'start': start,
            'parent_lane': parent_lane,
            'merge_from_lane': merge_from_lane,
        }

    def commit(lane_id, end):
        """Clôt le tronçon courant de `lane_id` et l'ajoute à `sejours`, sauf
        s'il est de durée nulle (deux événements simultanés sur la même
        ligne — la seconde clôture ne doit pas produire de barre vide)."""
        info = lanes[lane_id]
        if end <= info['start']:
            return
        venue = venues_par_id.get(info['venue_id'])
        if venue is None:
            return
        sejours.append({
            'lane': lane_id,
            'venue_id': info['venue_id'],
            'venue_name': venue.name,
            'is_storage': venue.is_storage,
            'start': info['start'],
            'end': end,
            'quantity': info['quantity'],
            'parent_lane': info['parent_lane'],
            'merge_from_lane': info['merge_from_lane'],
        })

    def free_lane(lane_id):
        del lanes[lane_id]
        heapq.heappush(free_lanes, lane_id)

    for venue_id, quantite in initial_positions:
        open_lane(allocate_lane(), venue_id, quantite, window_start)

    for event in events_in_window:
        t = event['effective_end']
        origin_id = event['origin_id']
        destination_id = event['destination_id']
        qty = event['quantity']

        origin_lane = next((lid for lid, info in lanes.items() if info['venue_id'] == origin_id), None)
        if origin_lane is None:
            # Incohérence en amont (transport dont l'origine n'a pas de lot
            # actif ici) — signalée séparément par
            # `get_material_coherence_issues`, ce n'est pas le rôle du
            # parcours de la refléter ; on ignore l'événement pour le tracé.
            continue

        dest_lane = next((lid for lid, info in lanes.items() if info['venue_id'] == destination_id), None)
        origin_remaining = lanes[origin_lane]['quantity'] - qty

        commit(origin_lane, t)

        if origin_remaining <= 0 and dest_lane is None:
            # Déplacement complet vers un lieu encore inoccupé : la même
            # ligne continue, rebaptisée — pas de bifurcation à dessiner.
            open_lane(origin_lane, destination_id, qty, t)
            continue

        if origin_remaining > 0:
            open_lane(origin_lane, origin_id, origin_remaining, t)
        else:
            free_lane(origin_lane)

        if dest_lane is not None:
            # Fusion : la quantité qui part rejoint une ligne déjà active à
            # ce lieu — c'est cette ligne d'arrivée qui porte l'annotation.
            quantite_fusionnee = lanes[dest_lane]['quantity'] + qty
            commit(dest_lane, t)
            open_lane(dest_lane, destination_id, quantite_fusionnee, t, merge_from_lane=origin_lane)
        else:
            # Bifurcation : nouvelle ligne pour la quantité qui part.
            open_lane(allocate_lane(), destination_id, qty, t, parent_lane=origin_lane)

    for lane_id in list(lanes.keys()):
        commit(lane_id, window_end)

    sejours.sort(key=lambda s: (s['start'], s['lane']))
    return sejours


def get_material_schedule(material, window_start=None, window_end=None):
    """Agenda chronologique d'un matériel : tout ce qui le mobilise, dans l'ordre.

    Ajouté le 2026-08-01 à la demande de Samuel : la fiche matériel ne
    montrait que ses assignations à des spectacles, sans horaire ni contexte.
    Elle liste maintenant, sur une seule ligne de temps, les spectacles, les
    blocs (montage, répétition, démontage) et les déplacements.

    Trois sources, réunies ici plutôt que côté frontend — la règle
    d'héritage des blocs est une règle métier, pas un détail d'affichage :

    - **Assignations** (`ShowMaterial`) : un spectacle, une répétition
      indépendante, ou un bloc de répétition rattaché, qui porte ses propres
      assignations depuis le 2026-07-31.
    - **Blocs hérités** : un montage ou un démontage n'a pas d'assignation
      propre — il utilise le matériel de son événement (voir
      `Show.inherits_resources`). Le matériel y est pourtant bel et bien
      mobilisé : chaque bloc de ce type produit une entrée dérivée de
      l'assignation de son événement, marquée `inherited: True`.
    - **Déplacements** (`TransportMaterial`) : y compris les propositions
      encore à approuver, qui n'ont pas d'heure (`start: None`) — elles sont
      renvoyées en fin de liste plutôt que masquées, c'est justement ce qu'il
      reste à compléter.

    `conflict` est calculé par assignation avec `get_material_conflicts`,
    restreint à CE matériel — plus précis et bien moins coûteux que de
    demander tous les conflits de chaque spectacle concerné.

    **Fenêtre du projet** (2026-08-01, demande de Samuel) : `window_start`/
    `window_end` bornent la liste — une entrée qui ne croise pas la fenêtre
    est écartée. C'est la même fenêtre que les écrans « Parcours »
    (`get_project_window`), pour que les deux racontent la même période. Les
    écartées ne sont pas perdues pour autant : elles sont comptées et
    renvoyées à part (voir la valeur de retour), sans quoi une assignation
    disparaîtrait sans explication. Sans fenêtre, tout est renvoyé.

    Retourne `(entries, hors_fenetre)`.
    """
    from .conflicts import get_material_conflicts

    def dans_la_fenetre(debut, fin):
        # Une proposition sans heure n'a pas de fenêtre à comparer : elle
        # reste affichée, c'est justement ce qu'il reste à planifier.
        if debut is None or fin is None:
            return True
        if window_start is not None and fin < window_start:
            return False
        if window_end is not None and debut > window_end:
            return False
        return True

    entries = []

    show_materials = (
        ShowMaterial.objects.filter(material_id=material.id)
        .select_related('show', 'show__venue', 'show__parent_show')
    )
    for sm in show_materials:
        show = sm.show
        entries.append({
            'kind': 'show',
            'id': show.id,
            'title': show.display_title,
            'event_type': show.event_type,
            'start': show.start_datetime,
            'end': show.end_datetime,
            'venue_name': show.venue.name,
            'quantity': sm.quantity,
            'is_rental': sm.is_rental,
            'rental_vendor': sm.rental_vendor,
            'inherited': False,
            'parent_title': show.parent_show.title if show.parent_show_id else None,
            'conflict': bool(
                get_material_conflicts(show, material, exclude_id=sm.id, quantity=sm.quantity)
            ),
        })
        # Blocs qui puisent dans cette assignation. `phases` est vide sur un
        # bloc (hiérarchie à un seul niveau) : pas de doublon à craindre si le
        # matériel est assigné à la fois à l'événement et à sa répétition.
        for phase in show.phases.select_related('venue').order_by('start_datetime'):
            if not phase.inherits_resources:
                continue
            entries.append({
                'kind': 'show',
                'id': phase.id,
                'title': phase.display_title,
                'event_type': phase.event_type,
                'start': phase.start_datetime,
                'end': phase.end_datetime,
                'venue_name': phase.venue.name,
                'quantity': sm.quantity,
                'is_rental': sm.is_rental,
                'rental_vendor': sm.rental_vendor,
                'inherited': True,
                'parent_title': show.title,
                'conflict': False,
            })

    # Tournées (2026-08-04) : chaque ligne est la PORTION qui concerne ce
    # matériel — de son arrêt de chargement à son arrêt de déchargement, avec
    # les heures d'arrivée dérivées à ces deux arrêts. Une proposition sans
    # heure garde `start`/`end` à None (arrival_at renvoie None sans
    # scheduled_datetime).
    transport_materials = (
        TransportMaterial.objects.filter(material_id=material.id)
        .select_related('transport', 'load_stop__venue', 'unload_stop__venue')
        .prefetch_related('transport__stops')
    )
    for tm in transport_materials:
        transport = tm.transport
        entries.append({
            'kind': 'transport',
            'id': transport.id,
            'title': (
                f"{tm.load_stop.venue.name} → {tm.unload_stop.venue.name}"
            ),
            'status': transport.status,
            'start': transport.arrival_at(tm.load_stop),
            'end': transport.arrival_at(tm.unload_stop),
            'venue_name': tm.unload_stop.venue.name,
            'quantity': tm.quantity,
            'inherited': False,
            'parent_title': None,
            'conflict': False,
        })

    # Une proposition sans heure n'a pas sa place dans la chronologie : elle
    # part à la fin, avec son `start` à `None` que le frontend sait afficher.
    retenues = [e for e in entries if dans_la_fenetre(e['start'], e['end'])]
    hors_fenetre = len(entries) - len(retenues)
    retenues.sort(key=lambda e: (e['start'] is None, e['start'] or timezone.now(), e['title']))
    return retenues, hors_fenetre

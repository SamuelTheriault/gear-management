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

from datetime import datetime, time, timedelta

from django.utils import timezone

from .models import Material, Show, ShowMaterial, Transport, TransportMaterial, Venue


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


def get_material_transports(material, window_start, window_end):
    """Transports **confirmés** qui déplacent `material`, dont la fenêtre
    croise `[window_start, window_end]` — ajouté le 2026-07-31 à la demande
    de Samuel, pour les superposer sur le Parcours Matériel (fenêtre du
    déplacement lui-même, pas seulement son arrivée comme `_material_events`
    le fait pour reconstruire les séjours).

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
            'show_title': transport.show.title,
            'origin_venue_id': event['origin_id'],
            'origin_venue_name': transport.origin_venue.name,
            'destination_venue_id': event['destination_id'],
            'destination_venue_name': transport.destination_venue.name,
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
        .filter(show__project=project, scheduled_datetime__isnull=False)
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
            destination_venue_id=show.venue_id,
            transport_materials__material=material,
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
            .filter(show__project=project, scheduled_datetime__isnull=False)
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

    Retourne une liste de **séjours** `{venue_id, venue_name, start, end,
    quantity}` : le matériel reste au lieu X de `start` à `end`. Les
    transitions sont les transports confirmés qui le déplacent (voir
    `_material_events`) — un séjour se termine quand un transport en fait
    partir des unités, et le suivant commence à l'arrivée.

    Simplification assumée : on suit le **lieu majoritaire** à chaque instant,
    pas chaque unité séparément. Pour du matériel en plusieurs exemplaires
    éparpillés entre deux lieux, le séjour porte le lieu où il y en a le plus,
    et `quantity` dit combien. Suivre chaque unité individuellement
    demanderait de les identifier une à une, ce que le modèle ne fait pas
    (voir `Material.quantity`, décision du 2026-07-19).
    """
    events = _material_events(material)
    if material.venue_id is None:
        return []

    # Instants où la position peut changer : le début de la fenêtre, puis
    # chaque arrivée de transport comprise dedans.
    bornes = [window_start]
    for event in events:
        if window_start < event['effective_end'] <= window_end:
            bornes.append(event['effective_end'])
    bornes.append(window_end)

    venues_par_id = {
        v.id: v for v in Venue.objects.filter(project_id=material.project_id)
    }

    sejours = []
    for index, borne in enumerate(bornes[:-1]):
        fin = bornes[index + 1]
        if fin <= borne:
            continue
        # `+1µs` : à l'instant exact d'une arrivée, le transport est appliqué.
        ledger = _ledger_before(
            events, borne + timedelta(microseconds=1), material.venue_id, material.quantity,
        )
        presents = [(vid, q) for vid, q in ledger.items() if q > 0]
        if not presents:
            continue
        venue_id, quantite = max(presents, key=lambda pair: pair[1])
        venue = venues_par_id.get(venue_id)
        if venue is None:
            continue

        # Fusionne avec le séjour précédent si c'est le même lieu — un
        # transport qui ne concerne pas ce matériel ne doit pas couper sa barre.
        if sejours and sejours[-1]['venue_id'] == venue_id and sejours[-1]['quantity'] == quantite:
            sejours[-1]['end'] = fin
            continue

        sejours.append({
            'venue_id': venue_id,
            'venue_name': venue.name,
            'is_storage': venue.is_storage,
            'start': borne,
            'end': fin,
            'quantity': quantite,
        })
    return sejours

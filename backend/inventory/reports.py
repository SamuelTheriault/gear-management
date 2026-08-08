"""Assemblage des données des sorties de rapport (chantier 2026-08-08).

Un seul endroit construit le contenu d'une feuille, quel que soit le canal
qui la consomme : la page publique Vue (`/p/<token>`), le PDF WeasyPrint, et
plus tard un éventuel envoi par courriel. Sans ça, la version écran et la
version papier divergeraient — exactement le défaut que le code QR est censé
corriger.

Chaque `build_*` renvoie un dictionnaire JSON-sérialisable. Les dates sont
laissées en objets `datetime`/`date` : la sérialisation DRF s'en charge pour
l'API, et le gabarit Django les formate pour le PDF. Aucune mise en forme
d'affichage (« 13 h 15 », « 1 h 25 ») n'est décidée ici — c'est de la
présentation, elle appartient au gabarit et à la vue Vue.

Note de périmètre : ces feuilles ne montrent PAS les conflits détectés par
`conflicts.py`. Un conflit est un problème de planification qui appartient à
Samuel ; l'afficher sur la feuille d'un technicien ou d'une salle
partenaire, c'est publier un doute qu'ils ne peuvent pas résoudre. Les avis
présents dans les maquettes restent donc réservés aux écrans internes.
"""

from datetime import timedelta

from django.db.models import Prefetch

from .models import (
    Show,
    ShowMaterial,
    ShowTechnician,
    Technician,
    Transport,
    TransportMaterial,
    TransportTechnician,
)


def _venue_payload(venue):
    if venue is None:
        return None
    return {
        'id': venue.id,
        'name': venue.name,
        'code': venue.code,
        'address': venue.address,
        'contact_name': venue.contact_name,
        'contact_info': venue.contact_info,
        'is_storage': venue.is_storage,
    }


def _technician_payload(technician):
    return {
        'id': technician.id,
        'name': technician.name,
        'specialty': technician.specialty,
    }


# --- Fiche de transport -------------------------------------------------------


def build_transport(transport):
    """Feuille d'une tournée : itinéraire, et à chaque arrêt ce qui monte et
    ce qui descend.

    Le manifeste est éclaté PAR ARRÊT plutôt que présenté en liste globale.
    C'est la seule lecture utile sur un quai : la personne qui décharge veut
    savoir ce qui sort ici, pas ce que contient le camion en tout. Les
    couples `load_stop`/`unload_stop` de `TransportMaterial` sont stockés
    (voir models.py), donc c'est une lecture, pas une reconstruction.
    """
    stops = list(transport.ordered_stops)
    lines = list(
        TransportMaterial.objects
        .filter(transport=transport)
        .select_related('material', 'load_stop__venue', 'unload_stop__venue')
        .order_by('material__name')
    )
    multi = len(stops) > 2

    stops_payload = []
    for index, stop in enumerate(stops):
        load = [
            {
                'quantity': line.quantity,
                'material': line.material.name,
                # Destination affichée uniquement sur une tournée à plus de
                # deux arrêts : sur un simple A → B elle est redondante et
                # allonge chaque ligne pour rien.
                'to': line.unload_stop.venue.name if multi else '',
            }
            for line in lines if line.load_stop_id == stop.id
        ]
        unload = [
            {'quantity': line.quantity, 'material': line.material.name}
            for line in lines if line.unload_stop_id == stop.id
        ]
        stops_payload.append({
            'order': stop.order,
            'venue': _venue_payload(stop.venue),
            'arrival_at': transport.arrival_at(stop),
            'travel_minutes_from_previous': stop.travel_minutes_from_previous,
            'travel_distance_meters': stop.travel_distance_meters,
            'is_first': index == 0,
            'is_last': index == len(stops) - 1,
            'load': load,
            'unload': unload,
        })

    known = [s.travel_distance_meters for s in stops if s.travel_distance_meters]
    missing = sum(
        1 for s in stops if s.order > 0 and not s.travel_distance_meters
    )

    return {
        'kind': 'transport',
        'id': transport.id,
        'status': transport.status,
        'status_display': transport.get_status_display(),
        'show': transport.show.display_title if transport.show_id else None,
        'truck': transport.truck.name if transport.truck_id else None,
        'scheduled_datetime': transport.scheduled_datetime,
        'ends_at': transport.effective_end,
        'total_duration_minutes': transport.total_duration_minutes,
        'distance_meters': sum(known),
        # Le total est partiel quand des segments n'ont pas de distance connue
        # (lieu sans GPS, durée saisie à la main) — le gabarit doit écrire
        # « au moins X km », comme le fait déjà `Truck.estimated_distance`.
        'distance_is_partial': missing > 0,
        'notes': transport.notes,
        'team': [
            _technician_payload(tt.technician)
            for tt in TransportTechnician.objects
            .filter(transport=transport).select_related('technician')
            .order_by('technician__name')
        ],
        'stops': stops_payload,
        'item_count': sum(line.quantity for line in lines),
    }


# --- Fiche spectacle ----------------------------------------------------------


def build_show(show):
    """Feuille d'un spectacle : lieu, horaire, équipe, matériel, et les blocs
    rattachés (montage/démontage/répétitions).

    Les blocs sont inclus parce qu'une fiche spectacle remise à une salle
    doit répondre à « à quelle heure vous arrivez et vous repartez », ce que
    le seul `start_datetime` de la représentation ne dit pas.
    """
    blocks = list(
        Show.objects.filter(parent_show=show)
        .select_related('venue').order_by('start_datetime')
    )
    materials = list(
        ShowMaterial.objects.filter(show=show)
        .select_related('material', 'material__category')
        .order_by('material__category__name', 'material__name')
    )

    return {
        'kind': 'show',
        'id': show.id,
        'title': show.display_title,
        'event_type': show.event_type,
        'event_type_display': show.get_event_type_display(),
        'venue': _venue_payload(show.venue),
        'start_datetime': show.start_datetime,
        'end_datetime': show.end_datetime,
        'engagement_start': show.engagement_start,
        'engagement_end': show.effective_end,
        'notes': show.notes,
        'team': [
            _technician_payload(st.technician)
            for st in ShowTechnician.objects.filter(show=show)
            .select_related('technician').order_by('technician__name')
        ],
        'materials': [
            {
                'quantity': sm.quantity,
                'material': sm.material.name,
                'category': sm.material.category.name if sm.material.category_id else '',
                'is_rental': sm.is_rental,
                'rental_vendor': sm.rental_vendor or '',
            }
            for sm in materials
        ],
        'blocks': [
            {
                'id': block.id,
                'title': block.display_title,
                'event_type': block.event_type,
                'event_type_display': block.get_event_type_display(),
                'start_datetime': block.start_datetime,
                'end_datetime': block.end_datetime,
                'venue': _venue_payload(block.venue),
            }
            for block in blocks
        ],
        'transports': [
            {
                'id': t.id,
                'scheduled_datetime': t.scheduled_datetime,
                'status': t.status,
                'from': t.origin_venue.name if t.origin_venue else None,
                'to': t.destination_venue.name if t.destination_venue else None,
            }
            for t in Transport.objects.filter(show=show)
            .prefetch_related('stops__venue').order_by('scheduled_datetime')
        ],
    }


# --- Parcours technicien ------------------------------------------------------


def _technician_engagements(technician, start=None, end=None):
    """Engagements d'un technicien, spectacles et tournées mélangés, triés.

    Même définition que `ProjectViewSet.technician_journey` (views.py) :
    assignations directes (`ShowTechnician`, `TransportTechnician`) PLUS les
    montages et démontages des spectacles assignés, qui n'ont pas
    d'assignation propre mais mobilisent bien la même équipe. Sans eux, le
    parcours montre un trou là où la personne est en réalité sur le plateau.

    Le marquage des conflits, lui, n'est délibérément PAS repris — voir la
    note de périmètre en tête de module.
    """
    engagements = []

    assigned = list(
        ShowTechnician.objects.filter(technician=technician)
        .select_related('show', 'show__venue').order_by('show__start_datetime')
    )
    assigned_shows = [st.show for st in assigned]

    for show in assigned_shows:
        engagements.append({
            'type': 'show',
            'id': show.id,
            'title': show.display_title,
            'event_type': show.event_type,
            'event_type_display': show.get_event_type_display(),
            'venue': _venue_payload(show.venue),
            'start': show.start_datetime,
            'end': show.end_datetime,
            'inherited': False,
        })

    # Montages/démontages hérités (voir Show.INHERITING_PHASE_TYPES).
    for block in Show.objects.filter(
        parent_show__in=assigned_shows,
        event_type__in=Show.INHERITING_PHASE_TYPES,
    ).select_related('venue', 'parent_show'):
        engagements.append({
            'type': 'show',
            'id': block.id,
            'title': block.display_title,
            'event_type': block.event_type,
            'event_type_display': block.get_event_type_display(),
            'venue': _venue_payload(block.venue),
            'start': block.start_datetime,
            'end': block.end_datetime,
            'inherited': True,
        })

    for tt in TransportTechnician.objects.filter(technician=technician).select_related(
        'transport', 'transport__truck',
    ).prefetch_related('transport__stops__venue'):
        transport = tt.transport
        if transport.scheduled_datetime is None:
            # Proposition auto non complétée : pas de fenêtre exploitable,
            # ignorée partout ailleurs (timelines, conflits) — même règle ici.
            continue
        engagements.append({
            'type': 'transport',
            'id': transport.id,
            'title': (
                f"{transport.origin_venue.name} → {transport.destination_venue.name}"
                if transport.origin_venue and transport.destination_venue else 'Tournée'
            ),
            'venue': _venue_payload(transport.origin_venue),
            'destination': _venue_payload(transport.destination_venue),
            'truck': transport.truck.name if transport.truck_id else None,
            'start': transport.scheduled_datetime,
            'end': transport.effective_end,
            'stop_count': len(transport.ordered_stops),
            'inherited': False,
        })

    if start is not None:
        engagements = [e for e in engagements if e['end'] is None or e['end'] >= start]
    if end is not None:
        engagements = [e for e in engagements if e['start'] <= end]

    engagements.sort(key=lambda e: e['start'])
    return engagements


def build_technician(technician):
    """Feuille de route d'un technicien sur toute la production."""
    engagements = _technician_engagements(technician)
    return {
        'kind': 'technician',
        'id': technician.id,
        'name': technician.name,
        'specialty': technician.specialty,
        'contact_info': technician.contact_info,
        'engagements': engagements,
        'first_start': engagements[0]['start'] if engagements else None,
        'last_end': engagements[-1]['end'] if engagements else None,
    }


# --- Horaire de la journée ----------------------------------------------------


def build_day(project, day):
    """Tout ce qui se passe dans la production un jour donné, par lieu.

    C'est la feuille de régie : elle croise spectacles, blocs et tournées sur
    une seule page paysage. Le regroupement par LIEU (et non par heure) est
    ce qui la rend lisible quand deux salles tournent en parallèle.

    Fenêtre : le jour civil dans le fuseau courant de Django. Un événement à
    cheval sur minuit apparaît sur les deux journées, ce qui est le
    comportement voulu — la personne en poste le soir et celle du lendemain
    matin doivent toutes deux le voir.
    """
    from django.utils import timezone as tz

    start = tz.make_aware(
        tz.datetime.combine(day, tz.datetime.min.time()),
    ) if tz.is_naive(tz.datetime.combine(day, tz.datetime.min.time())) else tz.datetime.combine(day, tz.datetime.min.time())
    end = start + timedelta(days=1)

    shows = list(
        Show.objects.filter(project=project, start_datetime__lt=end, end_datetime__gte=start)
        .select_related('venue', 'parent_show')
        .prefetch_related(Prefetch(
            'show_technicians',
            queryset=ShowTechnician.objects.select_related('technician'),
        ))
        .order_by('start_datetime')
    )

    transports = [
        t for t in Transport.objects.filter(project=project, scheduled_datetime__isnull=False)
        .select_related('truck', 'show')
        .prefetch_related('stops__venue', 'transport_technicians__technician')
        .order_by('scheduled_datetime')
        if t.scheduled_datetime < end and (t.effective_end or t.scheduled_datetime) >= start
    ]

    by_venue = {}
    for show in shows:
        entry = by_venue.setdefault(show.venue_id, {'venue': _venue_payload(show.venue), 'items': []})
        entry['items'].append({
            'type': 'show',
            'id': show.id,
            'title': show.display_title,
            'event_type': show.event_type,
            'event_type_display': show.get_event_type_display(),
            'start': show.start_datetime,
            'end': show.end_datetime,
            'team': [_technician_payload(st.technician) for st in show.show_technicians.all()],
        })

    for transport in transports:
        venue = transport.origin_venue
        key = venue.id if venue else None
        entry = by_venue.setdefault(key, {'venue': _venue_payload(venue), 'items': []})
        entry['items'].append({
            'type': 'transport',
            'id': transport.id,
            'title': (
                f"{transport.origin_venue.name} → {transport.destination_venue.name}"
                if transport.origin_venue and transport.destination_venue else 'Tournée'
            ),
            'truck': transport.truck.name if transport.truck_id else None,
            'start': transport.scheduled_datetime,
            'end': transport.effective_end,
            'team': [
                _technician_payload(tt.technician)
                for tt in transport.transport_technicians.all()
            ],
        })

    lanes = sorted(by_venue.values(), key=lambda e: (e['venue'] is None, e['venue']['name'] if e['venue'] else ''))
    for lane in lanes:
        lane['items'].sort(key=lambda i: i['start'])

    return {
        'kind': 'day',
        'day': day,
        'lanes': lanes,
        'item_count': sum(len(lane['items']) for lane in lanes),
    }


# --- Aiguillage ---------------------------------------------------------------


def build_payload(share):
    """Contenu de la feuille d'un `ReportShare`, quel que soit son type."""
    from .models import ReportShare

    if share.kind == ReportShare.KIND_TRANSPORT:
        return build_transport(share.transport)
    if share.kind == ReportShare.KIND_SHOW:
        return build_show(share.show)
    if share.kind == ReportShare.KIND_TECHNICIAN:
        return build_technician(share.technician)
    if share.kind == ReportShare.KIND_DAY:
        return build_day(share.project, share.day)
    raise ValueError(f"Type de rapport inconnu : {share.kind!r}")

"""Export/import complet d'un projet — voir `ProjectViewSet.export`/`import_project`
(views.py) et `architecture.md`.

Ajouté le 2026-08-04 à la demande de Samuel : pouvoir sortir un projet complet
de l'app (JSON, réimportable — et XML, lecture seule) pour l'archiver ou le
faire passer vers une autre itération de l'app (ex. une instance de
développement, ou une future migration d'hébergeur).

Contrairement à `duplication.py` (qui démarre une NOUVELLE édition d'un
mandat — dates/notes vidées, aucune assignation/horaire copiée),
l'export/import ici vise la fidélité complète : TOUTES les tables d'un projet
sont couvertes, y compris `Show`/`ShowMaterial`/`ShowTechnician`/`Transport`
et leurs tables de liaison. Un import crée toujours un NOUVEAU `Project` —
jamais n'écrase un projet existant (même logique de sécurité que
`duplicate_project`) — décision validée avec Samuel.

Les serializers DRF (serializers.py) ne sont volontairement PAS réutilisés
ici : plusieurs (`ShowMaterialSerializer`, `ShowTechnicianSerializer`,
`TransportSerializer`) déclenchent la détection de conflits à la création, ce
qui bloquerait la réimportation de données historiques parfaitement valides.
Comme `duplication.py`, ce module construit les objets directement via
`Model.objects.create()`.

Format du fichier exporté (JSON, `EXPORT_FORMAT`/`EXPORT_FORMAT_VERSION`) :
un dict avec `project` (les champs de la fiche projet) et une liste par table
(`venues`, `material_categories`, `materials`, `technicians`, `shows`,
`show_materials`, `show_technicians`, `transports`). Chaque ligne garde son id
d'origine (`id`) UNIQUEMENT pour permettre aux autres lignes du même fichier
de s'y référer (ex. `materials[].venue` pointe vers un `id` de `venues`) — cet
id n'a plus aucun sens une fois réimporté (nouvelles clés primaires) et n'est
jamais réutilisé tel quel.
"""

import datetime
from decimal import Decimal, InvalidOperation
from xml.etree.ElementTree import Element, tostring
from xml.dom import minidom

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from .rich_text import clean_notes
from .models import (
    Material,
    MaterialCategory,
    Project,
    Show,
    ShowMaterial,
    ShowTechnician,
    Technician,
    Transport,
    TransportMaterial,
    TransportStop,
    TransportTechnician,
    Venue,
)

EXPORT_FORMAT = 'gear-management-project'
EXPORT_FORMAT_VERSION = '1.0'


class PortabilityError(Exception):
    """Fichier d'import invalide, incomplet, ou de format non reconnu —
    toujours affichée telle quelle côté frontend (message déjà en français,
    voir `ProjectViewSet.import_project`)."""


# --- Export ---

def export_project_data(project):
    """Construit la structure complète et portable d'un projet — voir le
    docstring de module pour le format. Types Python natifs (date/datetime/
    Decimal) : la conversion en JSON (`DjangoJSONEncoder`) ou en XML
    (`_scalar_to_str`) se fait au niveau de l'appelant, pas ici, pour que les
    deux formats partagent exactement la même collecte de données."""
    materials = list(
        project.materials.select_related('category', 'venue', 'parent_material').all()
    )
    shows = list(project.shows.select_related('venue', 'parent_show').all())
    transports = list(
        Transport.objects.filter(project=project)
        .select_related('show')
        .prefetch_related(
            'stops__venue',
            'transport_technicians__technician',
            'transport_materials__material',
            'transport_materials__load_stop',
            'transport_materials__unload_stop',
        )
    )
    show_materials = list(
        ShowMaterial.objects.filter(show__project=project).select_related('show', 'material')
    )
    show_technicians = list(
        ShowTechnician.objects.filter(show__project=project).select_related('show', 'technician')
    )

    return {
        'format': EXPORT_FORMAT,
        'format_version': EXPORT_FORMAT_VERSION,
        'exported_at': timezone.now(),
        'project': {
            'name': project.name,
            'client_name': project.client_name,
            'status': project.status,
            'start_date': project.start_date,
            'end_date': project.end_date,
            'notes': project.notes,
        },
        'venues': [
            {
                'id': v.id,
                'name': v.name,
                'code': v.code,
                'address': v.address,
                'contact_name': v.contact_name,
                'contact_info': v.contact_info,
                'notes': v.notes,
                'is_storage': v.is_storage,
                'latitude': v.latitude,
                'longitude': v.longitude,
                'color': v.color,
            }
            for v in project.venues.all()
        ],
        'material_categories': [
            {'id': c.id, 'name': c.name, 'color': c.color}
            for c in project.material_categories.all()
        ],
        'materials': [
            {
                'id': m.id,
                'name': m.name,
                'description': m.description,
                'category': m.category_id,
                'parent_material': m.parent_material_id,
                'is_kit_parent': m.is_kit_parent,
                'venue': m.venue_id,
                'ownership_status': m.ownership_status,
                'is_active': m.is_active,
                'quantity': m.quantity,
                'notes': m.notes,
            }
            for m in materials
        ],
        'technicians': [
            {
                'id': t.id,
                'name': t.name,
                'contact_info': t.contact_info,
                'specialty': t.specialty,
                'notes': t.notes,
            }
            for t in project.technicians.all()
        ],
        'shows': [
            {
                'id': s.id,
                'title': s.title,
                'venue': s.venue_id,
                'event_type': s.event_type,
                'start_datetime': s.start_datetime,
                'end_datetime': s.end_datetime,
                'buffer_before_minutes': s.buffer_before_minutes,
                'buffer_after_minutes': s.buffer_after_minutes,
                'parent_show': s.parent_show_id,
                'notes': s.notes,
            }
            for s in shows
        ],
        'show_materials': [
            {
                'show': sm.show_id,
                'material': sm.material_id,
                'quantity': sm.quantity,
                'is_rental': sm.is_rental,
                'rental_vendor': sm.rental_vendor,
            }
            for sm in show_materials
        ],
        'show_technicians': [
            {'show': st.show_id, 'technician': st.technician_id}
            for st in show_technicians
        ],
        # Tournées multi-arrêts (2026-08-04) : `stops` remplace l'ancien
        # couple `origin_venue`/`destination_venue` (+ `transport_type`,
        # retiré sans équivalent) — voir Transport/TransportStop, models.py.
        # Chaque ligne de matériel référence son arrêt de chargement/
        # déchargement par POSITION (`order`), pas par id de `TransportStop`
        # — comme pour `materials[].id`, les ids ne survivent pas à
        # l'import (nouvelles clés primaires), la position dans la séquence
        # SI (même fichier, même tournée).
        'transports': [
            {
                'id': tr.id,
                'status': tr.status,
                'show': tr.show_id,
                'scheduled_datetime': tr.scheduled_datetime,
                'notes': tr.notes,
                'stops': [
                    {
                        'order': stop.order,
                        'venue': stop.venue_id,
                        'travel_minutes_from_previous': stop.travel_minutes_from_previous,
                    }
                    for stop in tr.ordered_stops
                ],
                'technicians': [tt.technician_id for tt in tr.transport_technicians.all()],
                'materials': [
                    {
                        'material': tm.material_id,
                        'quantity': tm.quantity,
                        'load_stop_order': tm.load_stop.order,
                        'unload_stop_order': tm.unload_stop.order,
                    }
                    for tm in tr.transport_materials.all()
                ],
            }
            for tr in transports
        ],
    }


# --- XML (export seulement — voir docstring de module) ---

# `tag[:-1]` (retirer le "s" final) suffit pour toutes nos clés de liste sauf
# celle-ci — "material_categories" perdrait son "y" (-> "material_categorie").
_SINGULAR_OVERRIDES = {'material_categories': 'material_category'}


def _singular(tag):
    return _SINGULAR_OVERRIDES.get(tag, tag[:-1] if tag.endswith('s') else tag)


def _scalar_to_str(value):
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _build_xml_element(tag, value):
    element = Element(tag)
    if isinstance(value, dict):
        for key, sub_value in value.items():
            element.append(_build_xml_element(key, sub_value))
    elif isinstance(value, list):
        child_tag = _singular(tag)
        for item in value:
            element.append(_build_xml_element(child_tag, item))
    else:
        element.text = _scalar_to_str(value)
    return element


def build_project_xml(data):
    """Sérialise la structure de `export_project_data` en XML (bytes, encodage
    UTF-8, indenté). Format non réimportable — voir docstring de module."""
    root = _build_xml_element('project_export', data)
    rough = tostring(root, encoding='utf-8')
    return minidom.parseString(rough).toprettyxml(indent='  ', encoding='utf-8')


# --- Import ---

def _parse_date(value):
    if not value:
        return None
    if isinstance(value, datetime.date):
        return value
    parsed = parse_date(str(value))
    if parsed is None:
        raise PortabilityError(f"Date invalide dans le fichier : « {value} ».")
    return parsed


def _parse_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        return value
    parsed = parse_datetime(str(value))
    if parsed is None:
        raise PortabilityError(f"Date/heure invalide dans le fichier : « {value} ».")
    return parsed


def _parse_decimal(value):
    if value in (None, ''):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        raise PortabilityError(f"Coordonnée invalide dans le fichier : « {value} ».")


def import_project_data(data, name=None, client_name=None):
    """Crée un NOUVEAU `Project` à partir d'un fichier exporté par
    `export_project_data` (JSON désérialisé — voir `ProjectViewSet.import_project`).

    `name` : remplace le nom du fichier si fourni (sinon celui du fichier,
    obligatoire dans un cas comme dans l'autre). `client_name` : idem,
    remplace celui du fichier si fourni explicitement (chaîne vide comprise —
    seul `None`, c-à-d absent, retombe sur le fichier).

    Toute l'opération est atomique : en cas d'erreur (référence brisée,
    format inconnu), rien n'est créé. Retourne `(nouveau_projet, counts)` où
    `counts` est un dict `{'venues': n, 'materials': n, ...}` — une entrée par
    table couverte.
    """
    if not isinstance(data, dict):
        raise PortabilityError("Fichier invalide : une structure JSON (objet) est attendue.")
    if data.get('format') != EXPORT_FORMAT:
        raise PortabilityError(
            "Ce fichier ne provient pas d'un export gear-management, ou son format n'est pas reconnu."
        )
    version = str(data.get('format_version') or '')
    if not version.startswith('1.'):
        raise PortabilityError(f"Version de format non prise en charge : « {version or 'inconnue'} ».")

    project_data = data.get('project') or {}
    resolved_name = (name if name is not None else project_data.get('name') or '').strip()
    if not resolved_name:
        raise PortabilityError("Le projet importé doit avoir un nom.")
    resolved_client_name = client_name if client_name is not None else (project_data.get('client_name') or '')

    try:
        with transaction.atomic():
            new_project = Project.objects.create(
                name=resolved_name,
                client_name=resolved_client_name,
                status=project_data.get('status') or Project.STATUS_ACTIVE,
                start_date=_parse_date(project_data.get('start_date')),
                end_date=_parse_date(project_data.get('end_date')),
                notes=clean_notes(project_data.get('notes') or ''),
            )

            venue_id_map = {}
            for v in data.get('venues') or []:
                new_venue = Venue.objects.create(
                    project=new_project,
                    name=v.get('name') or '',
                    code=v.get('code') or '',
                    address=v.get('address') or '',
                    contact_name=v.get('contact_name') or '',
                    contact_info=v.get('contact_info') or '',
                    notes=clean_notes(v.get('notes') or ''),
                    is_storage=bool(v.get('is_storage', False)),
                    latitude=_parse_decimal(v.get('latitude')),
                    longitude=_parse_decimal(v.get('longitude')),
                    color=v.get('color') or '',
                )
                venue_id_map[v.get('id')] = new_venue

            # Le signal `creer_categories_par_defaut` a déjà doté `new_project`
            # des 9 catégories par défaut à sa création (models.py/signals.py) —
            # `get_or_create` sur le nom évite les doublons, exactement comme
            # `duplication.duplicate_project`.
            category_id_map = {}
            for c in data.get('material_categories') or []:
                category_name = c.get('name') or ''
                new_category, created = MaterialCategory.objects.get_or_create(
                    project=new_project, name=category_name,
                    defaults={'color': c.get('color') or MaterialCategory.DEFAULT_COLOR},
                )
                if not created and c.get('color') and new_category.color != c.get('color'):
                    new_category.color = c.get('color')
                    new_category.save(update_fields=['color'])
                category_id_map[c.get('id')] = new_category

            # Matériel — deux passes : la hiérarchie parent/enfant ne peut être
            # remappée qu'une fois toutes les copies créées (même principe que
            # `duplication.duplicate_project`).
            material_id_map = {}
            materials_data = data.get('materials') or []
            for m in materials_data:
                new_material = Material.objects.create(
                    project=new_project,
                    name=m.get('name') or '',
                    description=m.get('description') or '',
                    category=category_id_map.get(m.get('category')),
                    venue=venue_id_map.get(m.get('venue')),
                    is_kit_parent=bool(m.get('is_kit_parent', False)),
                    ownership_status=m.get('ownership_status') or Material.OWNERSHIP_OWNED,
                    is_active=bool(m.get('is_active', True)),
                    quantity=int(m.get('quantity') or 1),
                    notes=clean_notes(m.get('notes') or ''),
                )
                material_id_map[m.get('id')] = new_material
            for m in materials_data:
                parent_ref = m.get('parent_material')
                if parent_ref is None:
                    continue
                parent = material_id_map.get(parent_ref)
                if parent is None:
                    raise PortabilityError(
                        f"Le matériel « {m.get('name')} » référence un parent introuvable dans le fichier."
                    )
                new_material = material_id_map[m.get('id')]
                new_material.parent_material = parent
                new_material.save(update_fields=['parent_material'])

            technician_id_map = {}
            for t in data.get('technicians') or []:
                new_technician = Technician.objects.create(
                    project=new_project,
                    name=t.get('name') or '',
                    contact_info=t.get('contact_info') or '',
                    specialty=t.get('specialty') or '',
                    notes=clean_notes(t.get('notes') or ''),
                )
                technician_id_map[t.get('id')] = new_technician

            # Spectacles — même logique deux passes pour `parent_show`
            # (montage/démontage/répétition rattachés, voir models.py).
            show_id_map = {}
            shows_data = data.get('shows') or []
            for s in shows_data:
                venue_obj = venue_id_map.get(s.get('venue'))
                if venue_obj is None:
                    raise PortabilityError(
                        f"Le spectacle « {s.get('title') or s.get('id')} » référence un lieu introuvable dans le fichier."
                    )
                new_show = Show.objects.create(
                    project=new_project,
                    title=s.get('title') or '',
                    venue=venue_obj,
                    event_type=s.get('event_type'),
                    start_datetime=_parse_datetime(s.get('start_datetime')),
                    end_datetime=_parse_datetime(s.get('end_datetime')),
                    buffer_before_minutes=int(s.get('buffer_before_minutes') or 0),
                    buffer_after_minutes=int(s.get('buffer_after_minutes') or 0),
                    notes=clean_notes(s.get('notes') or ''),
                )
                show_id_map[s.get('id')] = new_show
            for s in shows_data:
                parent_ref = s.get('parent_show')
                if parent_ref is None:
                    continue
                parent = show_id_map.get(parent_ref)
                if parent is None:
                    raise PortabilityError(
                        f"Le bloc « {s.get('title') or s.get('id')} » référence un événement parent introuvable dans le fichier."
                    )
                new_show = show_id_map[s.get('id')]
                new_show.parent_show = parent
                new_show.save(update_fields=['parent_show'])

            show_material_count = 0
            for sm in data.get('show_materials') or []:
                show_obj = show_id_map.get(sm.get('show'))
                material_obj = material_id_map.get(sm.get('material'))
                if show_obj is None or material_obj is None:
                    raise PortabilityError(
                        "Une assignation de matériel référence un spectacle ou un matériel introuvable dans le fichier."
                    )
                ShowMaterial.objects.create(
                    show=show_obj,
                    material=material_obj,
                    quantity=int(sm.get('quantity') or 1),
                    is_rental=bool(sm.get('is_rental', False)),
                    rental_vendor=sm.get('rental_vendor') or None,
                )
                show_material_count += 1

            show_technician_count = 0
            for st in data.get('show_technicians') or []:
                show_obj = show_id_map.get(st.get('show'))
                technician_obj = technician_id_map.get(st.get('technician'))
                if show_obj is None or technician_obj is None:
                    raise PortabilityError(
                        "Une assignation de technicien référence un spectacle ou un technicien introuvable dans le fichier."
                    )
                ShowTechnician.objects.create(show=show_obj, technician=technician_obj)
                show_technician_count += 1

            # Tournées multi-arrêts (2026-08-04) : chaque transport porte sa
            # propre séquence d'arrêts (`stops`, triée par `order` dans le
            # fichier — voir `export_project_data`), au moins 2 (départ +
            # arrivée), même contrainte que la création via l'API
            # (`TransportSerializer`). `stop_obj_by_order` sert ensuite à
            # résoudre `load_stop`/`unload_stop` de chaque ligne de matériel
            # — les ids de `TransportStop` d'origine ne survivent pas à
            # l'import, seule la position dans la séquence est fiable.
            transport_count = 0
            for tr in data.get('transports') or []:
                # `show` est OPTIONNEL depuis le 2026-08-06 (tournée « sans
                # spectacle », migration 0028) : null dans le fichier = tournée
                # logistique, on ne l'invente pas. Une référence NON nulle qui
                # ne résout pas reste une erreur (fichier incohérent).
                show_ref = tr.get('show')
                show_obj = show_id_map.get(show_ref) if show_ref is not None else None
                if show_ref is not None and show_obj is None:
                    raise PortabilityError(
                        "Un déplacement référence un spectacle introuvable dans le fichier."
                    )
                stops_data = sorted(tr.get('stops') or [], key=lambda s: s.get('order') or 0)
                if len(stops_data) < 2:
                    raise PortabilityError(
                        "Un déplacement du fichier n'a pas assez d'arrêts (au moins 2 attendus)."
                    )
                new_transport = Transport.objects.create(
                    project=new_project,
                    show=show_obj,
                    status=tr.get('status') or Transport.STATUS_CONFIRMED,
                    scheduled_datetime=_parse_datetime(tr.get('scheduled_datetime')),
                    notes=clean_notes(tr.get('notes') or ''),
                )
                stop_obj_by_order = {}
                for position, stop in enumerate(stops_data):
                    venue_obj = venue_id_map.get(stop.get('venue'))
                    if venue_obj is None:
                        raise PortabilityError(
                            "Un arrêt de déplacement référence un lieu introuvable dans le fichier."
                        )
                    new_stop = TransportStop.objects.create(
                        transport=new_transport,
                        venue=venue_obj,
                        order=position,
                        travel_minutes_from_previous=int(stop.get('travel_minutes_from_previous') or 0),
                    )
                    stop_obj_by_order[stop.get('order')] = new_stop
                for tech_ref in tr.get('technicians') or []:
                    technician_obj = technician_id_map.get(tech_ref)
                    if technician_obj is None:
                        raise PortabilityError("Un déplacement référence un technicien introuvable dans le fichier.")
                    TransportTechnician.objects.create(transport=new_transport, technician=technician_obj)
                for tm in tr.get('materials') or []:
                    material_obj = material_id_map.get(tm.get('material'))
                    load_stop_obj = stop_obj_by_order.get(tm.get('load_stop_order'))
                    unload_stop_obj = stop_obj_by_order.get(tm.get('unload_stop_order'))
                    if material_obj is None:
                        raise PortabilityError("Un déplacement référence un matériel introuvable dans le fichier.")
                    if load_stop_obj is None or unload_stop_obj is None:
                        raise PortabilityError(
                            "Une ligne de matériel de déplacement référence un arrêt introuvable dans le fichier."
                        )
                    TransportMaterial.objects.create(
                        transport=new_transport,
                        material=material_obj,
                        quantity=int(tm.get('quantity') or 1),
                        load_stop=load_stop_obj,
                        unload_stop=unload_stop_obj,
                    )
                transport_count += 1

            counts = {
                'venues': len(venue_id_map),
                'material_categories': len(category_id_map),
                'materials': len(material_id_map),
                'technicians': len(technician_id_map),
                'shows': len(show_id_map),
                'show_materials': show_material_count,
                'show_technicians': show_technician_count,
                'transports': transport_count,
            }
            return new_project, counts
    except PortabilityError:
        raise
    except (KeyError, TypeError, ValueError, IntegrityError) as exc:
        raise PortabilityError(f"Fichier invalide ou incomplet : {exc}") from exc

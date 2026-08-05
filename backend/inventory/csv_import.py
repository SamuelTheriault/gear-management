"""Import CSV par section — pendant de `csv_export.py`, ajouté le 2026-08-04 à
la demande de Samuel : réimporter un CSV exporté depuis Réglages (et
éventuellement modifié dans Excel) dans une des 4 listes du projet — matériel,
lieux, techniciens, spectacles.

Deux modes, choisis par l'utilisateur à chaque import (voir
`ProjetDetailView.vue`/`ReglagesView.vue` et `ProjectViewSet`... en fait
`MaterialViewSet.import_csv` et consorts, views.py) :
- `append` : les lignes du fichier s'ajoutent à la suite du contenu existant.
- `replace` : tout le contenu existant de CETTE liste, pour CE projet, est
  supprimé avant l'import — jamais les autres listes, jamais un autre projet.

Les en-têtes sont validés AVANT toute écriture (voir
`csv_export.parse_csv_rows`) — un fichier dont les colonnes ne correspondent
pas est rejeté sans rien toucher à la base. Chaque fonction est atomique :
soit tout le fichier est importé, soit rien ne l'est (une ligne invalide en
milieu de fichier annule tout, pas d'import partiel silencieux).

Comme `duplication.py`/`portability.py`, les objets sont créés directement
via `Model.objects.create()` plutôt que par les serializers DRF — un CSV peut
contenir des lignes qui, prises isolément, déclencheraient une détection de
conflit (ex. deux spectacles qui se chevauchent) sans que ce soit une erreur
de saisie à bloquer ici.
"""

import datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone as dj_timezone

from .csv_export import (
    MATERIAL_CSV_HEADER,
    SHOW_CSV_HEADER,
    TECHNICIAN_CSV_HEADER,
    VENUE_CSV_HEADER,
    CsvImportError,
    parse_csv_rows,
)
from .models import Material, MaterialCategory, Show, Technician, TransportStop, Venue

MODE_APPEND = 'append'
MODE_REPLACE = 'replace'
VALID_MODES = (MODE_APPEND, MODE_REPLACE)


def _yes_no(value):
    return (value or '').strip().lower() in ('oui', 'yes', 'true', '1')


def _parse_decimal(value, label):
    value = (value or '').strip()
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        raise CsvImportError(f"Valeur numérique invalide ({label}) : « {value} ».")


def _validate_mode(mode):
    if mode not in VALID_MODES:
        raise CsvImportError("Mode d'import invalide — « append » (à la suite) ou « replace » (remplace tout) attendu.")


# --- Matériel ---

def import_materials_csv(project, text, mode):
    """Importe `text` (contenu d'un CSV matériel) dans `project`. Une
    catégorie mentionnée mais absente du projet est créée à la volée (couleur
    par défaut) — un lieu mentionné mais introuvable fait échouer l'import
    (pas de création implicite : contrairement à une catégorie, un lieu
    inconnu est plus probablement une faute de frappe qu'une nouvelle
    entrée voulue).

    `replace` : supprime tout le matériel existant du projet — cascade sur
    ses assignations (`ShowMaterial`) et ses lignes de transport
    (`TransportMaterial`), voir `Material.show_materials`/
    `Material.transport_materials` (on_delete=CASCADE). Averti côté frontend
    avant confirmation (voir ReglagesView.vue)."""
    _validate_mode(mode)
    rows = parse_csv_rows(text, MATERIAL_CSV_HEADER)

    with transaction.atomic():
        if mode == MODE_REPLACE:
            project.materials.all().delete()

        venues_by_name = {v.name.strip().lower(): v for v in project.venues.all()}
        categories_by_name = {c.name.strip().lower(): c for c in project.material_categories.all()}
        ownership_by_label = {
            'propriété': Material.OWNERSHIP_OWNED,
            'location': Material.OWNERSHIP_RENTAL,
        }

        created_count = 0
        pending_parents = []  # (matériel créé, nom du parent à résoudre)
        for row in rows:
            name = row.get('Nom', '').strip()
            if not name:
                raise CsvImportError("Une ligne de matériel n'a pas de nom.")

            category = None
            category_name = row.get('Catégorie', '').strip()
            if category_name:
                category = categories_by_name.get(category_name.lower())
                if category is None:
                    category = MaterialCategory.objects.create(project=project, name=category_name)
                    categories_by_name[category_name.lower()] = category

            venue = None
            venue_name = row.get('Lieu', '').strip()
            if venue_name:
                venue = venues_by_name.get(venue_name.lower())
                if venue is None:
                    raise CsvImportError(f"Lieu introuvable pour « {name} » : « {venue_name} ».")

            raw_quantity = row.get('Quantité', '').strip()
            try:
                quantity = int(raw_quantity) if raw_quantity else 1
            except ValueError:
                raise CsvImportError(f"Quantité invalide pour « {name} » : « {raw_quantity} ».")
            if quantity < 1:
                raise CsvImportError(f"Quantité invalide pour « {name} » : doit être au moins 1.")

            ownership = ownership_by_label.get(
                (row.get('Propriété') or '').strip().lower(), Material.OWNERSHIP_OWNED,
            )

            material = Material.objects.create(
                project=project,
                name=name,
                description=row.get('Description', ''),
                category=category,
                venue=venue,
                is_kit_parent=_yes_no(row.get('Kit parent')),
                ownership_status=ownership,
                is_active=_yes_no(row.get('Actif') or 'Oui'),
                quantity=quantity,
                notes=row.get('Notes', ''),
            )
            created_count += 1

            parent_name = row.get('Fait partie du kit', '').strip()
            if parent_name:
                pending_parents.append((material, parent_name))

        if pending_parents:
            # Résolu contre TOUT le matériel du projet (pas seulement les
            # lignes de ce fichier) — un parent peut déjà exister avant cet
            # import, notamment en mode « à la suite ».
            by_name = {m.name.strip().lower(): m for m in project.materials.all()}
            for material, parent_name in pending_parents:
                parent = by_name.get(parent_name.lower())
                if parent is None or parent.id == material.id:
                    raise CsvImportError(
                        f"Parent de kit introuvable pour « {material.name} » : « {parent_name} »."
                    )
                material.parent_material = parent
                material.save(update_fields=['parent_material'])

        return {'materials': created_count}


# --- Lieux ---

def import_venues_csv(project, text, mode):
    """Importe `text` (CSV lieux) dans `project`.

    `replace` : refuse (sans rien supprimer) si un lieu existant est encore
    référencé par un spectacle, un arrêt de tournée (`Show.venue`/
    `TransportStop.venue` sont en `PROTECT` — voir models.py, tournées
    multi-arrêts du 2026-08-04), OU du matériel qui en fait son lieu
    d'origine (`Material.venue` est en `SET_NULL` côté modèle, mais
    obligatoire à la saisie depuis le 2026-07-30 — le vider silencieusement
    contredirait cette règle) — même logique que `VenueViewSet.destroy`
    (revue code-reviewer du 2026-08-04 : le premier passage ne vérifiait
    que spectacles/transports, laissant un lieu encore utilisé comme
    origine de matériel se faire supprimer sans avertissement), appliquée
    ici à l'ensemble du projet avant de rien toucher."""
    _validate_mode(mode)
    rows = parse_csv_rows(text, VENUE_CSV_HEADER)

    with transaction.atomic():
        if mode == MODE_REPLACE:
            existing = list(project.venues.all())
            blocked = []
            for venue in existing:
                show_count = venue.shows.count()
                transport_count = TransportStop.objects.filter(venue=venue).count()
                material_count = venue.materials.count()
                if show_count or transport_count or material_count:
                    blocked.append(venue.name)
            if blocked:
                raise CsvImportError(
                    "Remplacement impossible : ces lieux sont encore utilisés par des spectacles, "
                    "déplacements ou du matériel — " + ', '.join(blocked) + ". Retire-les de ces "
                    "fiches avant de remplacer, ou importe en mode « à la suite »."
                )
            project.venues.all().delete()

        created_count = 0
        for row in rows:
            name = row.get('Nom', '').strip()
            if not name:
                raise CsvImportError("Une ligne de lieu n'a pas de nom.")
            Venue.objects.create(
                project=project,
                name=name,
                code=(row.get('Code', '') or '').strip()[:4],
                address=row.get('Adresse', ''),
                contact_name=row.get('Contact', ''),
                contact_info=row.get('Coordonnées contact', ''),
                notes=row.get('Notes', ''),
                is_storage=_yes_no(row.get('Entrepôt')),
                latitude=_parse_decimal(row.get('Latitude'), f"{name} — Latitude"),
                longitude=_parse_decimal(row.get('Longitude'), f"{name} — Longitude"),
            )
            created_count += 1

        return {'venues': created_count}


# --- Techniciens ---

def import_technicians_csv(project, text, mode):
    """Importe `text` (CSV techniciens) dans `project`.

    `replace` : supprime tous les techniciens existants du projet — cascade
    sur leurs assignations (`ShowTechnician`) et affectations de transport
    (`TransportTechnician`), voir models.py (on_delete=CASCADE). Averti côté
    frontend avant confirmation."""
    _validate_mode(mode)
    rows = parse_csv_rows(text, TECHNICIAN_CSV_HEADER)

    with transaction.atomic():
        if mode == MODE_REPLACE:
            project.technicians.all().delete()

        created_count = 0
        for row in rows:
            name = row.get('Nom', '').strip()
            if not name:
                raise CsvImportError("Une ligne de technicien n'a pas de nom.")
            Technician.objects.create(
                project=project,
                name=name,
                contact_info=row.get('Coordonnées', ''),
                specialty=row.get('Spécialité', ''),
                notes=row.get('Notes', ''),
            )
            created_count += 1

        return {'technicians': created_count}


# --- Spectacles ---

_EVENT_TYPE_BY_LABEL = {label.strip().lower(): key for key, label in Show.EVENT_TYPE_CHOICES}


def _event_type_from_label(label, show_title):
    event_type = _EVENT_TYPE_BY_LABEL.get((label or '').strip().lower())
    if event_type is None:
        valeurs = ', '.join(label for _key, label in Show.EVENT_TYPE_CHOICES)
        raise CsvImportError(
            f"Type d'événement inconnu pour « {show_title} » : « {label} ». Valeurs attendues : {valeurs}."
        )
    return event_type


def _parse_local_datetime(value, label):
    """Interprète `value` (ex. `2026-09-01 19:00`, tel qu'exporté par
    `ShowViewSet.export_csv`) comme une heure LOCALE (America/Montreal, voir
    config/settings.py `TIME_ZONE`) plutôt qu'UTC — c'est ce que Samuel voit
    et modifie dans Excel."""
    raw = (value or '').strip()
    if not raw:
        raise CsvImportError(f"Date/heure manquante ({label}).")
    naive = None
    for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S'):
        try:
            naive = datetime.datetime.strptime(raw, fmt)
            break
        except ValueError:
            continue
    if naive is None:
        raise CsvImportError(
            f"Date/heure invalide ({label}) : « {raw} ». Format attendu : AAAA-MM-JJ HH:MM."
        )
    return dj_timezone.make_aware(naive)


def import_shows_csv(project, text, mode):
    """Importe `text` (CSV spectacles) dans `project` — événements
    top-level uniquement (le CSV n'a pas de colonne pour rattacher un bloc à
    un événement parent ; utiliser l'export/import JSON complet pour ça, voir
    `portability.py`). `buffer_before_minutes`/`buffer_after_minutes`
    reprennent les valeurs par défaut de Settings (aucune colonne dédiée dans
    ce CSV), comme pour toute création normale d'un `Show`.

    `replace` : supprime tous les spectacles existants du projet — cascade
    sur `ShowMaterial`, `ShowTechnician`, `Transport` (et ses propres tables
    de liaison) — voir models.py. Averti côté frontend avant confirmation."""
    _validate_mode(mode)
    rows = parse_csv_rows(text, SHOW_CSV_HEADER)

    with transaction.atomic():
        if mode == MODE_REPLACE:
            project.shows.all().delete()

        venues_by_name = {v.name.strip().lower(): v for v in project.venues.all()}
        created_count = 0
        for row in rows:
            title = row.get('Titre', '').strip()
            if not title:
                raise CsvImportError("Une ligne de spectacle n'a pas de titre.")

            venue_name = row.get('Lieu', '').strip()
            venue = venues_by_name.get(venue_name.lower())
            if venue is None:
                raise CsvImportError(f"Lieu introuvable pour « {title} » : « {venue_name} ».")

            event_type = _event_type_from_label(row.get("Type d'événement"), title)
            start = _parse_local_datetime(row.get('Début'), f"{title} — Début")
            end = _parse_local_datetime(row.get('Fin'), f"{title} — Fin")
            if end <= start:
                raise CsvImportError(f"« {title} » : la fin doit être après le début.")

            Show.objects.create(
                project=project,
                title=title,
                venue=venue,
                event_type=event_type,
                start_datetime=start,
                end_datetime=end,
                notes=row.get('Notes', ''),
            )
            created_count += 1

        return {'shows': created_count}

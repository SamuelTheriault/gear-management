"""Export CSV par section — voir `MaterialViewSet.export_csv`,
`VenueViewSet.export_csv`, `TechnicianViewSet.export_csv`,
`ShowViewSet.export_csv` (views.py).

Ajouté le 2026-08-04 à la demande de Samuel : contrairement à l'export complet
d'un projet (JSON/XML réimportable — voir `portability.py`), ceci exporte UNE
section à la fois, pensée pour un passage vers un tableur (Excel) — pas pour
être réimportée dans l'app.

Point-virgule comme séparateur plutôt que virgule : Excel en français
interprète la virgule comme séparateur décimal, pas comme séparateur de
colonnes — un CSV `,` s'ouvre en une seule colonne en local FR. Le BOM UTF-8
en tête force Excel à lire le fichier en UTF-8 plutôt qu'en Latin-1 à l'ouverture
directe (sans lui, les accents s'affichent mal).
"""

import csv
import io

from django.http import HttpResponse
from django.utils import timezone as dj_timezone

# En-têtes — partagés avec `csv_import.py` (import), qui les valide AVANT
# toute écriture (`parse_csv_rows`). Les deux fichiers doivent rester
# synchronisés : une colonne renommée ici casserait la réimportation d'un
# export existant.
MATERIAL_CSV_HEADER = [
    'Nom', 'Catégorie', 'Quantité', 'Propriété', 'Lieu', 'Actif',
    'Kit parent', 'Fait partie du kit', 'Description', 'Notes',
]
VENUE_CSV_HEADER = [
    'Nom', 'Code', 'Adresse', 'Contact', 'Coordonnées contact',
    'Entrepôt', 'Latitude', 'Longitude', 'Notes',
]
TECHNICIAN_CSV_HEADER = ['Nom', 'Coordonnées', 'Spécialité', 'Notes']
SHOW_CSV_HEADER = ["Titre", "Type d'événement", 'Lieu', 'Début', 'Fin', 'Notes']

_YES = 'Oui'
_NO = 'Non'


class CsvImportError(Exception):
    """Fichier CSV invalide ou incomplet — toujours affichée telle quelle
    côté frontend (message déjà en français, voir les vues `import-csv`)."""


def parse_csv_rows(text, expected_header):
    """Valide l'en-tête de `text` (CSV brut, séparateur `;`) contre
    `expected_header` AVANT de rien importer — colonne(s) manquante(s)
    nommée(s) dans le message d'erreur, comme demandé par Samuel. Retourne
    une liste de dicts (une entrée par ligne, clés = colonnes de l'en-tête
    du FICHIER — un ordre de colonnes différent de `expected_header` est
    toléré, seule la présence de chaque colonne attendue compte)."""
    # Le BOM UTF-8 ajouté par `csv_response` (et par Excel à la sauvegarde)
    # doit être retiré avant de lire l'en-tête, sinon il colle à son premier
    # caractère et fait échouer la comparaison.
    cleaned = (text or '').lstrip('﻿').strip()
    if not cleaned:
        raise CsvImportError("Fichier CSV vide.")

    reader = csv.reader(io.StringIO(cleaned), delimiter=';')
    try:
        header = next(reader)
    except StopIteration:
        raise CsvImportError("Fichier CSV vide.")
    header = [col.strip() for col in header]

    missing = [col for col in expected_header if col not in header]
    if missing:
        raise CsvImportError(
            "Colonne(s) manquante(s) dans le fichier : " + ', '.join(missing) + "."
        )

    dict_reader = csv.DictReader(io.StringIO(cleaned), delimiter=';')
    return list(dict_reader)


def csv_response(filename, header, rows):
    """Construit une réponse CSV téléchargeable — `header` et chaque ligne de
    `rows` sont des listes de valeurs déjà mises en forme (chaînes/nombres)."""
    buffer = io.StringIO()
    buffer.write('﻿')
    writer = csv.writer(buffer, delimiter=';')
    writer.writerow(header)
    writer.writerows(rows)
    response = HttpResponse(buffer.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _bool_label(value):
    return _YES if value else _NO


# --- Constructeurs de lignes par section — voir les actions `export-csv`
# correspondantes sur les ViewSets (views.py), qui appellent `csv_response`
# avec ces lignes. Le format d'une ligne correspond exactement à ce que
# `csv_import.py` sait relire (même labels Oui/Non, même format de date) —
# un fichier exporté doit pouvoir être réimporté tel quel.

def materials_export_rows(project, include_inactive=True):
    """Une ligne par matériel du projet, triée par nom — voir
    `MaterialViewSet.export_csv`."""
    queryset = project.materials.select_related('category', 'venue', 'parent_material')
    if not include_inactive:
        queryset = queryset.filter(is_active=True)
    return [
        [
            m.name,
            m.category.name if m.category else '',
            m.quantity,
            m.get_ownership_status_display(),
            m.venue.name if m.venue else '',
            _bool_label(m.is_active),
            _bool_label(m.is_kit_parent),
            m.parent_material.name if m.parent_material else '',
            m.description,
            m.notes,
        ]
        for m in queryset.order_by('name')
    ]


def venues_export_rows(project):
    """Une ligne par lieu du projet, triée par nom — voir
    `VenueViewSet.export_csv`."""
    return [
        [
            v.name,
            v.code,
            v.address,
            v.contact_name,
            v.contact_info,
            _bool_label(v.is_storage),
            '' if v.latitude is None else v.latitude,
            '' if v.longitude is None else v.longitude,
            v.notes,
        ]
        for v in project.venues.order_by('name')
    ]


def technicians_export_rows(project):
    """Une ligne par technicien du projet, triée par nom — voir
    `TechnicianViewSet.export_csv`."""
    return [
        [t.name, t.contact_info, t.specialty, t.notes]
        for t in project.technicians.order_by('name')
    ]


def shows_export_rows(project):
    """Une ligne par spectacle TOP-LEVEL du projet (pas de bloc rattaché —
    le CSV n'a pas de colonne pour l'événement parent, voir le docstring de
    `csv_import.import_shows_csv`), triée par date de début — voir
    `ShowViewSet.export_csv`."""
    queryset = project.shows.filter(parent_show__isnull=True).select_related('venue')
    return [
        [
            s.title,
            s.get_event_type_display(),
            s.venue.name if s.venue else '',
            dj_timezone.localtime(s.start_datetime).strftime('%Y-%m-%d %H:%M'),
            dj_timezone.localtime(s.end_datetime).strftime('%Y-%m-%d %H:%M'),
            s.notes,
        ]
        for s in queryset.order_by('start_datetime')
    ]

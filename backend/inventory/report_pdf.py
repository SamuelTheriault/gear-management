"""Rendu PDF des sorties de rapport (WeasyPrint) — chantier 2026-08-08.

Le contenu vient de `reports.build_payload`, exactement le même que celui
servi à la page publique : c'est ce qui garantit que le papier et l'écran ne
peuvent pas diverger. Ici on ne fait que la mise en page.

**Pourquoi WeasyPrint et pas l'impression du navigateur** : un PDF produit par
le serveur sort identique partout, s'archive, se joint à un courriel, et ne
dépend pas du navigateur ni de la boîte de dialogue d'impression de la
personne. Une salle partenaire qui reçoit « la feuille » doit recevoir un
fichier, pas une invitation à faire Ctrl+P.

**Coût opérationnel à connaître** : WeasyPrint charge Pango et HarfBuzz au
premier import (paquets `libpango-1.0-0`, `libpangoft2-1.0-0`,
`libharfbuzz-subset0` dans le Dockerfile). L'import est donc DIFFÉRÉ à
l'intérieur de `render_pdf` plutôt que fait en tête de module : sans ça, tout
démarrage de Django — y compris `manage.py check` en CI et le boot du
conteneur — paierait ces bibliothèques, et surtout planterait avec un
`OSError` opaque si un paquet système venait à manquer, au lieu d'échouer
proprement sur la seule requête qui demande un PDF.
"""

import logging
from pathlib import Path

from django.template.loader import render_to_string
from django.utils import timezone

from .models import ReportShare
from .report_shares import build_share_url, qr_svg
from .reports import build_payload

logger = logging.getLogger('inventory')

#: Répertoire des polices embarquées (JetBrains Mono, 4 graisses). Servi aux
#: `@font-face` du gabarit sous forme d'URL `file://` — jamais par le réseau.
FONTS_DIR = Path(__file__).resolve().parent / 'fonts'

GABARITS = {
    ReportShare.KIND_TRANSPORT: 'reports/transport.html',
    ReportShare.KIND_SHOW: 'reports/show.html',
    ReportShare.KIND_TECHNICIAN: 'reports/technician.html',
    ReportShare.KIND_DAY: 'reports/day.html',
}

RUBANS = {
    ReportShare.KIND_TRANSPORT: 'Fiche de transport',
    ReportShare.KIND_SHOW: 'Fiche spectacle',
    ReportShare.KIND_TECHNICIAN: 'Parcours technicien',
    ReportShare.KIND_DAY: 'Horaire de la journée',
}

LEGENDES_SIGNATURE = {
    ReportShare.KIND_TRANSPORT: 'Signature · chargement vérifié',
    ReportShare.KIND_SHOW: 'Signature · fiche reçue',
    ReportShare.KIND_TECHNICIAN: 'Signature · feuille de route reçue',
    ReportShare.KIND_DAY: 'Signature · régie',
}

_MOIS = [
    'janvier', 'février', 'mars', 'avril', 'mai', 'juin',
    'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre',
]
_JOURS = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']


def _entete(share, rapport):
    """Titre, référence et statut affichés dans l'en-tête répété.

    Chaque type de feuille a son propre « qu'est-ce que je regarde » : pour
    une tournée c'est l'itinéraire, pour un parcours c'est le nom de la
    personne. Centralisé ici pour que les quatre gabarits partagent le même
    bandeau sans dupliquer la logique.
    """
    if share.kind == ReportShare.KIND_TRANSPORT:
        arrets = rapport['stops']
        depart = arrets[0]['venue']['name'] if arrets else '?'
        arrivee = arrets[-1]['venue']['name'] if arrets else '?'
        jour = rapport['scheduled_datetime']
        return {
            'titre': f'{depart} → {arrivee}',
            'reference': f'T-{share.transport_id:02d}',
            'statut': rapport['status_display'],
            'statut_attention': rapport['status'] != 'confirmed',
            'sous_contexte': _jour_long(jour) if jour else '',
        }
    if share.kind == ReportShare.KIND_SHOW:
        return {
            'titre': rapport['title'],
            'reference': '',
            'statut': rapport['event_type_display'],
            'statut_attention': False,
            'sous_contexte': _jour_long(rapport['start_datetime']),
        }
    if share.kind == ReportShare.KIND_TECHNICIAN:
        return {
            'titre': rapport['name'],
            'reference': '',
            'statut': rapport['specialty'],
            'statut_attention': False,
            'sous_contexte': '',
        }
    return {
        'titre': _jour_long(rapport['day']),
        'reference': '',
        'statut': f"{rapport['item_count']} éléments",
        'statut_attention': False,
        'sous_contexte': '',
    }


def _jour_long(valeur):
    if valeur is None:
        return ''
    d = timezone.localtime(valeur).date() if hasattr(valeur, 'hour') else valeur
    return f'{_JOURS[d.weekday()]} {d.day} {_MOIS[d.month - 1]} {d.year}'


def nom_fichier(share, rapport):
    """Nom du fichier téléchargé — lisible dans un dossier de production et
    dans une pièce jointe de courriel, pas `rapport(3).pdf`."""
    from django.utils.text import slugify

    entete = _entete(share, rapport)
    morceaux = [RUBANS[share.kind], entete['titre']]
    if entete['sous_contexte']:
        morceaux.append(entete['sous_contexte'])
    return slugify('-'.join(morceaux))[:120] + '.pdf'


def render_html(share, request=None):
    """HTML complet de la feuille — utile pour déboguer une mise en page sans
    repasser par WeasyPrint (le rendu diffère du navigateur, mais le contenu
    et la structure sont les mêmes)."""
    rapport = build_payload(share)
    url = build_share_url(share, request)
    contexte = {
        'r': rapport,
        'share': share,
        'projet': share.project.name,
        'ruban': RUBANS[share.kind],
        'legende_signature': LEGENDES_SIGNATURE[share.kind],
        'qr': qr_svg(url),
        'url': url,
        'imprime_le': timezone.localtime(),
        'fonts': FONTS_DIR.as_uri(),
        'titre_document': f'{RUBANS[share.kind]} — {share.project.name}',
    }
    contexte.update(_entete(share, rapport))
    return render_to_string(GABARITS[share.kind], contexte), rapport


def render_pdf(share, request=None):
    """Renvoie `(octets_pdf, nom_fichier)`.

    Import de WeasyPrint différé — voir le docstring de module.
    """
    from weasyprint import HTML

    html, rapport = render_html(share, request)
    # `base_url` sur le répertoire de l'app : les `@font-face` du gabarit
    # utilisent déjà des URL `file://` absolues, mais un chemin de base
    # correct évite toute résolution surprise si un gabarit venait à
    # référencer une ressource relative.
    pdf = HTML(string=html, base_url=str(Path(__file__).resolve().parent)).write_pdf()
    logger.info(
        "PDF rendu — partage %s (%s), %d octets",
        share.token[:6], share.kind, len(pdf),
    )
    return pdf, nom_fichier(share, rapport)

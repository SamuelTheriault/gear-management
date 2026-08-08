"""Vues PUBLIQUES des sorties de rapport — les seules de l'API sans session.

Tout le reste de l'API est derrière `IsAuthenticated` + `HasProjectAccess`
(voir `permissions.py`). Ce module est l'exception, délibérée et étroite :
c'est ce qui se trouve au bout du code QR imprimé en pied de feuille. Voir
le docstring de `ReportShare` (models.py) pour le modèle de menace.

Règles que TOUTE vue ajoutée ici doit respecter :

1. **Lecture seule.** Aucune méthode d'écriture, jamais. Un lien qui fuite ne
   doit pas pouvoir modifier la production.
2. **Un jeton = un objet.** On sert le contenu de la cible du partage et rien
   d'autre. Pas de `?project=`, pas de liste, aucun paramètre qui élargirait
   la portée.
3. **404 uniforme.** Jeton inconnu, révoqué ou expiré : même réponse. Sinon
   la vue devient un oracle qui confirme l'existence d'un jeton.
4. **Non indexable.** `X-Robots-Tag` sur chaque réponse, plus un `robots.txt`
   qui interdit `/p/` (voir `config/urls.py`). Une feuille de tournée avec
   les coordonnées d'un quai de déchargement n'a rien à faire dans Google.
5. **Non mise en cache.** `Cache-Control: no-store` : le contenu doit être à
   jour — c'est la promesse même du QR — et ne doit pas rester dans le cache
   d'un proxy partagé ou d'un téléphone prêté.
"""

import logging

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from .report_shares import build_share_url, record_access, resolve_share
from .report_pdf import render_pdf
from .reports import build_payload

logger = logging.getLogger('inventory')


class PublicReportThrottle(ScopedRateThrottle):
    """Limite de débit par adresse IP sur les vues publiques.

    Le taux (`DEFAULT_THROTTLE_RATES['public-report']`, voir settings.py) est
    volontairement généreux : une équipe entière sur le wifi d'une salle
    partage une seule IP publique, et une limite serrée bloquerait tout le
    monde parce qu'un technicien a rechargé trois fois. Le but ici n'est pas
    de rationner l'usage légitime mais de rendre coûteuse une énumération
    automatisée de jetons — ce que les 128 bits d'entropie rendent de toute
    façon déjà vain.
    """

    scope = 'public-report'


def _harden(response):
    """En-têtes communs à toute réponse publique — voir les règles 4 et 5."""
    response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    response['Cache-Control'] = 'no-store, max-age=0'
    response['Referrer-Policy'] = 'no-referrer'
    return response


def _not_found():
    """404 uniforme (règle 3), avec un message qui aide la personne devant le
    téléphone sans rien révéler à qui sonde l'API."""
    return _harden(Response(
        {'detail': "Ce lien n'est plus valide. Demande une version à jour à la personne qui te l'a remis."},
        status=status.HTTP_404_NOT_FOUND,
    ))


@api_view(['GET'])
@permission_classes([AllowAny])
@throttle_classes([PublicReportThrottle])
def public_report(request, token):
    """Contenu à jour de la feuille désignée par `token`.

    Consommée par la page Vue publique `/p/<token>`, celle-là même que le QR
    imprimé fait ouvrir. Le PDF passe par le même assemblage de données
    (`reports.build_payload`) pour que papier et écran ne puissent pas
    diverger.
    """
    share = resolve_share(token)
    if share is None:
        return _not_found()

    record_access(share)

    payload = build_payload(share)
    return _harden(Response({
        'kind': share.kind,
        'kind_display': share.get_kind_display(),
        'project': share.project.name,
        'url': build_share_url(share, request),
        # Horodatage de CETTE lecture, à afficher bien en vue sur la page.
        # C'est ce que la personne compare avec la date imprimée en pied de
        # sa feuille pour savoir si sa copie papier a pris du retard — sans
        # cette comparaison, le QR ne prouve rien. On renvoie l'instant de
        # lecture et non un `updated_at` stocké : les modèles n'en ont pas,
        # et surtout une feuille dépend de dizaines de lignes liées
        # (arrêts, matériel, équipe) dont aucune date unique ne rendrait
        # compte. « Lu à l'instant » est à la fois vrai et suffisant.
        'fetched_at': timezone.now(),
        'report': payload,
    }))


@api_view(['GET'])
@permission_classes([AllowAny])
@throttle_classes([PublicReportThrottle])
def public_report_pdf(request, token):
    """Version PDF imprimable de la même feuille.

    Public au même titre que la page : la personne qui a scanné le QR doit
    pouvoir réimprimer sa feuille sans compte — c'est le cas d'usage
    quotidien d'un directeur technique de salle qui veut sa copie papier
    avant l'arrivée du camion. Le PDF ne contient rien de plus que la page.

    `Content-Disposition: inline` et non `attachment` : sur un téléphone, un
    PDF en pièce jointe disparaît dans le dossier Téléchargements, tandis
    qu'en `inline` il s'ouvre dans la visionneuse — et l'impression reste à
    un geste de là.
    """
    share = resolve_share(token)
    if share is None:
        return _not_found()

    record_access(share)

    try:
        pdf, nom = render_pdf(share, request)
    except OSError:
        # WeasyPrint échoue à l'import si les bibliothèques système (Pango,
        # HarfBuzz) manquent dans l'image — voir le Dockerfile. On journalise
        # et on renvoie une erreur lisible plutôt qu'un 500 opaque : la page
        # web, elle, reste disponible.
        logger.exception("Rendu PDF impossible pour le partage %s", share.token[:6])
        return _harden(Response(
            {'detail': "La version PDF est momentanément indisponible. La page en ligne, elle, reste à jour."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        ))

    reponse = HttpResponse(pdf, content_type='application/pdf')
    reponse['Content-Disposition'] = f'inline; filename="{nom}"'
    return _harden(reponse)

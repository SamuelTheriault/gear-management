"""Émission, résolution et rendu QR des liens publics de rapport.

Complète le modèle `ReportShare` (models.py) avec ce qui n'a pas sa place
dans une classe de modèle : la résolution d'un jeton entrant, la
construction de l'URL absolue, et la génération du code QR imprimé.

Voir `public_views.py` pour les vues qui consomment ces fonctions, et le
docstring de `ReportShare` pour le modèle de menace (le jeton EST
l'authentification).
"""

import io

import segno
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import ReportShare

# Correction d'erreur du QR. 'm' ≈ 15 % de modules récupérables : le bon
# compromis pour une feuille qui sera pliée, cornée et photocopiée, sans
# gonfler le symbole comme le ferait 'q' ou 'h' (une correction plus forte
# = plus de modules = modules plus petits à surface d'impression constante,
# donc au final MOINS lisible sur un cadran de 25 mm).
QR_ERROR_LEVEL = 'm'

# Côté du QR imprimé. Sous ~20 mm, un téléphone d'appoint dans un quai mal
# éclairé décroche ; au-delà de 30 mm le code mange le pied de page.
QR_SIZE_MM = 25


def build_share_url(share, request=None):
    """URL absolue de la page publique à jour — c'est elle qu'encode le QR.

    Deux sources, dans l'ordre :

    1. `PUBLIC_BASE_URL` (settings), quand elle est configurée. Nécessaire
       dès que le PDF peut être produit hors d'un cycle requête/réponse
       (tâche planifiée, commande de gestion, envoi par courriel).
    2. À défaut, l'origine de la requête courante. `SECURE_PROXY_SSL_HEADER`
       est déjà configuré (config/settings.py), donc `build_absolute_uri`
       renvoie bien `https://` derrière le proxy Railway et non `http://`.

    Lève `ValueError` si aucune des deux n'est disponible : mieux vaut une
    erreur franche au moment de générer la feuille qu'un QR imprimé à 40
    exemplaires qui pointe vers `http://testserver/p/...`.
    """
    base = (getattr(settings, 'PUBLIC_BASE_URL', '') or '').rstrip('/')
    if base:
        return f'{base}{share.path}'
    if request is not None:
        return request.build_absolute_uri(share.path)
    raise ValueError(
        "Impossible de construire l'URL publique : ni PUBLIC_BASE_URL "
        "(settings) ni requête HTTP disponible.",
    )


def qr_svg(url, size_mm=QR_SIZE_MM):
    """Code QR en SVG inline, dimensionné en millimètres.

    **Pourquoi pas simplement `segno.svg_inline()`** : sa sortie est un
    `<svg width="37" height="37">` SANS `viewBox`. Sans viewBox, aucun
    système de coordonnées n'est déclaré, et WeasyPrint ignore purement et
    simplement toute largeur qu'on impose en CSS — le QR sort à sa taille
    intrinsèque (~9 mm), illisible. Vérifié dans le bac à sable le
    2026-08-08. On réinjecte donc le viewBox et les dimensions physiques.

    **Pourquoi du SVG et pas un PNG** : c'est du vectoriel, donc net à la
    résolution réelle de l'imprimante, quelle qu'elle soit. Un PNG de 180 px
    imprimé à 25 mm tombe à ~180 dpi et commence à baver.

    **Pourquoi pas `api.qrserver.com`** (utilisé par les maquettes Claude
    Design) : cela transmettrait l'URL privée de partage à un tiers à chaque
    rendu — exactement le secret qu'on cherche à protéger — et rendrait la
    production d'une feuille dépendante de la disponibilité d'un service
    externe. segno est du Python pur, sans dépendance.
    """
    code = segno.make(url, error=QR_ERROR_LEVEL)
    modules = code.symbol_size(border=0)[0]
    svg = code.svg_inline(dark='#0f1216', border=0)
    return svg.replace(
        '<svg',
        f'<svg viewBox="0 0 {modules} {modules}" '
        f'width="{size_mm}mm" height="{size_mm}mm"',
        1,
    )


def qr_png_data_uri(url, scale=10):
    """Repli PNG en data-URI, pour un canal qui n'accepte pas le SVG inline
    (aperçu HTML dans un courriel, par exemple). Le SVG reste le défaut pour
    tout ce qui part à l'impression."""
    import base64

    buf = io.BytesIO()
    segno.make(url, error=QR_ERROR_LEVEL).save(buf, kind='png', scale=scale, border=0)
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


# --- Émission -----------------------------------------------------------------

#: Champ FK de `ReportShare` porteur de la cible, par type de rapport.
TARGET_FIELD = {
    ReportShare.KIND_TRANSPORT: 'transport',
    ReportShare.KIND_SHOW: 'show',
    ReportShare.KIND_TECHNICIAN: 'technician',
    ReportShare.KIND_DAY: 'day',
}


def get_or_create_share(*, project, kind, target, created_by=None, expires_at=None):
    """Renvoie `(share, created)` — le partage ACTIF de cette cible, ou un
    nouveau.

    Réutiliser plutôt que réémettre est une décision structurante, détaillée
    dans le docstring de `ReportShare` : réimprimer une feuille ne doit
    jamais périmer les copies déjà distribuées sur le terrain.

    La course entre deux requêtes simultanées est réglée par les contraintes
    d'unicité partielles en base, pas par un verrou applicatif : on tente la
    création, et si la contrainte saute c'est qu'un partage actif vient
    d'apparaître — on le relit.
    """
    field = TARGET_FIELD[kind]
    lookup = {'project': project, 'kind': kind, field: target, 'revoked_at__isnull': True}

    existing = ReportShare.objects.filter(**lookup).first()
    if existing is not None and existing.is_active:
        return existing, False
    if existing is not None:
        # Actif au sens « non révoqué » mais expiré : on relance l'horloge
        # sur le MÊME jeton plutôt que d'en émettre un nouveau, sinon les
        # feuilles déjà imprimées deviendraient définitivement mortes.
        existing.expires_at = expires_at
        existing.save(update_fields=['expires_at'])
        return existing, False

    try:
        with transaction.atomic():
            return ReportShare.objects.create(
                project=project, kind=kind, created_by=created_by,
                expires_at=expires_at, **{field: target},
            ), True
    except IntegrityError:
        return ReportShare.objects.get(**lookup), False


def resolve_share(token):
    """`ReportShare` actif correspondant à `token`, ou `None`.

    Un jeton inconnu, révoqué ou expiré donne le même `None` — les vues
    publiques en font toutes un 404 identique. Distinguer les cas
    confirmerait à un curieux qu'un jeton a existé, et transformerait la
    réponse en oracle.
    """
    if not token:
        return None
    share = ReportShare.objects.filter(token=token).select_related(
        'project', 'transport', 'show', 'technician',
    ).first()
    if share is None or not share.is_active:
        return None
    return share


def record_access(share):
    """Horodate la consultation et incrémente le compteur.

    Écriture ciblée via `F()` et `update()` : pas de lecture-modification-
    écriture (deux scans simultanés du même QR ne se perdent pas), et surtout
    aucun autre champ n'est réécrit — un `save()` complet ici risquerait
    d'écraser une révocation faite entre-temps depuis l'interface.
    """
    from django.db.models import F

    ReportShare.objects.filter(pk=share.pk).update(
        last_accessed_at=timezone.now(),
        access_count=F('access_count') + 1,
    )

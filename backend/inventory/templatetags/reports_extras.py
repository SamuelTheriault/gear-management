"""Filtres de gabarit des sorties de rapport (chantier 2026-08-08).

Uniquement de la mise en forme d'affichage — l'assemblage des données reste
dans `reports.py`. Ces filtres existent plutôt que des `{{ x|date:"..." }}`
en ligne pour deux raisons : la convention horaire francophone (« 8 h 35 »,
avec espaces, et non « 08:35 ») demande un post-traitement, et une feuille de
tournée affiche la même heure à vingt endroits — la règle doit vivre à un
seul.
"""

from django import template
from django.utils import timezone

register = template.Library()

_MOIS = [
    'janvier', 'février', 'mars', 'avril', 'mai', 'juin',
    'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre',
]
_JOURS = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']


@register.filter
def heure(valeur):
    """« 8 h 35 ». Espaces autour du « h » : c'est la convention typographique
    québécoise, et c'est aussi plus lisible en diagonale sur un quai."""
    if not valeur:
        return '—'
    local = timezone.localtime(valeur) if timezone.is_aware(valeur) else valeur
    return f'{local.hour} h {local.minute:02d}'


@register.filter
def jour_long(valeur):
    """« jeudi 14 septembre 2026 »."""
    if not valeur:
        return '—'
    d = timezone.localtime(valeur).date() if hasattr(valeur, 'hour') else valeur
    return f'{_JOURS[d.weekday()]} {d.day} {_MOIS[d.month - 1]} {d.year}'


@register.filter
def jour_court(valeur):
    """« 14 sept. » — pour les colonnes serrées du parcours technicien."""
    if not valeur:
        return '—'
    d = timezone.localtime(valeur).date() if hasattr(valeur, 'hour') else valeur
    mois = _MOIS[d.month - 1]
    return f'{d.day} {mois[:4]}.' if len(mois) > 5 else f'{d.day} {mois}'


@register.filter
def km(metres):
    """Mètres → « 41,3 » (virgule décimale). Chaîne vide si inconnu, pour que
    le gabarit puisse simplement tester la valeur."""
    if not metres:
        return ''
    return f'{metres / 1000:.1f}'.replace('.', ',')


@register.filter
def duree(minutes):
    """« 1 h 25 » au-delà de l'heure, « 45 min » en deçà."""
    if not minutes:
        return '—'
    if minutes < 60:
        return f'{minutes} min'
    return f'{minutes // 60} h {minutes % 60:02d}'

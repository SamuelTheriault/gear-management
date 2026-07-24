"""
Signaux de régénération automatique des propositions de transport (module
transport, ajouté le 2026-07-24). Voir `transport_autogen.py` pour la logique.

Décision Samuel du 2026-07-24 : la génération est **automatique**, déclenchée
à chaque changement pouvant modifier l'ensemble des déplacements nécessaires :
- assignation de matériel à un spectacle (`ShowMaterial`) ;
- transport CONFIRMÉ créé/modifié/supprimé (change la couverture) ;
- ligne de matériel transporté d'un transport confirmé (`TransportMaterial`) ;
- spectacle créé/modifié (horaire ou lieu → change les besoins).

Toutes les régénérations passent par `regenerate_project_proposals`, qui pose
une garde de réentrance (`is_regenerating`) : les écritures qu'elle fait
(création/suppression de propositions) redéclencheraient ces mêmes signaux, on
les neutralise donc pendant qu'une régénération est en cours.
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Show, ShowMaterial, Transport, TransportMaterial
from .transport_autogen import is_regenerating, regenerate_project_proposals


def _project_of_show(show_id):
    """Projet d'un spectacle (par id), ou None s'il n'existe plus (ex. suppression
    en cascade). Résolu par requête pour ne pas dépendre d'une relation
    éventuellement déjà détruite sur l'instance du signal."""
    if show_id is None:
        return None
    show = Show.objects.filter(id=show_id).select_related('project').first()
    return show.project if show else None


def _regenerate_for_show(show_id):
    """Régénère les propositions du projet du spectacle `show_id`, sauf si une
    régénération est déjà en cours (garde de réentrance)."""
    if is_regenerating():
        return
    project = _project_of_show(show_id)
    if project is not None:
        regenerate_project_proposals(project)


@receiver(post_save, sender=ShowMaterial)
@receiver(post_delete, sender=ShowMaterial)
def _on_show_material_change(instance, **kwargs):
    """Assignation de matériel créée/modifiée/supprimée → régénère le projet."""
    _regenerate_for_show(instance.show_id)


@receiver(post_save, sender=Transport)
@receiver(post_delete, sender=Transport)
def _on_transport_change(instance, **kwargs):
    """Transport confirmé créé/modifié/supprimé → régénère (la couverture change).

    On ignore les transports `to_approve` : ce sont les propositions elles-mêmes,
    gérées par la régénération (et neutralisées par la garde de réentrance)."""
    if instance.status != Transport.STATUS_CONFIRMED:
        return
    _regenerate_for_show(instance.show_id)


@receiver(post_save, sender=TransportMaterial)
@receiver(post_delete, sender=TransportMaterial)
def _on_transport_material_change(instance, **kwargs):
    """Ligne de matériel transporté changée sur un transport confirmé → régénère.

    Couvre le cas de la création via l'API (les lignes sont créées après le
    transport lui-même : ce signal capte l'ajout du matériel et régénère avec
    la couverture correcte)."""
    if is_regenerating():
        return
    transport = Transport.objects.filter(id=instance.transport_id).select_related('show__project').first()
    if transport is None or transport.status != Transport.STATUS_CONFIRMED:
        return
    _regenerate_for_show(transport.show_id)


@receiver(post_save, sender=Show)
def _on_show_change(instance, **kwargs):
    """Spectacle créé/modifié (horaire ou lieu) → régénère son projet."""
    if is_regenerating():
        return
    regenerate_project_proposals(instance.project)

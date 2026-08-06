"""
Que devient une tournée quand on supprime un spectacle qu'elle dessert ?

Ajouté le 2026-08-05 à la demande de Samuel : « si on efface un événement qui
fait partie d'une séquence de plusieurs autres arrêts, on retire l'arrêt et le
matériel associé mais on n'efface pas le transport ».

Avant ça, `Transport.show` étant en CASCADE, supprimer un spectacle emportait
la tournée ENTIÈRE — y compris les arrêts qui servaient d'autres salles et
d'autres spectacles. Sur un aller simple A → B c'était sans conséquence ; sur
une tournée à trois arrêts, ça effaçait du travail sans rapport avec le
spectacle supprimé.

Règle appliquée par `detach_show_from_transports()` :

1. Les arrêts **au lieu du spectacle supprimé** sont retirés, avec les lignes
   de matériel qui les référencent (`TransportMaterial.load_stop`/
   `unload_stop` sont en CASCADE — c'est le « matériel associé » demandé).
2. Les arrêts restants sont renumérotés, et la durée du segment du premier
   arrêt remise à 0 (c'est un départ, pas un trajet).
3. Le rattachement `Transport.show` est **réancré** sur un spectacle d'un
   arrêt ENCORE DESSERVI, hors de la famille du spectacle supprimé — le plus
   proche dans le temps de l'heure de départ (voir `_reancrage`, qui explique
   pourquoi ces deux exclusions comptent). Ce champ borne les horaires du
   déplacement (voir `validate_transport_window`) et n'est pas nullable :
   sans candidat, la tournée n'a plus de raison d'être.
4. La tournée est supprimée dans deux cas seulement : moins de deux arrêts
   restants (un trajet a besoin d'un départ et d'une arrivée), ou aucun
   spectacle à réancrer.

**Choix par défaut, à revoir avec Samuel si besoin** : le réancrage est
automatique et silencieux. Les deux autres options écartées étaient de rendre
`Transport.show` nullable (migration + tout le code qui suppose un spectacle)
et de demander le nouveau rattachement dans la fenêtre de confirmation (une
suppression devient un formulaire).

Appelé depuis `ShowViewSet.perform_destroy` — donc sur la suppression
explicite d'un spectacle, pas sur une cascade de suppression de projet, où
réancrer sur un spectacle lui-même en cours de suppression n'aurait aucun
sens.
"""

from .models import Transport, TransportStop


def _reancrage(transport, show, arrets_restants):
    """Spectacle sur lequel réancrer cette tournée, ou `None`.

    Cherché parmi les spectacles des lieux ENCORE DESSERVIS — d'où
    `arrets_restants` en paramètre plutôt qu'une relecture de
    `transport.stops` : au moment de l'appel, les arrêts à retirer sont
    toujours en base, et les inclure réancrerait la tournée sur un lieu
    qu'elle ne visite plus. `Transport.show` borne les horaires du
    déplacement (voir `validate_transport_window`), une ancre au mauvais
    endroit fausse cette validation.

    Toute la FAMILLE du spectacle supprimé est écartée (`Show.family_ids`),
    pas seulement lui : ses blocs de montage/démontage sont au même lieu et
    démarrent juste avant, donc souvent « les plus proches » — les choisir
    comme ancre ferait mourir la tournée avec eux, en cascade, alors qu'on
    vient justement de la sauver.

    Le plus proche de l'heure de départ l'emporte : c'est celui que la
    tournée sert le plus vraisemblablement.
    """
    from .models import Show

    lieux = {arret.venue_id for arret in arrets_restants}
    if not lieux:
        return None
    candidats = list(
        Show.objects
        .filter(venue_id__in=lieux, project_id=transport.show.project_id)
        .exclude(id__in=show.family_ids)
    )
    if not candidats:
        return None
    repere = transport.scheduled_datetime
    if repere is None:
        return min(candidats, key=lambda s: s.start_datetime)
    return min(candidats, key=lambda s: abs(s.start_datetime - repere))


def plan_show_deletion(show):
    """Ce qu'il adviendrait des tournées si `show` était supprimé.

    Retourne `(supprimes, raccourcis)` — deux listes d'ids de `Transport`.
    Sert à annoncer l'effet réel dans la fenêtre de confirmation (voir
    `ShowSerializer.deletion_impact`), sans rien modifier.
    """
    supprimes, raccourcis = [], []
    for transport in show.transports.prefetch_related('stops').all():
        restants = [stop for stop in transport.stops.all() if stop.venue_id != show.venue_id]
        if len(restants) < 2 or _reancrage(transport, show, restants) is None:
            supprimes.append(transport.id)
        else:
            raccourcis.append(transport.id)
    return supprimes, raccourcis


def detach_show_from_transports(show):
    """Retire `show` de ses tournées — voir la note de module.

    À appeler AVANT la suppression du spectacle : les tournées conservées sont
    réancrées sur un autre spectacle, ce qui les soustrait à la cascade.
    Retourne `(supprimes, raccourcis)`, les mêmes listes d'ids que
    `plan_show_deletion`.
    """
    supprimes, raccourcis = [], []
    for transport in list(show.transports.prefetch_related('stops').all()):
        a_retirer = [stop for stop in transport.stops.all() if stop.venue_id == show.venue_id]
        restants = [stop for stop in transport.stops.all() if stop.venue_id != show.venue_id]

        nouvelle_ancre = _reancrage(transport, show, restants) if len(restants) >= 2 else None
        if nouvelle_ancre is None:
            # Laissé à la cascade : la tournée n'a plus ni séquence valable ni
            # spectacle à desservir.
            supprimes.append(transport.id)
            continue

        # Le matériel chargé/déchargé à ces arrêts part avec eux (CASCADE sur
        # `TransportMaterial.load_stop`/`unload_stop`).
        TransportStop.objects.filter(id__in=[stop.id for stop in a_retirer]).delete()

        for position, stop in enumerate(sorted(restants, key=lambda s: s.order)):
            # Le premier arrêt est un départ : pas de trajet qui y mène.
            duree = 0 if position == 0 else stop.travel_minutes_from_previous
            if stop.order != position or stop.travel_minutes_from_previous != duree:
                stop.order = position
                stop.travel_minutes_from_previous = duree
                stop.save(update_fields=['order', 'travel_minutes_from_previous'])

        Transport.objects.filter(id=transport.id).update(show=nouvelle_ancre)
        raccourcis.append(transport.id)
    return supprimes, raccourcis

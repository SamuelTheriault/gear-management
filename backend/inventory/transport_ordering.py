"""
Suggestion d'ordre optimal des arrêts d'une tournée — chantier 3 des travaux
transport (2026-08-06/07, décisions de Samuel).

Principe : à séquence d'arrêts donnée, proposer l'ordre qui minimise le temps
de route total (matrice de trajets Google Routes), en respectant deux
contraintes :

- le PREMIER arrêt est fixe — c'est le point de départ (l'entrepôt, ou là où
  le camion se trouve) ;
- les précédences de matériel : une ligne chargée à l'arrêt X et déchargée à
  l'arrêt Y impose que X passe avant Y dans le nouvel ordre — on ne dépose
  pas ce qu'on n'a pas encore ramassé.

Méthode : énumération EXACTE des permutations des arrêts non fixes. Les
tournées réelles font 2 à 8 arrêts (7! = 5 040 ordres au pire) — inutile
d'approximer, l'optimum est garanti et le calcul instantané. La matrice de
trajets est demandée à `maps.estimate_travel` (durée + distance dans le même
appel) pour chaque couple ORIENTÉ de lieux distincts réellement utiles, avec
mémoïsation — une tournée de 5 lieux distincts = au plus 20 appels Routes.

La suggestion est STATELESS : elle reçoit la séquence en cours d'édition
(lieux + portions de matériel), ne lit ni n'écrit aucune tournée — c'est le
frontend qui applique le résultat au formulaire, et l'enregistrement normal
qui persiste. Voir `TransportViewSet.order_suggestion`.

Si un seul couple de lieux nécessaire n'est pas estimable (clé API absente,
lieu sans GPS, erreur réseau), la suggestion est impossible : on renvoie une
erreur claire plutôt qu'un optimum sur des données inventées
(`OrderingUnavailable`).
"""

from itertools import permutations

from .maps import estimate_travel


class OrderingUnavailable(Exception):
    """La matrice de trajets ne peut pas être construite (clé Google Routes
    absente, lieu sans coordonnées GPS, ou appel en échec) — message prêt à
    afficher dans `args[0]`."""


def _travel_matrix(venues):
    """Matrice `{(venue_id_a, venue_id_b): {'minutes', 'meters'}}` pour tous
    les couples orientés de lieux distincts de `venues` (mémoïsée par couple —
    un lieu qui revient deux fois dans la séquence ne coûte rien de plus).

    Lève `OrderingUnavailable` au premier couple non estimable : un optimum
    calculé sur un trou de matrice n'aurait aucun sens.
    """
    matrix = {}
    uniques = {v.id: v for v in venues}
    for a_id, a in uniques.items():
        for b_id, b in uniques.items():
            if a_id == b_id or (a_id, b_id) in matrix:
                continue
            estimation = estimate_travel(a, b)
            if estimation is None:
                raise OrderingUnavailable(
                    f"Impossible d'estimer le trajet « {a.name} » → « {b.name} » : "
                    "clé Google Routes absente, lieu sans coordonnées GPS, ou appel en échec. "
                    "La suggestion d'ordre a besoin de la matrice complète."
                )
            matrix[(a_id, b_id)] = estimation
    return matrix


def _sequence_cost(venue_ids, matrix):
    """`(minutes, meters)` totaux d'une séquence de lieux, via la matrice."""
    minutes = 0
    meters = 0
    for a, b in zip(venue_ids, venue_ids[1:]):
        segment = matrix[(a, b)]
        minutes += segment['minutes']
        meters += segment['meters'] or 0
    return minutes, meters


def suggest_stop_order(venues, precedence_pairs):
    """Ordre optimal des arrêts, contraintes respectées.

    `venues` : lieux de la séquence ACTUELLE, indexés par position (le
    premier est fixe). `precedence_pairs` : couples `(load_index,
    unload_index)` en positions actuelles — chargement avant déchargement.

    Retourne un dict :
    - `order` : les positions ACTUELLES dans leur nouvel ordre (commence
      toujours par 0) — `[0, 2, 1]` = l'ancien arrêt 3 passe en 2e ;
    - `segments` : pour chaque position du NOUVEL ordre, `{'minutes',
      'meters'}` du segment qui y mène (première entrée : None/None) ;
    - `total_minutes` / `total_meters` : le coût du nouvel ordre ;
    - `current_minutes` / `current_meters` : le coût de l'ordre ACTUEL sur la
      même matrice — comparable, contrairement aux durées stockées qui
      incluent des saisies manuelles ;
    - `already_optimal` : True si aucun ordre valide ne fait mieux.

    Lève `OrderingUnavailable` si la matrice est incomplète, `ValueError` si
    moins de 3 arrêts (rien à réordonner sur un aller simple).
    """
    n = len(venues)
    if n < 3:
        raise ValueError("Une tournée à moins de 3 arrêts n'a qu'un seul ordre possible.")

    matrix = _travel_matrix(venues)
    current_ids = [v.id for v in venues]
    current_minutes, current_meters = _sequence_cost(current_ids, matrix)

    best_order = list(range(n))
    best_cost = (current_minutes, current_meters)

    for tail in permutations(range(1, n)):
        order = (0, *tail)
        # Position de chaque arrêt d'origine dans ce candidat.
        rank = {original: position for position, original in enumerate(order)}
        if any(rank[load] >= rank[unload] for load, unload in precedence_pairs):
            continue
        # Deux arrêts consécutifs au même lieu n'ont pas de sens (règle du
        # serializer) — un candidat qui en produirait est écarté.
        ids = [venues[i].id for i in order]
        if any(a == b for a, b in zip(ids, ids[1:])):
            continue
        cost = _sequence_cost(ids, matrix)
        if cost < best_cost:
            best_cost = cost
            best_order = list(order)

    new_ids = [venues[i].id for i in best_order]
    segments = [None]
    for a, b in zip(new_ids, new_ids[1:]):
        segments.append(matrix[(a, b)])

    return {
        'order': best_order,
        'segments': [
            {'minutes': s['minutes'], 'meters': s['meters']} if s else {'minutes': None, 'meters': None}
            for s in segments
        ],
        'total_minutes': best_cost[0],
        'total_meters': best_cost[1],
        'current_minutes': current_minutes,
        'current_meters': current_meters,
        'already_optimal': best_order == list(range(n)),
    }

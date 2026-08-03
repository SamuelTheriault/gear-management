import { ref } from 'vue'

/**
 * État partagé des puces de filtre (2026-08-01, à la demande de Samuel :
 * « tous les boutons de filtre en haut des pages devraient avoir le même
 * comportement avec la touche ⌘ pour la sélection multiple »). Comportement
 * à la Finder : un clic simple sélectionne UNE seule valeur (remplace la
 * sélection courante), ⌘+clic (ou Ctrl+clic) ajoute ou retire une valeur de
 * la sélection sans effacer les autres.
 *
 * Remplace deux modèles bespoke qui coexistaient avant ce changement :
 *  - un `ref('Tous')` à valeur unique (Matériel, Spectacles, Cohérence,
 *    Transports, les modales d'assignation) ;
 *  - un objet de booléens indépendants par clé, activable en combinaison
 *    dès le clic simple, sans ⌘ (Dashboard — seul écran qui permettait déjà
 *    de combiner plusieurs types, mais pas de la même façon que les autres).
 *
 * Un ensemble vide = aucun filtre actif = tout est affiché. C'est l'état
 * par défaut ET ce à quoi la puce « Tous » ramène toujours, avec ou sans
 * ⌘ — combiner « Tous » et une catégorie précise n'aurait pas de sens.
 */
export function useChipFilter() {
  const selected = ref(new Set())

  function isSelected(value) {
    return selected.value.has(value)
  }

  // Utilisé pour filtrer une liste : vrai si rien n'est filtré (tout
  // s'affiche) ou si `value` fait partie de la sélection.
  function passes(value) {
    return selected.value.size === 0 || selected.value.has(value)
  }

  function selectAll() {
    selected.value = new Set()
  }

  function toggle(value, event) {
    const multi = !!(event && (event.metaKey || event.ctrlKey))
    if (!multi) {
      selected.value = new Set([value])
      return
    }
    const next = new Set(selected.value)
    if (next.has(value)) next.delete(value)
    else next.add(value)
    selected.value = next
  }

  return { selected, isSelected, passes, selectAll, toggle }
}

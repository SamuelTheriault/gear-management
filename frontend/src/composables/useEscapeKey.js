import { onMounted, onUnmounted } from 'vue'

/**
 * Ferme une modale/confirmation à la touche Échap (2026-07-31, point 6 de
 * l'audit ergonomie/navigation — voir audit_ergonomie_navigation.md). Avant
 * ça, aucune modale de l'app ne réagissait au clavier : seuls le clic sur
 * le fond, le « × » ou « Annuler » fermaient quoi que ce soit.
 *
 * N'ajoute qu'un écouteur global tant que le composant appelant est monté —
 * pas de logique d'« est-ce ouvert ? » ici, c'est à `onEscape` de vérifier
 * l'état pertinent (ex. `if (confirming.value) cancelDelete()`) avant
 * d'agir, comme pour un clic sur `.click.self`. Ce choix évite de dupliquer
 * un `watch` par appelant : certains écrans ont plusieurs états de modale
 * en jeu (ex. TransportDetailView, qui a la fois la confirmation de
 * suppression et la modale « Ajouter du matériel »).
 *
 * @param {(event: KeyboardEvent) => void} onEscape
 */
export function useEscapeKey(onEscape) {
  function handleKeydown(event) {
    if (event.key === 'Escape') onEscape(event)
  }

  onMounted(() => window.addEventListener('keydown', handleKeydown))
  onUnmounted(() => window.removeEventListener('keydown', handleKeydown))
}

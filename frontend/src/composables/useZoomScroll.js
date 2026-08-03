import { watch, nextTick } from 'vue'

/**
 * Synchronise le défilement horizontal d'un conteneur avec le niveau de
 * zoom courant — ajouté le 2026-08-02 (suite de l'ajout du zoom) à la
 * demande de Samuel : pouvoir SE DÉPLACER (défilement natif du navigateur)
 * dans une vue zoomée, pas seulement zoomer/dézoomer par paliers.
 *
 * Partagé par les 3 écrans à axe horaire (Tableau de bord, Parcours
 * Matériel, Parcours Technicien) : chacun élargit son conteneur de contenu
 * à `${zoomLevel * 100}%` de large à l'intérieur d'un conteneur
 * `overflow-x: auto` (`scrollRef`) — ce composable se contente de repositionner
 * ce conteneur au bon `scrollLeft` à chaque changement de `zoomLevel`
 * (`zoomIn`/`zoomOut`/`resetZoom`), en visant `scrollFraction` (0-1, le
 * début de la fenêtre zoomée dans la largeur totale).
 *
 * On ne réagit QU'aux changements de `zoomLevel`, jamais au défilement
 * manuel de l'utilisateur (pas de `scroll` listener ici) : une fois
 * positionné, le pan devient un défilement natif que le navigateur gère
 * seul — le relire en JS pour le remettre en état ne ferait que créer des
 * à-coups.
 *
 * `nextTick()` : `zoomLevel` change AVANT que le DOM n'ait fini d'appliquer
 * la nouvelle largeur du conteneur — sans l'attendre, `scrollWidth` lu trop
 * tôt refléterait encore l'ancien niveau de zoom.
 *
 * `scrollLeft = scrollWidth * scrollFraction` (2026-08-02, correction — pas
 * `maxScroll * scrollFraction`, bug signalé par Samuel : l'affichage
 * dérivait vers un bord au lieu de rester centré). `scrollFraction` est une
 * fraction de la largeur TOTALE du contenu (`scrollWidth`, puisque `pct()`
 * positionne déjà tout en % de la journée complète) — `maxScroll` est plus
 * petit que `scrollWidth` d'exactement `clientWidth`, donc le multiplier
 * par `scrollFraction` sous-estimait la cible dès que `scrollFraction > 0`,
 * décalant la fenêtre visible vers le début de la journée. `zoomIn`/
 * `zoomOut` centrent déjà la fenêtre active sur l'ancien centre (voir
 * `useParcours.js`/`DashboardView.vue`) et la fenêtre active fait TOUJOURS
 * exactement la largeur du conteneur visible à son propre niveau de zoom
 * (par construction de `zoomLevel`) — aligner son DÉBUT sur le bord gauche
 * du viewport suffit donc à la centrer sur l'écran. Le clamp final
 * (`Math.min(maxScroll, ...)`) protège seulement contre l'arrondi flottant :
 * mathématiquement, `scrollWidth * scrollFraction <= maxScroll` est déjà
 * garanti tant que la fenêtre active reste dans les bornes de la journée.
 */
export function useZoomScroll(scrollRef, zoomLevel, scrollFraction) {
  watch(zoomLevel, async () => {
    await nextTick()
    const el = scrollRef.value
    if (!el) return
    const maxScroll = Math.max(0, el.scrollWidth - el.clientWidth)
    const target = el.scrollWidth * scrollFraction.value
    el.scrollLeft = Math.min(maxScroll, Math.max(0, target))
  })
}

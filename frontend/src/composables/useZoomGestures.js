import { onBeforeUnmount, onMounted, watch } from 'vue'

/**
 * Pincer le trackpad pour zoomer, ⌘0 pour revenir à l'origine (2026-08-05,
 * demande de Samuel) — sur les trois écrans à axe horaire : Tableau de bord,
 * Parcours Matériel, Parcours Technicien.
 *
 * Complète les boutons +/- de `ZoomControls.vue` sans les remplacer : ceux-ci
 * restent le seul chemin visible et découvrable, le geste est un raccourci.
 *
 * ## Comment un pincement est reconnu
 *
 * Il n'existe pas d'événement « pinch » sur desktop. Les navigateurs
 * traduisent le pincement du trackpad en `wheel` avec `ctrlKey: true` — c'est
 * la convention (la même que celle du zoom natif de la page), et le seul
 * signal disponible. Conséquence assumée : Ctrl + molette d'une vraie souris
 * zoome aussi, ce qui est cohérent plutôt que gênant.
 *
 * `preventDefault()` est indispensable, sinon le navigateur zoome TOUTE la
 * page par-dessus notre propre zoom. D'où `{ passive: false }` : sans lui,
 * Chrome ignore l'appel et journalise un avertissement.
 *
 * ## Pourquoi un seuil plutôt qu'un pas par événement
 *
 * Un pincement produit une rafale d'événements (souvent 10 à 30 par geste),
 * chacun avec un `deltaY` de quelques unités. Appeler `zoomIn()` à chaque
 * fois traverserait toute la plage de zoom en un pincement. On cumule donc
 * le delta et on ne déclenche un pas qu'au franchissement du seuil, ce qui
 * donne un rythme proche des clics sur les boutons.
 *
 * ## ⌘0
 *
 * `preventDefault()` là aussi : ⌘0 est le raccourci de remise à zéro du zoom
 * du navigateur. Ignoré pendant la saisie dans un champ, où l'utilisateur
 * s'attend au comportement natif.
 *
 * @param {import('vue').Ref<HTMLElement|null>} elementRef conteneur qui capte le pincement
 * @param {{zoomIn: Function, zoomOut: Function, reset: Function}} actions
 */
const SEUIL_DELTA = 40

export function useZoomGestures(elementRef, { zoomIn, zoomOut, reset }) {
  let cumul = 0

  function onWheel(event) {
    // Sans `ctrlKey`, c'est un défilement normal : on ne s'en mêle pas, la
    // colonne des pistes doit continuer de défiler horizontalement.
    if (!event.ctrlKey) return
    event.preventDefault()

    // Changer de sens en cours de geste doit répondre tout de suite, pas
    // attendre que le cumul inverse ait repassé le seuil.
    if ((cumul > 0) !== (event.deltaY > 0)) cumul = 0
    cumul += event.deltaY
    if (Math.abs(cumul) < SEUIL_DELTA) return

    // Pincement qui s'écarte = deltaY négatif = zoom avant, comme partout.
    if (cumul < 0) zoomIn()
    else zoomOut()
    cumul = 0
  }

  function onKeydown(event) {
    if (!(event.metaKey || event.ctrlKey) || event.key !== '0') return
    const cible = event.target
    const saisie = cible && (
      cible.tagName === 'INPUT' || cible.tagName === 'TEXTAREA' || cible.isContentEditable
    )
    if (saisie) return
    event.preventDefault()
    reset()
  }

  function attacher(element) {
    if (!element) return
    element.addEventListener('wheel', onWheel, { passive: false })
  }

  function detacher(element) {
    if (!element) return
    element.removeEventListener('wheel', onWheel)
  }

  // L'élément n'existe pas tant que la timeline n'a rien à afficher (`v-if`)
  // et change quand elle réapparaît — d'où le `watch` plutôt qu'un simple
  // attachement au montage.
  watch(elementRef, (nouveau, ancien) => {
    detacher(ancien)
    attacher(nouveau)
  })

  onMounted(() => {
    attacher(elementRef.value)
    window.addEventListener('keydown', onKeydown)
  })

  onBeforeUnmount(() => {
    detacher(elementRef.value)
    window.removeEventListener('keydown', onKeydown)
  })
}

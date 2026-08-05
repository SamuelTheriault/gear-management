import { ref } from 'vue'

/**
 * Info-bulle « flottante » positionnée en JS (2026-08-03, demande de Samuel).
 *
 * Contexte : le Tableau de bord et les deux écrans Parcours utilisaient
 * jusqu'ici une info-bulle 100% CSS (`position: absolute` ancrée au bloc
 * survolé, révélée par `:hover`). Ce pattern reste piégé dès que l'ancêtre
 * scrollable (`.dash-timeline__scroll`/`.parcours-scroll`, `overflow-x:
 * auto` pour le défilement horizontal sous zoom) clippe tout ce qui dépasse
 * sa boîte — peu importe le sens d'ouverture ou la marge tampon ajoutée
 * (voir les notes du 2026-07-31 et du 2026-08-03 dans CLAUDE.md : ça ne fait
 * que repousser le problème, jamais l'éliminer). Le `z-index` n'y change
 * rien non plus : le clipping se joue avant la mise en couches.
 *
 * `position: fixed` sur l'élément rendu (voir `FloatingTooltip.vue`) échappe
 * à TOUT ancêtre avec un `overflow` non `visible`, tant qu'aucun ancêtre n'a
 * de `transform`/`filter`/`will-change` qui recréerait un contexte de
 * positionnement pour les éléments `fixed` — vérifié : aucun cas dans cette
 * app. La contrepartie : il faut calculer sa position en JS au survol
 * plutôt qu'en pur CSS, d'où ce composable.
 *
 * Usage : un seul `<FloatingTooltip :tooltip="tooltip" />` par écran (monté
 * une fois n'importe où dans le template — il est téléporté dans `<body>`,
 * sa position dans le DOM source n'a pas d'importance). `show(event,
 * content)` au `@mouseenter` de chaque élément survolable (`event` fournit
 * l'élément via `currentTarget`, pattern Vue standard), `hide()` au
 * `@mouseleave` — et, si l'écran a un geste de glisser-déposer sur les mêmes
 * blocs (Dashboard), au début d'un glisser réel.
 */
export function useFloatingTooltip() {
  // Doivent rester synchronisés avec `.floating-tooltip` dans
  // FloatingTooltip.vue (max-width/estimation de hauteur).
  const TOOLTIP_WIDTH = 240
  const ESTIMATED_HEIGHT = 130
  const MARGIN = 8
  const EDGE_PADDING = 10

  const tooltip = ref({
    visible: false,
    x: 0,
    y: 0,
    placement: 'bottom',
    title: '',
    time: '',
    lines: [],
  })

  /**
   * @param {MouseEvent} event - fournit l'élément survolé via `currentTarget`.
   * @param {{ title?: string, time?: string, lines?: string[] }} content
   */
  function show(event, content) {
    const el = event?.currentTarget
    if (!el) return
    const rect = el.getBoundingClientRect()

    // Centrée horizontalement sur l'élément, clampée aux bords de la fenêtre
    // pour ne jamais déborder hors écran sur un bloc proche d'un bord.
    let x = rect.left + rect.width / 2
    x = Math.min(
      Math.max(x, TOOLTIP_WIDTH / 2 + EDGE_PADDING),
      window.innerWidth - TOOLTIP_WIDTH / 2 - EDGE_PADDING,
    )

    // Vers le bas par défaut ; bascule vers le haut s'il n'y a pas la place
    // en dessous DANS LA FENÊTRE — plus besoin de tenir compte d'un ancêtre
    // CSS particulier, `position: fixed` se positionne par rapport au
    // viewport, pas à un conteneur qui défile.
    const spaceBelow = window.innerHeight - rect.bottom
    const placement = spaceBelow < ESTIMATED_HEIGHT + MARGIN && rect.top > ESTIMATED_HEIGHT + MARGIN
      ? 'top'
      : 'bottom'
    const y = placement === 'bottom' ? rect.bottom + MARGIN : rect.top - MARGIN

    tooltip.value = { visible: true, x, y, placement, ...content }
  }

  function hide() {
    tooltip.value = { ...tooltip.value, visible: false }
  }

  return { tooltip, show, hide }
}

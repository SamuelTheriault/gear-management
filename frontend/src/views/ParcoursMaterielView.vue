<script setup>
import { ref, computed, watch } from 'vue'
import AppShell from '../components/AppShell.vue'
import ParcoursDayPicker from '../components/ParcoursDayPicker.vue'
import ZoomControls from '../components/ZoomControls.vue'
import FloatingTooltip from '../components/FloatingTooltip.vue'
import { api } from '../api/client'
import { useActiveProject } from '../composables/useActiveProject'
import { useParcours } from '../composables/useParcours'
import { useZoomScroll } from '../composables/useZoomScroll'
import { useZoomGestures } from '../composables/useZoomGestures'
import { useFloatingTooltip } from '../composables/useFloatingTooltip'
import { VENUE_PALETTE } from '../constants/venuePalette'

/**
 * Parcours du matériel (`/parcours/materiel`, sous-menu du Tableau de bord
 * depuis le 2026-07-30) — ajouté le 2026-07-30 à la
 * demande de Samuel : voir OÙ SE TROUVE chaque matériel sur toute la durée de
 * la production, et pas seulement ses engagements.
 *
 * Les séjours viennent de `GET /api/projects/{id}/material-journey/`, qui
 * réutilise le grand livre de positions de `transport_coherence.py` — même
 * source de vérité que la cohérence des emplacements et que la disponibilité
 * au départ d'un transport. Les trois écrans ne peuvent donc pas se
 * contredire.
 *
 * Affichage jour par jour (2026-07-31, demande de Samuel : « comme le
 * dashboard principal, avec des boutons de filtre pour sélectionner la
 * journée ») : une seule journée à la fois (axe 0h→24h), choisie via des
 * puces + flèches précédent/suivant (`days`/`selectedDayKey`/`selectDay`/
 * `stepDay` dans useParcours). Chaque séjour/marque/transport est tronqué aux
 * bornes de la journée choisie (`overlapsDay`) — un séjour à cheval sur deux
 * jours n'apparaît que pour sa portion dans le jour affiché.
 *
 * Lecture d'une ligne : un segment coloré par lieu de séjour, et un liseré
 * lavande en bas quand le matériel est requis par un spectacle à ce
 * moment-là — pour repérer d'un coup d'œil « il est bien là où il sert ».
 *
 * Filtre par catégorie (2026-07-30, suite, demande de Samuel : « on va avoir
 * beaucoup de matériel ») : les mêmes puces que l'inventaire, appliquées au
 * panneau de sélection. « Tout » ne coche alors que ce qui est visible — voir
 * `selectAll` dans useParcours. Comme dans l'inventaire, seules les catégories
 * réellement présentes deviennent des puces : une puce qui ne mène nulle part
 * n'aide personne.
 *
 * Sélection multiple des puces (2026-07-30, suite) : ⌘ + clic (ou Ctrl sur
 * PC) ajoute/retire une catégorie de la sélection ; un clic simple remplace
 * la sélection par cette seule catégorie. Aucune catégorie sélectionnée
 * équivaut à « Tous », ce qui évite un état vide où plus rien ne s'afficherait.
 *
 * Arborescence des kits (2026-07-30, suite) : le panneau de sélection affiche
 * les composants en retrait sous leur kit, comme l'inventaire et les modales
 * d'assignation. Un composant dont le kit est masqué par le filtre de
 * catégorie reste affiché, mais au premier niveau — mieux vaut orphelin que
 * perdu.
 *
 * Sélection en cascade : cocher un kit coche ses composants, décocher le kit
 * les décoche — même comportement que les modales d'assignation, à la demande
 * de Samuel. La cascade porte sur TOUS les composants du kit, y compris ceux
 * que le filtre de catégorie masque : ils appartiennent au kit, et leur ligne
 * apparaît alors dans la timeline même si la case correspondante n'est pas
 * visible dans le panneau. Chaque composant reste décochable individuellement.
 *
 * Bifurcations/fusions (2026-08-01, demande de Samuel) : `get_material_journey`
 * renvoie maintenant des séjours répartis sur des `lane` (lignes), avec
 * `parent_lane`/`merge_from_lane` quand un matériel à quantité multiple se
 * scinde entre plusieurs lieux à la fois, ou que deux lignes se rejoignent —
 * voir `transport_coherence.py`. Une ligne (matériel) dont TOUTES les
 * positions du jour affiché tiennent sur une seule `lane` garde le rendu
 * d'avant (une seule barre, hauteur de piste inchangée) — c'est le cas de la
 * grande majorité du matériel. Dès qu'au moins deux lanes sont actives le
 * même jour, la piste s'agrandit et empile une sous-ligne par lane
 * (`laneIndex`/`laneCount`, calculés par jour affiché — pas sur tout le
 * parcours, pour ne pas gaspiller de hauteur les jours sans division).
 *
 * Transports en transit (2026-08-01, suite, demande de Samuel) : un
 * déplacement confirmé n'est plus un simple liseré fin superposé — il occupe
 * sa vraie durée prévue (`t.start`→`t.end`) DANS la ligne (lane) où se
 * trouvait le matériel juste avant, comme un séjour à part entière mais
 * hachuré (`.parcours-transit`). Le séjour qui le précède sur cette même
 * lane est visuellement raccourci pour s'arrêter au départ plutôt qu'à
 * l'arrivée (`departureTrim`) — sinon les deux se chevaucheraient sur la
 * même fenêtre. Une bifurcation/fusion (lane de destination différente de la
 * lane d'origine) part maintenant du bloc de transit lui-même : un
 * connecteur en équerre (`row.connectors`, deux segments — un tronc vertical
 * puis une branche horizontale d'une largeur FIXE égale à la hauteur d'une
 * lane, `LANE_HEIGHT`) descend ou monte jusqu'à la lane de destination, même
 * langage visuel que le raccordement des kits dans l'inventaire
 * (`.kit-child::after`) plutôt qu'une courbe SVG. Un transport qui ne change
 * pas de lane (relocalisation simple, cas courant) n'a pas de connecteur : le
 * bloc de transit s'insère juste avant la suite du séjour, sur la même ligne.
 * Limite connue, inchangée : `.parcours-mark` (assignation) continue de
 * couvrir toute la hauteur de la piste, pas une lane précise.
 *
 * Corrigé le 2026-08-01 (suite) : le séjour/bloc qui suit un transport
 * pouvait chevaucher visuellement sa durée — `segmentStyle` (useParcours)
 * impose une largeur plancher (pour qu'un marqueur ponctuel reste visible),
 * qui faisait déborder un segment court sur son voisin alors que séjours et
 * transit doivent se toucher pile bout à bout. `rangeStyle` (local, sans
 * plancher) est utilisée à la place pour les séjours et les blocs de
 * transit — seuls `row.marks` gardent `segmentStyle`. Couleur du bloc de
 * transit rendue CONSTANTE (bordure pointillée) au lieu d'un motif hachuré
 * coloré par lieu — même code couleur que les transports confirmés sur le
 * Dashboard. Cette constante était `var(--accent)`, passée à `var(--transport)`
 * (fuchsia) le 2026-08-02 — voir la note dédiée dans CLAUDE.md.
 *
 * Zoom (2026-08-02, demande de Samuel) : `ZoomControls.vue` + l'état
 * correspondant (`isZoomed`/`canZoomIn`/`canZoomOut`/`zoomIn`/`zoomOut`/
 * `resetZoom`) vivent dans `useParcours.js`, partagé avec
 * `ParcoursTechniciensView` — cet écran affiche juste les boutons.
 * « Réinitialiser » revient à la journée complète (0h-24h) — la sélection de
 * jour reste le seul niveau « zoom arrière » au-delà de ça.
 *
 * Défilement horizontal sous zoom (2026-08-02, suite, demande de Samuel :
 * « se déplacer dans la vue ») : révision du mécanisme de zoom ci-dessus —
 * `pct`/`segmentStyle`/`overlapsDay`/`hourMarks` sont maintenant TOUJOURS
 * relatifs à la journée entière (plus à une fenêtre zoomée recalculée), et
 * c'est `.parcours-scroll__content` qui s'élargit à `zoomLevel * 100 %` à
 * l'intérieur de `.parcours-scroll` (`overflow-x: auto`) — se déplacer dans
 * une vue zoomée devient donc un défilement NATIF du navigateur (molette,
 * trackpad, barre de défilement), pas un recalcul de fenêtre. `useZoomScroll`
 * repositionne ce défilement au bon endroit à chaque zoomIn/zoomOut/
 * resetZoom (`scrollFraction`), sans jamais lire le défilement manuel en
 * retour. L'étiquette de chaque ligne (`.parcours-row__label`) est sortie
 * dans sa propre colonne fixe (`.parcours-labels`), à côté — pas dans — la
 * zone défilante, pour qu'elle ne bouge jamais pendant qu'on se déplace.
 *
 * Sous-items en retrait dans la timeline (2026-08-02, suite, demande de
 * Samuel) : les LIGNES elles-mêmes (pas seulement le panneau de sélection,
 * qui avait déjà ce traitement) affichent maintenant un composant de kit en
 * retrait sous son kit, même trait de raccordement que
 * `.parcours-option--nested`. `orderedRows` (nouveau) rejoue le même
 * regroupement que `visibleOptions` — chaque composant suit immédiatement
 * son kit dans l'ordre d'affichage — avant que `decorated` construise les
 * séjours/pistes ; `nested` n'est vrai que si le kit parent est LUI AUSSI
 * dans la sélection courante (orphelin affiché à plat sinon, même principe
 * que le panneau). Uniquement la colonne d'étiquettes est indentée — les
 * pistes/segments de la timeline elle-même n'ont pas bougé.
 *
 * Info-bulle flottante (2026-08-03, demande de Samuel) : les info-bulles de
 * séjour/transit/marqueur ne sont plus des `<div>` imbriquées révélées en
 * CSS-only par `:hover` — `.parcours-scroll` (`overflow-x: auto`, pour le
 * défilement sous zoom) les clippait dès qu'elles dépassaient sa boîte,
 * peu importe le sens d'ouverture (même bug que sur le Dashboard, voir
 * `useFloatingTooltip.js`). `showTooltip`/`hideTooltip` au survol de chaque
 * élément, un seul `<FloatingTooltip>` positionné en JS
 * (`position: fixed`, échappe à tout ancêtre) pour tout l'écran. Les champs
 * `tooltipTitle`/`tooltipTime`/`tooltipLines` déjà calculés dans `decorated`
 * n'ont pas changé — seule leur consommation dans le template change.
 */

const { activeProjectId } = useActiveProject()

const {
  options, selectedIds, rows, window: fenetre, loading, loadError,
  days, selectedDayKey, selectDay, stepDay, hourMarks, overlapsDay,
  selectAll, selectNone, segmentStyle, pct,
  isZoomed, canZoomIn, canZoomOut, zoomIn, zoomOut, resetZoom,
  zoomLevel, scrollFraction,
} = useParcours({
  endpoint: 'material-journey',
  itemsKey: 'materials',
  listEndpoint: '/materials/',
  listParam: 'materials',
})

// Défilement horizontal natif sous zoom (2026-08-02, suite — voir la note de
// tête) : `scrollRef` pointe le conteneur `overflow-x: auto` qui entoure
// l'axe et toutes les pistes ; `useZoomScroll` le repositionne à chaque
// changement de niveau de zoom pour viser la fenêtre visée, puis laisse le
// navigateur gérer seul le défilement manuel.
const scrollRef = ref(null)
useZoomScroll(scrollRef, zoomLevel, scrollFraction)
// Pincer le trackpad pour zoomer, ⌘0 pour revenir à l'origine (2026-08-05) —
// raccourcis, les boutons +/- restent le chemin visible.
useZoomGestures(scrollRef, { zoomIn, zoomOut, reset: resetZoom })

// Info-bulle flottante (2026-08-03) — voir la note de tête et
// `useFloatingTooltip.js`.
const { tooltip, show: showTooltip, hide: hideTooltip } = useFloatingTooltip()

// --- Filtre par catégorie ---

const categories = ref([])
// Liste de clés sélectionnées (id de catégorie, ou 'none' pour le matériel
// non classé). Vide = aucune restriction, donc « Tous ».
const selectedCategories = ref([])

async function loadCategories() {
  if (!activeProjectId.value) return
  const data = await api.get('/material-categories/', { project: activeProjectId.value })
  categories.value = Array.isArray(data) ? data : (data.results ?? [])
}

watch(activeProjectId, loadCategories, { immediate: true })

/**
 * Clic sur une puce de catégorie.
 *
 * ⌘ (macOS) ou Ctrl (PC) enfoncé : bascule cette catégorie dans la sélection,
 * pour en cumuler plusieurs. Sinon : la sélection est remplacée par cette
 * seule catégorie — le geste courant reste un clic simple.
 *
 * Décocher la dernière catégorie retombe sur « Tous » plutôt que sur une
 * liste vide : un panneau sans aucune option n'apprend rien.
 */
function pickCategory(key, event) {
  const cumul = event?.metaKey || event?.ctrlKey
  if (key === 'all') {
    selectedCategories.value = []
    return
  }
  if (!cumul) {
    selectedCategories.value = [key]
    return
  }
  selectedCategories.value = selectedCategories.value.includes(key)
    ? selectedCategories.value.filter((other) => other !== key)
    : [...selectedCategories.value, key]
}

const categoryChips = computed(() => {
  // Seules les catégories présentes dans le matériel du projet, et la puce
  // « Sans catégorie » uniquement s'il existe vraiment du matériel non classé.
  const present = new Set(options.value.map((m) => m.category).filter((id) => id != null))
  const chips = [
    {
      key: 'all',
      label: 'Tous',
      active: selectedCategories.value.length === 0,
    },
    ...categories.value
      .filter((c) => present.has(c.id))
      .map((c) => ({
        key: c.id,
        label: c.name,
        color: c.color,
        active: selectedCategories.value.includes(c.id),
      })),
  ]
  if (options.value.some((m) => m.category == null)) {
    chips.push({
      key: 'none',
      label: 'Sans catégorie',
      active: selectedCategories.value.includes('none'),
    })
  }
  return chips
})

const matchingOptions = computed(() =>
  options.value.filter((m) => {
    if (selectedCategories.value.length === 0) return true
    const cle = m.category == null ? 'none' : m.category
    return selectedCategories.value.includes(cle)
  }),
)

/**
 * Ordonne la liste comme l'inventaire : chaque composant suit immédiatement
 * son kit. `nested` marque ceux qu'on affiche en retrait — c'est-à-dire ceux
 * dont le parent est lui aussi visible dans la liste courante.
 */
const visibleOptions = computed(() => {
  const liste = matchingOptions.value
  const visibles = new Set(liste.map((m) => m.id))

  const enfants = new Map()
  liste.forEach((m) => {
    if (m.parent_material == null || !visibles.has(m.parent_material)) return
    if (!enfants.has(m.parent_material)) enfants.set(m.parent_material, [])
    enfants.get(m.parent_material).push(m)
  })

  const ordonne = []
  liste.forEach((m) => {
    if (m.parent_material != null && visibles.has(m.parent_material)) return
    ordonne.push({ ...m, nested: false, childCount: (enfants.get(m.id) ?? []).length })
    ;(enfants.get(m.id) ?? []).forEach((child) => {
      ordonne.push({ ...child, nested: true, childCount: 0 })
    })
  })
  return ordonne
})

const childrenByParent = computed(() => {
  const map = new Map()
  options.value.forEach((m) => {
    if (m.parent_material == null) return
    if (!map.has(m.parent_material)) map.set(m.parent_material, [])
    map.get(m.parent_material).push(m)
  })
  return map
})

/**
 * Coche/décoche une ligne, en entraînant les composants d'un kit.
 *
 * On écrit `selectedIds` en une seule fois plutôt que d'appeler le `toggle`
 * du composable pour chaque id : celui-ci est observé et déclencherait un
 * appel API par composant.
 */
function toggleOption(option) {
  const dejaCoche = selectedIds.value.includes(option.id)
  const enfants = childrenByParent.value.get(option.id) ?? []
  const cibles = [option.id, ...enfants.map((c) => c.id)]

  selectedIds.value = dejaCoche
    ? selectedIds.value.filter((id) => !cibles.includes(id))
    : [...new Set([...selectedIds.value, ...cibles])]
}

// Une couleur stable par lieu, pour qu'un même lieu garde la même teinte d'une
// ligne à l'autre. L'entrepôt (le « bercail ») est volontairement neutre : ce
// qui doit sauter aux yeux, c'est quand le matériel en est SORTI.
//
// Un lieu peut fixer sa propre couleur (`Venue.color`, 2026-08-02, demande de
// Samuel — voir LieuDetailView.vue) : si renseignée, elle prime sur le cycle
// automatique, y compris sur le traitement neutre d'un entrepôt (Samuel fixe
// alors sciemment une teinte pour CE lieu). `venueColorOverrides` vient d'un
// chargement séparé de `/api/venues/` — le material-journey ne renvoie que
// `venue_id`/`venue_name`/`is_storage` par séjour, pas la couleur du lieu, et
// ça n'a pas paru justifié d'étoffer ce contrat juste pour un détail
// d'affichage. La génération automatique elle-même (cycle `VENUE_PALETTE`)
// reste INCHANGÉE quand aucun lieu n'a de couleur fixée.
const venues = ref([])

async function loadVenues() {
  if (!activeProjectId.value) return
  const data = await api.get('/venues/', { project: activeProjectId.value })
  venues.value = Array.isArray(data) ? data : (data.results ?? [])
}

watch(activeProjectId, loadVenues, { immediate: true })

const venueColorOverrides = computed(() => {
  const map = new Map()
  venues.value.forEach((v) => {
    if (v.color) map.set(v.id, v.color)
  })
  return map
})

const venueColors = computed(() => {
  const map = new Map()
  let i = 0
  rows.value.forEach((row) => {
    row.stays.forEach((stay) => {
      if (map.has(stay.venue_id)) return
      const override = venueColorOverrides.value.get(stay.venue_id)
      if (override) {
        map.set(stay.venue_id, override)
      } else if (stay.is_storage) {
        map.set(stay.venue_id, 'rgba(var(--fg-rgb),.12)')
      } else {
        map.set(stay.venue_id, VENUE_PALETTE[i++ % VENUE_PALETTE.length])
      }
    })
  })
  return map
})

const legend = computed(() => {
  const seen = new Map()
  rows.value.forEach((row) => {
    row.stays.forEach((stay) => {
      if (!seen.has(stay.venue_id)) {
        seen.set(stay.venue_id, { name: stay.venue_name, color: venueColors.value.get(stay.venue_id) })
      }
    })
  })
  return [...seen.values()]
})

const dateFmt = new Intl.DateTimeFormat('fr-CA', {
  day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
})

// Hauteur d'une lane et espace entre deux lanes, en piste multi-lignes
// (voir la note de tête sur les bifurcations/fusions) — en dessous de 2
// lanes actives le même jour, ces constantes ne servent pas : le rendu à
// une seule barre garde son style CSS d'origine (top/bottom 8px).
const LANE_HEIGHT = 22
const LANE_GAP = 6

const rowTopPx = (li) => 8 + li * (LANE_HEIGHT + LANE_GAP)
const rowCenterPx = (li) => rowTopPx(li) + LANE_HEIGHT / 2

/** Comme `segmentStyle` (useParcours), mais SANS largeur minimale forcée.
 * Séjours et blocs de transit doivent se toucher exactement bout à bout — un
 * séjour raccourci par `departureTrim` s'arrête pile où le transit suivant
 * commence, et le transit s'arrête pile où le séjour suivant reprend. La
 * largeur plancher de `segmentStyle` (pensée pour qu'un marqueur ponctuel
 * reste visible) ferait déborder un segment court sur son voisin — c'est le
 * chevauchement signalé par Samuel (2026-08-01). Les marqueurs
 * d'assignation (`row.marks`) n'ont pas cette contrainte de contiguïté et
 * gardent `segmentStyle`. */
function rangeStyle(startIso, endIso) {
  const left = pct(startIso)
  const width = Math.max(pct(endIso) - left, 0)
  return { left: `${left}%`, width: `${width}%` }
}

/** Connecteur en équerre entre la lane `fromLi` (le bloc de transit) et la
 * lane `toLi` (la lane de destination) à la position horizontale `xPercent`
 * — même langage visuel que le raccordement des kits (tronc + branche),
 * plutôt qu'une courbe : la branche horizontale a une largeur FIXE égale à
 * `LANE_HEIGHT`, demandée par Samuel pour qu'elle reste bien proportionnée
 * au lieu d'être une longue diagonale. */
function elbowConnector(xPercent, fromLi, toLi) {
  const down = toLi > fromLi
  const top = down ? rowTopPx(fromLi) + LANE_HEIGHT : rowCenterPx(toLi)
  const bottom = down ? rowCenterPx(toLi) : rowTopPx(fromLi)
  return {
    trunk: { left: `${xPercent}%`, top: `${top}px`, height: `${Math.max(bottom - top, 1)}px` },
    branch: { left: `${xPercent}%`, top: `${rowCenterPx(toLi)}px` },
  }
}

/**
 * Regroupe les lignes de la timeline comme le panneau de sélection
 * (`visibleOptions`) : chaque composant suit immédiatement son kit, et
 * `nested` ne marque que ceux dont le kit parent est LUI AUSSI dans la
 * sélection courante (orphelin affiché à plat sinon, même principe que
 * `visibleOptions`).
 */
const orderedRows = computed(() => {
  const rowIds = new Set(rows.value.map((r) => r.id))
  const parentOf = new Map(options.value.map((m) => [m.id, m.parent_material]))
  const byId = new Map(rows.value.map((r) => [r.id, r]))

  const enfants = new Map()
  rows.value.forEach((r) => {
    const p = parentOf.get(r.id)
    if (p == null || !rowIds.has(p)) return
    if (!enfants.has(p)) enfants.set(p, [])
    enfants.get(p).push(r.id)
  })

  const ordonne = []
  rows.value.forEach((r) => {
    const p = parentOf.get(r.id)
    if (p != null && rowIds.has(p)) return
    ordonne.push({ ...r, nested: false })
    ;(enfants.get(r.id) ?? []).forEach((cid) => ordonne.push({ ...byId.get(cid), nested: true }))
  })
  return ordonne
})

const decorated = computed(() =>
  orderedRows.value.map((row) => {
    const dayStays = row.stays.filter((s) => overlapsDay(s.start, s.end))
    const dayTransports = (row.transports ?? []).filter((t) => overlapsDay(t.start, t.end))

    // Une lane par position simultanée ACTIVE CE JOUR-LÀ (pas sur tout le
    // parcours) : un matériel qui se scinde un autre jour ne doit pas
    // agrandir la piste ici pour rien.
    const laneIds = [...new Set(dayStays.map((s) => s.lane))].sort((a, b) => a - b)
    const laneIndex = new Map(laneIds.map((l, i) => [l, i]))
    const laneCount = laneIds.length
    const multiLane = laneCount > 1

    const laneBox = (li) => (multiLane
      ? { top: `${rowTopPx(li)}px`, bottom: 'auto', height: `${LANE_HEIGHT}px` }
      : {})

    // Un transport RACCOURCIT visuellement le séjour qui le précède sur sa
    // lane d'origine — il occupe désormais lui-même la fenêtre
    // [départ, arrivée], le séjour s'arrête donc au départ plutôt qu'à
    // l'arrivée (voir la note de tête). Indexé par lieu + instant d'arrivée,
    // qui identifie de façon unique le séjour qu'un transport referme (même
    // correspondance que le backend utilise pour clore une lane).
    const departureTrim = new Map()
    dayTransports.forEach((t) => {
      departureTrim.set(`${t.origin_venue_id}|${new Date(t.end).getTime()}`, t.start)
    })

    const stays = dayStays.map((stay) => {
      const li = laneIndex.get(stay.lane)
      const trimKey = `${stay.venue_id}|${new Date(stay.end).getTime()}`
      const visualEnd = departureTrim.get(trimKey) ?? stay.end
      return {
        ...stay,
        style: {
          ...rangeStyle(stay.start, visualEnd),
          ...laneBox(li),
          background: venueColors.value.get(stay.venue_id),
        },
        // Quantité écrite directement sur la branche dès qu'il y a plus
        // d'une lane à distinguer — inutile (et redondant avec l'info-bulle)
        // sur le cas courant à une seule ligne. Suffixe « x » (2026-08-02,
        // demande de Samuel) pour qu'un chiffre nu ne soit pas confondu avec
        // autre chose (heure, code de lieu…) — même suffixe sur le bloc de
        // transit juste en dessous et sur la Répartition de la fiche
        // matériel (MaterielDetailView.vue).
        label: multiLane ? `${stay.venue_name} · ${stay.quantity}x` : stay.venue_name,
        tooltipTitle: stay.venue_name,
        tooltipTime: `${dateFmt.format(new Date(stay.start))} – ${dateFmt.format(new Date(stay.end))}`,
        tooltipLines: [
          `${stay.quantity} unité(s)`,
          stay.is_storage ? 'Lieu d\'entreposage' : 'Lieu de spectacle',
        ],
      }
    })

    // Un transport se raccorde à sa lane d'origine (celle qui se termine
    // pile à son arrivée) et à sa lane de destination (celle qui commence
    // pile à ce même instant) — même correspondance exacte que le backend
    // utilise pour fermer/ouvrir une lane, voir `get_material_journey`.
    const findStayByEdge = (field, venueId, iso) => {
      const t = new Date(iso).getTime()
      return dayStays.find((s) => s.venue_id === venueId && new Date(s[field]).getTime() === t)
    }

    const connectors = []
    const transports = dayTransports.map((t) => {
      const originStay = findStayByEdge('end', t.origin_venue_id, t.end)
      const destStay = findStayByEdge('start', t.destination_venue_id, t.end)
      const lane = originStay?.lane ?? null
      const destLane = destStay?.lane ?? null
      const li = lane != null ? laneIndex.get(lane) : null

      if (multiLane && li != null && destLane != null && destLane !== lane && laneIndex.has(destLane)) {
        const { trunk, branch } = elbowConnector(pct(t.end), li, laneIndex.get(destLane))
        connectors.push({
          key: `link-${lane}-${destLane}-${t.end}`,
          trunk,
          branch,
          color: venueColors.value.get(t.destination_venue_id),
        })
      }

      return {
        ...t,
        style: { ...rangeStyle(t.start, t.end), ...(li != null ? laneBox(li) : {}) },
        label: `→ ${t.destination_venue_name} · ${t.quantity}x`,
        tooltipTitle: `Déplacement — ${t.show_title}`,
        tooltipTime: `${dateFmt.format(new Date(t.start))} – ${dateFmt.format(new Date(t.end))}`,
        tooltipLines: [
          `${t.origin_venue_name} → ${t.destination_venue_name}`,
          `${t.quantity} unité(s)`,
        ],
      }
    })

    return {
      ...row,
      stays,
      transports,
      connectors,
      trackStyle: multiLane
        ? { minHeight: `${8 + laneCount * LANE_HEIGHT + (laneCount - 1) * LANE_GAP + 8}px` }
        : {},
      marks: row.assignments.filter((a) => overlapsDay(a.start, a.end)).map((a) => ({
        ...a,
        style: segmentStyle(a.start, a.end),
        tooltipTitle: a.show_title,
        tooltipTime: `${dateFmt.format(new Date(a.start))} – ${dateFmt.format(new Date(a.end))}`,
        tooltipLines: [
          'Requis par un spectacle',
          `${a.venue_name} · ${a.quantity} unité(s)`,
        ],
      })),
    }
  }),
)
</script>

<template>
  <AppShell>
    <div class="page">
      <div class="page-header">
        <h1 class="page-title">Parcours Matériel</h1>
        <div class="page-count">{{ selectedIds.length }} item(s) affiché(s)</div>
      </div>

      <div v-if="loadError" class="hint hint--error">
        Impossible de charger le parcours. Es-tu connecté (session Django) ?
      </div>
      <div v-else-if="!fenetre && !loading" class="hint">
        Ce projet n'a ni dates ni événement : il n'y a pas encore de période à afficher.
        Tu peux saisir les dates du projet dans les Réglages.
      </div>

      <div class="parcours">
        <div class="parcours-picker">
          <div class="parcours-picker__head">
            <div class="parcours-picker__title">Matériel</div>
            <button type="button" class="parcours-picker__link" @click="selectAll(visibleOptions)">
              Tout
            </button>
            <button type="button" class="parcours-picker__link" @click="selectNone">Aucun</button>
          </div>
          <div class="picker-filters">
            <span
              v-for="c in categoryChips"
              :key="c.key"
              class="picker-chip"
              :class="{ 'picker-chip--active': c.active }"
              @click="pickCategory(c.key, $event)"
            >
              <span v-if="c.color" class="picker-chip__dot" :style="{ background: c.color }" />
              {{ c.label }}
            </span>
          </div>
          <div class="picker-hint">⌘ + clic pour cumuler plusieurs catégories</div>
          <div v-if="visibleOptions.length === 0" class="picker-empty">
            Aucun matériel dans cette sélection.
          </div>
          <label
            v-for="o in visibleOptions"
            :key="o.id"
            class="parcours-option"
            :class="{ 'parcours-option--nested': o.nested }"
            @click.prevent="toggleOption(o)"
          >
            <span
              class="parcours-option__check"
              :class="{ 'parcours-option__check--on': selectedIds.includes(o.id) }"
            >{{ selectedIds.includes(o.id) ? '✓' : '' }}</span>
            <span class="parcours-option__name">{{ o.name }}</span>
            <span v-if="o.childCount > 0" class="parcours-option__badge">{{ o.childCount }}</span>
          </label>
        </div>

        <div class="parcours-board">
          <div v-if="loading" class="parcours-empty">Chargement…</div>
          <div v-else-if="decorated.length === 0" class="parcours-empty">
            Coche du matériel à gauche pour voir son parcours.
          </div>

          <template v-else>
            <div class="parcours-toolbar">
              <ParcoursDayPicker
                :days="days"
                :selected-day-key="selectedDayKey"
                @select="selectDay"
                @step="stepDay"
              />
              <ZoomControls
                :is-zoomed="isZoomed"
                :can-zoom-in="canZoomIn"
                :can-zoom-out="canZoomOut"
                @zoom-in="zoomIn"
                @zoom-out="zoomOut"
                @reset="resetZoom"
              />
            </div>

            <div class="parcours-timeline">
              <div class="parcours-labels">
                <div class="parcours-labels__spacer" />
                <div
                  v-for="row in decorated"
                  :key="`label-${row.id}`"
                  class="parcours-row__label"
                  :class="{ 'parcours-row__label--nested': row.nested }"
                  :style="row.trackStyle"
                >
                  <div class="parcours-row__name">{{ row.name }}</div>
                  <div class="parcours-row__meta">
                    {{ row.category_name ?? 'Sans catégorie' }} · origine {{ row.home_venue_name }}
                  </div>
                </div>
              </div>

              <div ref="scrollRef" class="parcours-scroll">
                <div class="parcours-scroll__content" :style="{ width: `${zoomLevel * 100}%` }">
                  <div class="parcours-axis">
                    <div v-for="mark in hourMarks" :key="mark.key" class="parcours-axis__tick" :style="{ left: mark.left }">
                      {{ mark.label }}
                    </div>
                  </div>

                  <div v-for="row in decorated" :key="`track-${row.id}`" class="parcours-track" :style="row.trackStyle">
                    <div
                      v-for="mark in hourMarks"
                      :key="`grid-${mark.key}`"
                      class="parcours-gridline"
                      :style="{ left: mark.left }"
                    />
                    <template v-for="c in row.connectors" :key="c.key">
                      <div class="parcours-lane-trunk" :style="{ ...c.trunk, background: c.color }" />
                      <div class="parcours-lane-branch" :style="{ ...c.branch, background: c.color }" />
                    </template>
                    <div
                      v-for="(stay, i) in row.stays"
                      :key="`s${i}`"
                      class="parcours-seg"
                      :style="stay.style"
                      @mouseenter="showTooltip($event, { title: stay.tooltipTitle, time: stay.tooltipTime, lines: stay.tooltipLines })"
                      @mouseleave="hideTooltip"
                    >
                      <span class="parcours-seg__label">{{ stay.label }}</span>
                    </div>
                    <div
                      v-for="(t, i) in row.transports"
                      :key="`t${i}`"
                      class="parcours-transit"
                      :style="t.style"
                      @mouseenter="showTooltip($event, { title: t.tooltipTitle, time: t.tooltipTime, lines: t.tooltipLines })"
                      @mouseleave="hideTooltip"
                    >
                      <span class="parcours-seg__label">{{ t.label }}</span>
                    </div>
                    <div
                      v-for="(mark, i) in row.marks"
                      :key="`m${i}`"
                      class="parcours-mark"
                      :style="mark.style"
                      @mouseenter="showTooltip($event, { title: mark.tooltipTitle, time: mark.tooltipTime, lines: mark.tooltipLines })"
                      @mouseleave="hideTooltip"
                    >
                      <span class="parcours-mark__label">{{ mark.show_title }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div class="legend">
              <span v-for="l in legend" :key="l.name" class="legend__item">
                <span class="legend__swatch" :style="{ background: l.color }" />{{ l.name }}
              </span>
              <span class="legend__item">
                <span class="legend__swatch legend__swatch--mark" />Requis par un spectacle
              </span>
              <span class="legend__item">
                <span class="legend__swatch legend__swatch--transport" />Déplacement confirmé
              </span>
            </div>
          </template>
        </div>
      </div>
    </div>
    <FloatingTooltip :tooltip="tooltip" />
  </AppShell>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.page-count {
  font: 500 12px system-ui;
  color: rgba(var(--fg-rgb), 0.48);
}

.hint {
  font: 500 13px system-ui;
  color: rgba(var(--fg-rgb), 0.58);
}

.hint--error {
  color: oklch(0.78 0.16 35);
}

.picker-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(var(--fg-rgb), 0.06);
}

.picker-chip {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 4px 8px;
  border-radius: 0 6px 0 6px;
  background: rgba(var(--fg-rgb), 0.06);
  color: rgba(var(--fg-rgb), 0.63);
  font: 500 10.5px system-ui;
  cursor: pointer;
  white-space: nowrap;
}

.picker-chip--active {
  background: rgba(var(--accent-rgb), 0.2);
  color: var(--accent);
  font-weight: 600;
}

.picker-chip__dot {
  width: 7px;
  height: 7px;
  border-radius: 2px;
  flex: none;
}

/* Composant affiché en retrait sous son kit, avec le trait de raccordement —
   même lecture que l'inventaire et les modales d'assignation. */
.parcours-option--nested {
  position: relative;
  margin-left: 18px;
  border-left: 2px solid rgba(var(--accent-rgb), 0.25);
  padding-left: 10px;
}

.parcours-option--nested::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  width: 8px;
  height: 2px;
  background: rgba(var(--accent-rgb), 0.25);
}

/* Nombre de composants d'un kit, pour comprendre le regroupement sans avoir
   à compter les lignes en retrait. */
.parcours-option__badge {
  flex: none;
  min-width: 16px;
  padding: 1px 5px;
  border-radius: 0 5px 0 5px;
  background: rgba(var(--fg-rgb), 0.08);
  color: rgba(var(--fg-rgb), 0.48);
  font: 600 9.5px var(--font-mono);
  text-align: center;
}

.picker-hint {
  font: 400 10px system-ui;
  color: rgba(var(--fg-rgb), 0.25);
  padding: 2px 0 4px;
}

.picker-empty {
  padding: 10px 4px;
  font: 400 11.5px system-ui;
  color: rgba(var(--fg-rgb), 0.38);
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  padding-top: 8px;
  border-top: 1px solid rgba(var(--fg-rgb), 0.06);
}

.legend__item {
  display: flex;
  align-items: center;
  gap: 6px;
  font: 400 11px system-ui;
  color: rgba(var(--fg-rgb), 0.53);
}

.legend__swatch {
  width: 12px;
  height: 10px;
  border-radius: 0 3px 0 3px;
}

/* Les deux puces ci-dessous gardaient la hauteur de 3px des anciens liserés
   (2026-08-02, signalé par Samuel) : elles ne représentaient plus ce qui est
   réellement dessiné, et leur alignement sautait dans la légende. Même
   gabarit que `.legend__swatch` maintenant, et mêmes couleurs que les blocs
   correspondants — bleu pour le marqueur d'assignation (`.parcours-mark`),
   `var(--transport)` (fuchsia) + pointillé pour le bloc de transit
   (`.parcours-transit`). */
.legend__swatch--mark {
  background: oklch(0.72 0.15 250);
}

.legend__swatch--transport {
  background: var(--transport);
  border: 1px dashed rgba(0, 0, 0, 0.35);
}

/* Composant de kit en retrait dans la colonne d'étiquettes (2026-08-02,
   demande de Samuel) — même trait de raccordement que
   `.parcours-option--nested` dans le panneau de sélection, valeurs juste
   réduites pour laisser assez de place au nom dans les 150px de
   `.parcours-labels`. */
.parcours-row__label--nested {
  position: relative;
  margin-left: 14px;
  border-left: 2px solid rgba(var(--accent-rgb), 0.25);
  padding-left: 8px;
}

.parcours-row__label--nested::before {
  content: '';
  position: absolute;
  left: -2px;
  top: 50%;
  width: 8px;
  height: 2px;
  background: rgba(var(--accent-rgb), 0.25);
}
</style>

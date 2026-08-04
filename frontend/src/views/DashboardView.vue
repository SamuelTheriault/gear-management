<script setup>
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppShell from '../components/AppShell.vue'
import ZoomControls from '../components/ZoomControls.vue'
import { api } from '../api/client'
import { useActiveProject } from '../composables/useActiveProject'
import { useChipFilter } from '../composables/useChipFilter'
import { useZoomScroll } from '../composables/useZoomScroll'
import { useEventDisplay } from '../composables/useEventDisplay'

const router = useRouter()

/**
 * Tableau de bord — port de Dashboard.dc.html, branché sur l'API réelle
 * (2026-07-30).
 *
 * Données : `GET /api/shows/?project=`, `GET /api/materials/?project=` (pour
 * le total d'items), `GET /api/projects/{id}/conflicts/` (le même rapport
 * project-wide dédupliqué que ConflitsView.vue), `GET
 * /api/transports/?project=` et `GET /api/projects/{id}/window/`.
 *
 * ## Bornage au projet (2026-08-02, demande de Samuel)
 *
 * « Le dashboard ne devrait pas suivre la semaine en cours réel, on borne
 * tout sur les dates spécifiées du projet. » La carte s'appelle donc
 * « Calendrier du projet » et non plus « Cette semaine ». Trois changements
 * structurants par rapport à la version précédente :
 *
 * 1. **La fenêtre vient du backend** (`GET /projects/{id}/window/` →
 *    `get_project_window`) : dates du projet si elles sont saisies, sinon du
 *    premier au dernier événement. Même règle que les écrans « Parcours » et
 *    les chronologies de fiche — délibérément pas réécrite en JS.
 * 2. **Un seul axe continu**, plus un axe 0h-24h par jour. Les positions sont
 *    donc des minutes DEPUIS LE DÉBUT DE LA FENÊTRE, pas des minutes dans la
 *    journée : `DAY_SPAN_MIN` a disparu au profit de `windowBounds.span`. Les
 *    journées ne structurent plus le gabarit, elles se lisent sur la
 *    graduation de l'axe et sur les lignes verticales renforcées à minuit
 *    (`--day`).
 * 3. **Une ligne par LIEU** sur toute la période (`venueRows`), au lieu d'un
 *    en-tête de jour suivi de ses lieux. Un transport touche deux lieux : il
 *    apparaît sur les deux lignes, chaque occurrence étant une COPIE
 *    indépendante (`{ ...item }`) pour que la voie assignée par `packLanes`
 *    sur une ligne n'écrase pas celle de l'autre.
 *
 * Le « filtre de dates » demandé ne demande pas de mécanisme séparé : les
 * puces de jour existantes restreignent les entrées visibles, et `autoWindow`
 * (donc le zoom par défaut et le bouton Réinitialiser) se resserre sur ce qui
 * reste — sélectionner un seul jour revient donc à s'y recentrer.
 *
 * ## Filtres
 *
 * Trois rangées de puces, toutes en `useChipFilter` (clic simple = une seule
 * valeur, ⌘+clic combine) : type en haut de page, jour et lieu au-dessus de
 * la timeline. Le filtre de type touche aussi « Spectacles à venir » ; les
 * filtres jour/lieu sont limités à la timeline. Les options disponibles
 * (`availableDays`/`availableVenues`) sont calculées AVANT le filtre
 * jour/lieu lui-même — une puce ne doit pas disparaître parce qu'on vient
 * d'en cocher une autre. Un transport compte pour ses deux lieux dans les
 * options, mais `venueRows` réapplique le filtre PAR LIEU : un transport dont
 * un seul des deux lieux est sélectionné ne perd que la ligne correspondante.
 *
 * ## Zoom et défilement
 *
 * Boutons +/- et Réinitialiser (`ZoomControls`, partagé avec les écrans
 * Parcours). Les positions des blocs restent TOUJOURS relatives à la fenêtre
 * complète du projet ; seule la largeur du conteneur change
 * (`zoomLevel = fullSpan / activeWindow.span`) et `scrollLeft` amène la
 * portion voulue à l'écran (`useZoomScroll`) — même principe que zoomer une
 * image dans un conteneur `overflow: auto`. `zoomWindow = null` ne veut PAS
 * dire « fenêtre complète » ici mais « fenêtre automatique » : `zoomOut` n'y
 * retombe jamais, seul `resetZoom` le fait (sémantique différente de
 * `useParcours.js`, piège à ne pas reproduire).
 *
 * ## Survol, clic et glisser-déposer
 *
 * Chaque bloc porte une info-bulle CSS-only (`block.details`) et navigue vers
 * sa fiche au clic. `.dash-timeline__track` et `.dash-timeline__block` n'ont
 * pas d'`overflow: hidden`, pour laisser l'info-bulle déborder.
 *
 * ⌘ + glisser ajuste l'horaire : poignées aux deux bords pour le début/la
 * fin, corps du bloc pour déplacer en gardant la durée. Sans ⌘, le clic
 * navigue normalement. Au relâchement, un PATCH **sans** `force` — en cas de
 * conflit bloquant (400) le bloc revient à sa place et un bandeau s'affiche,
 * l'arbitrage fin se fait sur la fiche.
 *
 * Deux conséquences du passage à l'axe continu, à connaître :
 * - un glisser horizontal peut désormais changer la DATE d'un événement, ce
 *   que l'ancien axe 0h-24h interdisait par construction ;
 * - la conversion pixel → minutes se fait sur toute la fenêtre du projet,
 *   donc un même geste vaut beaucoup plus de temps sur un projet long. C'est
 *   le zoom qui redonne de la précision.
 *
 * À noter (comportement backend préexistant) : `ShowSerializer.validate()` ne
 * bloque que les conflits de LIEU sur un changement d'horaire — matériel et
 * techniciens ne sont pas revalidés à ce moment-là, comme pour l'édition de
 * fiche.
 */

const { activeProjectId } = useActiveProject()

const loading = ref(false)
const loadError = ref(null)
const shows = ref([])
const materials = ref([])
const transports = ref([])
const report = ref({ venue_conflicts: [], material_conflicts: [], technician_conflicts: [], conflict_count: 0 })
// Fenêtre du projet, calculée par le backend (`get_project_window`) : dates
// saisies sur le projet, sinon du premier au dernier événement. Même règle que
// les écrans Parcours et les chronologies de fiche — pas de réécriture en JS.
const projectWindow = ref(null)

async function loadDashboard() {
  if (!activeProjectId.value) return
  loading.value = true
  loadError.value = null
  try {
    const [showsData, materialsData, reportData, transportsData, windowData] = await Promise.all([
      api.get('/shows/', { project: activeProjectId.value }),
      api.get('/materials/', { project: activeProjectId.value }),
      api.get(`/projects/${activeProjectId.value}/conflicts/`),
      api.get('/transports/', { project: activeProjectId.value }),
      api.get(`/projects/${activeProjectId.value}/window/`),
    ])
    shows.value = Array.isArray(showsData) ? showsData : (showsData.results ?? [])
    materials.value = Array.isArray(materialsData) ? materialsData : (materialsData.results ?? [])
    report.value = reportData
    transports.value = Array.isArray(transportsData) ? transportsData : (transportsData.results ?? [])
    projectWindow.value = windowData?.start && windowData?.end ? windowData : null
  } catch (e) {
    loadError.value = e
  } finally {
    loading.value = false
  }
}

watch(activeProjectId, loadDashboard, { immediate: true })

const today = new Intl.DateTimeFormat('fr-CA', {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
  year: 'numeric',
}).format(new Date())

const typeSuffix = {
  rehearsal: 'répétition',
  performance: 'représentation',
  storage: 'entreposage',
  setup: 'montage',
  teardown: 'démontage',
}

// Couleur des blocs de timeline par type d'événement. Montage et démontage
// (blocs rattachés, 2026-07-31) se distinguent du spectacle qu'ils encadrent :
// on doit voir d'un coup d'œil que la salle est occupée avant et après. Les
// couleurs « badge » des 5 types (rehearsal/performance/storage/setup/
// teardown, désormais personnalisables via Réglages — voir
// constants/eventTypeMeta.js) ne sont PAS reprises telles quelles ici : seuls
// Montage/Démontage ont une teinte dédiée dans cette timeline, calculée
// (`color-mix`, 2026-08-02) comme une déclinaison plus foncée de
// `--event-setup`/`--event-teardown` — une seule source par type, la nuance
// de la timeline n'est qu'un rendu différent de la même couleur. Répétition/
// Représentation/Entreposage restent volontairement sur le vert « statut OK »
// par défaut plus bas (sémantique, comme le rouge conflit/orange à
// approuver — hors de la portée des couleurs personnalisables).
const typeColors = {
  setup: 'color-mix(in oklch, var(--event-setup) 70%, black)',
  teardown: 'color-mix(in oklch, var(--event-teardown) 70%, black)',
}

// --- Filtre de catégories (2026-07-30, suite) ---
// Filtre les types d'entrées affichées dans la timeline « Cette semaine » et
// dans « Spectacles à venir » — les 3 event_type de Show (Spectacle/
// Répétition/Entreposage) plus Transport (n'apparaît que dans la timeline).
//
// ⌘+clic pour combiner plusieurs types (2026-08-01, à la demande de Samuel
// — même comportement que toutes les puces de filtre de l'app, voir
// useChipFilter.js). Avant ce changement, le Dashboard était le seul écran
// où le clic simple combinait déjà librement (bascule indépendante par
// type, sans ⌘) — remplacé par le même modèle Set « vide = tout affiché »
// que les autres écrans, pour que le geste soit identique partout.
const typeFilter = useChipFilter()

// Libellés au pluriel, propres à cet écran (une liste de ce qui se passe),
// alors que Réglages nomme un type au singulier. L'ORDRE, lui, est celui
// ENREGISTRÉ dans les Réglages (`Settings.event_type_order`, réordonnable par
// glisser-déposer depuis le 2026-08-02) — d'où le passage par
// `useEventDisplay` plutôt que par la constante par défaut. Les blocs rattachés (montage/
// démontage) sont des `Show` comme les autres : ils arrivent dans la même
// liste et se filtrent pareil.
const TYPE_LABELS = {
  rehearsal: 'Répétitions',
  setup: 'Montages',
  performance: 'Spectacles',
  teardown: 'Démontages',
  transport: 'Transports',
  storage: 'Entreposage',
}

const { eventTypeOrder } = useEventDisplay()

const typeChips = computed(() => {
  const defs = eventTypeOrder.value.map((key) => ({ key, label: TYPE_LABELS[key] }))
  return [
    { label: 'Tous', active: typeFilter.selected.value.size === 0, select: () => typeFilter.selectAll() },
    ...defs.map((d) => ({
      label: d.label,
      active: typeFilter.isSelected(d.key),
      select: (event) => typeFilter.toggle(d.key, event),
    })),
  ]
})

// --- Filtres jour/lieu (2026-08-02, suite, demande de Samuel) ---
// Portée limitée à « Cette semaine » (contrairement au filtre de type
// ci-dessus, qui touche aussi « Spectacles à venir ») — voir la note de
// tête du module.
const dayFilter = useChipFilter()
const venueFilter = useChipFilter()

// --- Conflits (réutilise le même rapport project-wide que ConflitsView.vue) ---

const conflictedShowIds = computed(() => {
  const ids = new Set()
  for (const group of ['venue_conflicts', 'material_conflicts', 'technician_conflicts']) {
    for (const pair of report.value[group] ?? []) {
      if (pair.a?.show_id) ids.add(pair.a.show_id)
      if (pair.b?.show_id) ids.add(pair.b.show_id)
    }
  }
  return ids
})

const conflictCount = computed(() => report.value.conflict_count ?? 0)
const hasConflicts = computed(() => conflictCount.value > 0)

const conflictSubtitle = computed(() => {
  const mat = report.value.material_conflicts ?? []
  const tech = report.value.technician_conflicts ?? []
  const venue = report.value.venue_conflicts ?? []
  if (mat.length) return `${mat[0].a.material_name} réservé sur 2 spectacles qui se chevauchent`
  if (tech.length) {
    const name = tech[0].a.technician_name ?? tech[0].b.technician_name
    return `${name} assigné sur 2 engagements qui se chevauchent`
  }
  if (venue.length) return `${venue[0].a.venue_name} réservé pour 2 spectacles qui se chevauchent`
  return ''
})

// --- Calendrier du projet ---
//
// Bornage au projet (2026-08-02, demande de Samuel : « le dashboard ne devrait
// pas suivre la semaine en cours réel, on borne tout sur les dates spécifiées
// du projet »). L'ancienne version découpait la semaine calendaire courante en
// une ligne par jour, chaque ligne étant un axe 0h-24h. Ici : UN SEUL axe
// continu couvrant toute la fenêtre du projet, et une ligne par LIEU — plus de
// notion de « jour » dans la structure, seulement dans la graduation de l'axe
// et dans les puces de filtre.
//
// Conséquence : les positions ne sont plus des minutes DANS LA JOURNÉE mais
// des minutes DEPUIS LE DÉBUT DE LA FENÊTRE. Tout ce qui manipulait
// `DAY_SPAN_MIN` (zoom, défilement, conversion pixel → temps du glisser) suit
// la même transformation.

function minutesSince(origin, date) {
  return (date.getTime() - origin.getTime()) / 60000
}

const dayLabelFmt = new Intl.DateTimeFormat('fr-CA', { weekday: 'short', day: 'numeric', month: 'short' })
const axisDayFmt = new Intl.DateTimeFormat('fr-CA', { day: 'numeric', month: 'short' })
const axisTimeFmt = new Intl.DateTimeFormat('fr-CA', { hour: '2-digit', minute: '2-digit', hour12: false })

// Bornes de la fenêtre du projet, en millisecondes + span en minutes.
const windowBounds = computed(() => {
  const w = projectWindow.value
  if (!w) return null
  const start = new Date(w.start)
  const end = new Date(w.end)
  const span = minutesSince(start, end)
  return span > 0 ? { start, end, span } : null
})

const windowLabel = computed(() => {
  const b = windowBounds.value
  if (!b) return null
  return `${dayLabelFmt.format(b.start)} → ${dayLabelFmt.format(b.end)}`
})

function fmtInstant(date) {
  return `${axisDayFmt.format(date)} ${axisTimeFmt.format(date)}`
}

// Spectacles et transports du projet, fusionnés en une seule liste d'entrées.
// Bornés à la fenêtre du projet : ce qui tombe dehors n'a pas de place sur
// l'axe. Indépendant du zoom et des filtres jour/lieu, comme avant — zoomer ne
// doit jamais recalculer QUELS événements existent.
const projectEntries = computed(() => {
  const bounds = windowBounds.value
  if (!bounds) return []
  const dansLaFenetre = (start, end) => end >= bounds.start && start <= bounds.end
  const entries = []
  for (const show of shows.value) {
    if (!typeFilter.passes(show.event_type)) continue
    const start = new Date(show.start_datetime)
    const end = new Date(show.end_datetime)
    if (!dansLaFenetre(start, end)) continue
    entries.push({
      kind: 'show',
      id: show.id,
      date: start,
      start,
      end,
      name: show.display_title,
      conflict: conflictedShowIds.value.has(show.id),
      venueName: show.venue_name,
      eventTypeLabel: typeSuffix[show.event_type] ?? show.event_type,
      typeColor: typeColors[show.event_type] ?? null,
      // Rattaché à un événement : la puce le rappelle dans l'info-bulle.
      parentTitle: show.parent_show_title ?? null,
      route: `/spectacles/${show.id}`,
    })
  }
  for (const t of transports.value) {
    if (!typeFilter.passes('transport')) continue
    // Une proposition auto non complétée (to_approve sans heure) n'a pas de
    // fenêtre exploitable — voir Transport.effective_end côté backend.
    if (!t.scheduled_datetime || !t.effective_end) continue
    const start = new Date(t.scheduled_datetime)
    const end = new Date(t.effective_end)
    if (!dansLaFenetre(start, end)) continue
    // Tournées multi-arrêts (2026-08-04) : le libellé enchaîne TOUS les
    // arrêts (codes courts) — plus de type livraison/ramassage (champ retiré).
    const stops = t.stops ?? []
    entries.push({
      kind: 'transport',
      id: t.id,
      date: start,
      start,
      end,
      name: stops.map((s) => s.venue_code || s.venue_name).join(' → '),
      status: t.status,
      conflict: !!t.has_technician_conflict,
      technicianName: (t.technician_names ?? []).join(', '),
      materialsSummary: t.is_empty ? 'Camion vide' : `${(t.materials ?? []).length} article(s)`,
      // Noms complets (pas les codes utilisés dans `name` ci-dessus) : ce
      // sont les clés de regroupement par lieu (voir `venueRows`) — TOUS les
      // arrêts de la tournée, dédupliqués (une tournée aller-retour repasse
      // par le même lieu).
      stopVenueNames: [...new Set(stops.map((s) => s.venue_name))],
      // Le redimensionnement (durée TOTALE) n'est sans ambiguïté que sur une
      // tournée à 2 arrêts — au-delà, l'ajustement se fait segment par
      // segment sur la fiche (voir beginDrag/onDragEnd).
      resizable: stops.length <= 2,
      route: `/transports/${t.id}`,
    })
  }
  return entries
})

// Options des puces jour/lieu : seulement ce qui est réellement présent dans
// le projet (après filtre de type, AVANT le filtre jour/lieu lui-même — une
// puce ne doit pas disparaître parce qu'on vient d'en cocher une autre).
const availableDays = computed(() => {
  const map = new Map()
  for (const entry of projectEntries.value) {
    const key = entry.date.toDateString()
    if (!map.has(key)) map.set(key, entry.date)
  }
  return [...map.entries()]
    .sort((a, b) => a[1] - b[1])
    .map(([key, date]) => ({ key, label: dayLabelFmt.format(date) }))
})

const dayChips = computed(() => [
  { label: 'Tous les jours', active: dayFilter.selected.value.size === 0, select: () => dayFilter.selectAll() },
  ...availableDays.value.map((d) => ({
    label: d.label,
    active: dayFilter.isSelected(d.key),
    select: (event) => dayFilter.toggle(d.key, event),
  })),
])

// Un transport touche deux lieux (origine + destination) : il compte pour
// les deux ici, même s'il n'apparaîtra en double dans la timeline que si les
// deux passent le filtre (voir `pushTo` dans `venueRows`).
const availableVenues = computed(() => {
  const set = new Set()
  for (const entry of projectEntries.value) {
    if (entry.kind === 'show') {
      if (entry.venueName) set.add(entry.venueName)
    } else {
      ;(entry.stopVenueNames ?? []).forEach((name) => set.add(name))
    }
  }
  return [...set].sort((a, b) => a.localeCompare(b, 'fr'))
})

const venueChips = computed(() => [
  { label: 'Tous les lieux', active: venueFilter.selected.value.size === 0, select: () => venueFilter.selectAll() },
  ...availableVenues.value.map((name) => ({
    label: name,
    active: venueFilter.isSelected(name),
    select: (event) => venueFilter.toggle(name, event),
  })),
])

const hasAnyEntries = computed(() => projectEntries.value.length > 0)

// Entrées qui passent le filtre jour ET (au sens large pour un transport : au
// moins UN des deux lieux) le filtre lieu — alimente `venueRows` ET
// `autoWindow`, pour que « Réinitialiser » se recentre sur ce qui reste
// visible après filtrage plutôt que sur le projet entier.
const visibleEntries = computed(() => projectEntries.value.filter((entry) => {
  if (!dayFilter.passes(entry.date.toDateString())) return false
  if (entry.kind === 'show') return venueFilter.passes(entry.venueName)
  return (entry.stopVenueNames ?? []).some((name) => venueFilter.passes(name))
}))

const LANE_HEIGHT = 34

// Empile les entrées qui se chevauchent en « voies » (lane 0, 1, 2…) et
// renvoie la hauteur de piste correspondante — appliqué PAR LIEU.
function packLanes(items) {
  const sorted = [...items].sort((a, b) => a.start - b.start)
  const laneEnds = []
  sorted.forEach((it) => {
    let lane = laneEnds.findIndex((end) => end <= it.start)
    if (lane === -1) {
      lane = laneEnds.length
      laneEnds.push(it.end)
    } else {
      laneEnds[lane] = it.end
    }
    it.lane = lane
  })
  return { items: sorted, rowHeight: `${laneEnds.length * LANE_HEIGHT - 4}px` }
}

// Une ligne par LIEU sur toute la fenêtre du projet (2026-08-02) — remplace
// l'ancien groupement jour PUIS lieu. Un lieu sans aucun événement n'a pas
// d'entrée dans la Map, rien à cacher explicitement. Indépendant du zoom : la
// hauteur d'une piste et la voie d'un bloc ne doivent pas sauter en zoomant.
const venueRows = computed(() => {
  const bounds = windowBounds.value
  if (!bounds) return []
  const byVenue = new Map()
  // Copie l'entrée (`{ ...item }`) plutôt que de partager la référence : un
  // transport est poussé dans DEUX lieux (origine + destination), chacun avec
  // sa propre voie assignée par `packLanes` — muter la même référence deux
  // fois écraserait la première assignation.
  const pushTo = (venueName, item) => {
    if (!venueName) return
    if (!venueFilter.passes(venueName)) return
    if (!byVenue.has(venueName)) byVenue.set(venueName, [])
    byVenue.get(venueName).push({ ...item })
  }
  for (const entry of visibleEntries.value) {
    const startMin = minutesSince(bounds.start, entry.start)
    const endMin = Math.max(startMin + 15, minutesSince(bounds.start, entry.end))
    const it = { ...entry, startMin, endMin }
    if (it.kind === 'show') {
      pushTo(it.venueName, it)
    } else {
      // Tournées (2026-08-04) : le bloc apparaît sur la ligne de CHAQUE lieu
      // desservi — arrêts intermédiaires compris (déjà dédupliqués).
      ;(it.stopVenueNames ?? []).forEach((name) => pushTo(name, it))
    }
  }
  return [...byVenue.entries()]
    .map(([venueName, items]) => {
      // `packLanes` trie sur `start`/`end` : on lui donne les minutes.
      const pour = items.map((it) => ({ ...it, start: it.startMin, end: it.endMin }))
      const { items: sorted, rowHeight } = packLanes(pour)
      return { venueName, items: sorted, rowHeight }
    })
    .sort((a, b) => a.venueName.localeCompare(b.venueName, 'fr'))
})

// Fenêtre AUTOMATIQUE : du premier au dernier événement VISIBLE, avec une
// marge d'une heure. C'est la fenêtre par défaut (zoom non actif) ET la cible
// du bouton Réinitialiser. Contrairement à la version « semaine », elle peut
// couvrir plusieurs jours — filtrer sur un seul jour la resserre dessus, ce
// qui donne le « filtre de dates » demandé sans mécanisme séparé.
const autoWindow = computed(() => {
  const bounds = windowBounds.value
  if (!bounds) return null
  const entries = visibleEntries.value
  if (entries.length === 0) return { start: 0, end: bounds.span, span: bounds.span }
  let winStart = Infinity
  let winEnd = -Infinity
  for (const entry of entries) {
    const startMin = minutesSince(bounds.start, entry.start)
    const endMin = Math.max(startMin + 15, minutesSince(bounds.start, entry.end))
    winStart = Math.min(winStart, startMin)
    winEnd = Math.max(winEnd, endMin)
  }
  winStart = Math.max(0, winStart - 60)
  winEnd = Math.min(bounds.span, winEnd + 60)
  return { start: winStart, end: winEnd, span: winEnd - winStart || 1 }
})

// --- Zoom (2026-08-02) ---
//
// Même mécanique qu'avant, la référence passant de la journée (1440 min) à la
// fenêtre du projet : les positions des blocs restent TOUJOURS relatives à
// cette fenêtre fixe, seule la largeur du conteneur change avec le zoom et
// `scrollLeft` amène la portion voulue à l'écran (voir `useZoomScroll`).

const ZOOM_FACTOR = 0.6
const MIN_ZOOM_SPAN_MIN = 15

// { start, end, span } en minutes depuis le début de la fenêtre du projet, ou
// `null` = fenêtre automatique (`autoWindow`). Comme avant, `null` NE
// représente PAS la fenêtre complète : `zoomOut` ne retombe jamais dessus,
// seul `resetZoom` le fait.
const zoomWindow = ref(null)

const fullSpan = computed(() => windowBounds.value?.span ?? 1)

function clampWindow(start, span) {
  const total = fullSpan.value
  const clampedSpan = Math.min(Math.max(span, MIN_ZOOM_SPAN_MIN), total)
  const clampedStart = Math.max(0, Math.min(total - clampedSpan, start))
  return { start: clampedStart, end: clampedStart + clampedSpan, span: clampedSpan }
}

const activeWindow = computed(() => zoomWindow.value ?? autoWindow.value)
const isZoomed = computed(() => zoomWindow.value != null)
const canZoomIn = computed(() => !!activeWindow.value && activeWindow.value.span > MIN_ZOOM_SPAN_MIN + 0.5)
const canZoomOut = computed(() => !!activeWindow.value && activeWindow.value.span < fullSpan.value - 0.5)

function zoomIn() {
  const base = activeWindow.value
  if (!base) return
  const center = (base.start + base.end) / 2
  const newSpan = base.span * ZOOM_FACTOR
  zoomWindow.value = clampWindow(center - newSpan / 2, newSpan)
}

function zoomOut() {
  const base = activeWindow.value
  if (!base) return
  const center = (base.start + base.end) / 2
  const newSpan = base.span / ZOOM_FACTOR
  zoomWindow.value = clampWindow(center - newSpan / 2, newSpan)
}

function resetZoom() {
  zoomWindow.value = null
}

// Changer de projet est le seul déclencheur automatique — PAS un rechargement
// après glisser-déposer (`onDragEnd` → `loadDashboard`), qui perdrait le zoom
// juste après qu'il ait servi à ajuster un bloc précisément.
watch(activeProjectId, () => { zoomWindow.value = null })

const zoomLevel = computed(() => {
  if (!activeWindow.value) return 1
  return fullSpan.value / activeWindow.value.span
})

const scrollFraction = computed(() => {
  if (!activeWindow.value) return 0
  return activeWindow.value.start / fullSpan.value
})

const scrollRef = ref(null)
useZoomScroll(scrollRef, zoomLevel, scrollFraction)

// --- Rendu de la timeline ---
//
// Les positions (left/width) sont TOUJOURS relatives à la fenêtre complète du
// projet — jamais à la portion zoomée. Seule la graduation de l'axe dépend de
// la fenêtre active, pour rester lisible à n'importe quel niveau de zoom.
const timeline = computed(() => {
  const bounds = windowBounds.value
  const active = activeWindow.value
  if (!bounds || !active) return { rows: [], hasEntries: false, marks: [] }
  const total = bounds.span

  // Graduation adaptative : de l'heure (fenêtre courte) au jour entier
  // (projet de plusieurs semaines). Les repères sont alignés sur des heures
  // rondes pour ne pas afficher « 03:47 ».
  const stepMin = active.span <= 240 ? 30
    : active.span <= 720 ? 60
      : active.span <= 2880 ? 180
        : active.span <= 10080 ? 360
          : 1440
  const marks = []
  const premier = new Date(bounds.start)
  premier.setMinutes(0, 0, 0)
  for (let t = minutesSince(bounds.start, premier); t <= total; t += stepMin) {
    if (t < 0) continue
    const instant = new Date(bounds.start.getTime() + t * 60000)
    const minuit = instant.getHours() === 0 && instant.getMinutes() === 0
    marks.push({
      key: t,
      left: `${(t / total) * 100}%`,
      label: stepMin >= 1440 || minuit ? axisDayFmt.format(instant) : axisTimeFmt.format(instant),
      isDayStart: minuit,
    })
  }

  const rows = venueRows.value.map((venue) => {
    const blocks = venue.items.map((it) => {
      const left = (it.startMin / total) * 100
      const width = (Math.max(it.endMin - it.startMin, 1) / total) * 100

      // Rouge = conflit (chevauchement réel, spectacle ou technicien de
      // transport). Sinon : vert pour un spectacle, fuchsia pour un
      // transport confirmé (`--transport`), orange pour une proposition à
      // approuver — mêmes couleurs de statut que TransportsView.vue.
      let color = 'oklch(0.72 0.13 165)'
      let textColor = '#062622'
      if (it.conflict) {
        color = 'oklch(0.7 0.16 35)'
        textColor = '#2a1400'
      } else if (it.kind === 'transport') {
        if (it.status === 'to_approve') {
          color = 'oklch(0.78 0.13 85)'
          textColor = '#2a1f00'
        } else {
          color = 'var(--transport)'
          textColor = '#211c33'
        }
      } else if (it.typeColor) {
        // Bloc rattaché (montage/démontage) : teinte plus sourde que
        // l'événement qu'il encadre, pour lire la séquence d'un coup d'œil.
        color = it.typeColor
        textColor = 'rgba(var(--fg-rgb),.9)'
      }
      const details = it.kind === 'transport'
        ? [
            it.status === 'to_approve' ? 'À approuver' : 'Confirmé',
            it.technicianName ? `Technicien : ${it.technicianName}` : 'Aucun technicien assigné',
            it.materialsSummary,
          ]
        : [
            it.venueName,
            it.eventTypeLabel,
            ...(it.parentTitle ? [`Rattaché à « ${it.parentTitle} »`] : []),
          ]
      if (it.conflict) details.push(it.kind === 'transport' ? 'Conflit technicien' : "Conflit d'horaire")

      return {
        id: it.id,
        kind: it.kind,
        startMin: it.startMin,
        endMin: it.endMin,
        left: `${left}%`,
        width: `${width}%`,
        top: `${it.lane * LANE_HEIGHT}px`,
        name: it.name,
        time: `${fmtInstant(it.start)} – ${axisTimeFmt.format(it.end)}`,
        color,
        textColor,
        details,
        route: it.route,
      }
    })
    return { venueName: venue.venueName, blocks, rowHeight: venue.rowHeight }
  })

  return { rows, hasEntries: rows.length > 0, marks }
})

// --- Glisser-déposer pour ajuster l'horaire (voir note du module) ---

const MIN_DURATION_MINUTES = 15

// { kind, id, mode: 'move'|'resize-start'|'resize-end',
//   originStartMin, originEndMin, startMin, endMin, pointerStartX, trackWidthPx }
// Les minutes sont comptées depuis le début de la fenêtre du projet.
const dragState = ref(null)
const dragError = ref(null)
let suppressClick = false

// Minutes depuis le début de la fenêtre du projet → instant réel. Un glisser
// horizontal peut donc désormais changer la DATE d'un événement, ce que
// l'ancienne version (un axe 0h-24h par jour) interdisait par construction.
// C'est la conséquence assumée d'un axe continu : sur une piste où deux jours
// se suivent, empêcher de franchir minuit n'aurait aucun sens visuel.
function minutesToDate(minutes) {
  const bounds = windowBounds.value
  return new Date(bounds.start.getTime() + Math.round(minutes) * 60000)
}

function blockStyle(block) {
  const fullSpan = windowBounds.value?.span ?? 1
  const state = dragState.value
  if (state && state.kind === block.kind && state.id === block.id) {
    // Relatif à la journée complète, comme le rendu normal — voir la note
    // de tête sur le défilement horizontal sous zoom.
    return {
      top: block.top,
      left: `${(state.startMin / fullSpan) * 100}%`,
      width: `${((state.endMin - state.startMin) / fullSpan) * 100}%`,
      background: block.color,
      color: block.textColor,
    }
  }
  return {
    top: block.top,
    left: block.left,
    width: block.width,
    background: block.color,
    color: block.textColor,
  }
}

function blockTimeLabel(block) {
  const state = dragState.value
  if (state && state.kind === block.kind && state.id === block.id) {
    return `${fmtInstant(minutesToDate(state.startMin))} – ${axisTimeFmt.format(minutesToDate(state.endMin))}`
  }
  return block.time
}

function isDragging(block) {
  const state = dragState.value
  return !!state && state.kind === block.kind && state.id === block.id
}

function beginDrag(block, mode, event) {
  // Glisser-déposer réservé à Cmd (⌘) enfoncée — évite les ajustements
  // accidentels d'horaire lors d'un simple clic. Sans Cmd, on ne fait rien
  // ici : l'événement continue sa route normalement (clic → navigation,
  // même sur une poignée, faute de stopPropagation/preventDefault).
  if (!event.metaKey) return
  event.preventDefault()
  event.stopPropagation()
  // Une tournée à plus de 2 arrêts ne se redimensionne pas ici : sa durée
  // totale est la somme de ses segments, à ajuster sur la fiche (2026-08-04).
  // La déplacer (mode 'move') reste permis — une seule heure d'ancrage.
  if (mode !== 'move' && block.kind === 'transport' && block.resizable === false) {
    dragError.value = 'Cette tournée a plusieurs segments — ajuste les durées arrêt par arrêt sur sa fiche.'
    return
  }
  const track = event.currentTarget.closest('.dash-timeline__track')
  if (!track) return
  dragError.value = null
  // Un clic sur une poignée de redimensionnement ne doit jamais naviguer,
  // même sans mouvement. Un clic sur le corps du bloc (mode 'move') doit
  // encore naviguer si aucun glisser réel n'a eu lieu — voir onDragMove.
  suppressClick = mode !== 'move'
  dragState.value = {
    kind: block.kind,
    id: block.id,
    mode,
    originStartMin: block.startMin,
    originEndMin: block.endMin,
    startMin: block.startMin,
    endMin: block.endMin,
    pointerStartX: event.clientX,
    trackWidthPx: track.getBoundingClientRect().width || 1,
  }
  window.addEventListener('pointermove', onDragMove)
  window.addEventListener('pointerup', onDragEnd, { once: true })
}

function onDragMove(event) {
  const state = dragState.value
  if (!state) return
  const deltaPx = event.clientX - state.pointerStartX
  if (Math.abs(deltaPx) > 3) suppressClick = true
  // trackWidthPx représente toujours la fenêtre COMPLÈTE du projet à
  // l'échelle du zoom courant — voir la note de tête. Un même déplacement en
  // pixels vaut donc beaucoup plus de minutes qu'avant sur un projet long :
  // c'est le zoom qui redonne de la précision, comme pour l'ancienne version.
  const total = fullSpan.value
  const deltaMin = (deltaPx / state.trackWidthPx) * total

  let newStart = state.originStartMin
  let newEnd = state.originEndMin
  if (state.mode === 'move') {
    const duration = state.originEndMin - state.originStartMin
    newStart = Math.max(0, Math.min(total - duration, state.originStartMin + deltaMin))
    newEnd = newStart + duration
  } else if (state.mode === 'resize-start') {
    newStart = Math.max(0, Math.min(state.originEndMin - MIN_DURATION_MINUTES, state.originStartMin + deltaMin))
  } else {
    newEnd = Math.min(total, Math.max(state.originStartMin + MIN_DURATION_MINUTES, state.originEndMin + deltaMin))
  }
  dragState.value = { ...state, startMin: newStart, endMin: newEnd }
}

async function onDragEnd() {
  window.removeEventListener('pointermove', onDragMove)
  const state = dragState.value
  if (!state) return
  // Pas de mouvement réel (simple clic relâché sur place) : rien à
  // enregistrer, le clic normal (navigation) prend le relais.
  if (Math.round(state.startMin) === Math.round(state.originStartMin) && Math.round(state.endMin) === Math.round(state.originEndMin)) {
    dragState.value = null
    return
  }
  // Le bloc garde sa position glissée (dragState reste actif) pendant
  // l'aller-retour réseau, pour éviter un flash de retour à la position
  // d'origine avant que loadDashboard() ne recalcule la vraie position.
  const newStart = minutesToDate(state.startMin)
  const newEnd = minutesToDate(state.endMin)
  try {
    if (state.kind === 'show') {
      await api.patch(`/shows/${state.id}/`, {
        start_datetime: newStart.toISOString(),
        end_datetime: newEnd.toISOString(),
      })
    } else if (state.mode === 'move') {
      // Déplacer une tournée = décaler sa seule heure d'ancrage (2026-08-04) ;
      // ne pas renvoyer la durée totale, ambiguë sur une tournée multi-arrêts
      // (et sujette aux arrondis de la timeline).
      await api.patch(`/transports/${state.id}/`, {
        scheduled_datetime: newStart.toISOString(),
      })
    } else {
      // Redimensionnement : seulement possible sur une tournée à 2 arrêts
      // (voir beginDrag) — la durée totale = l'unique segment, sans ambiguïté.
      await api.patch(`/transports/${state.id}/`, {
        scheduled_datetime: newStart.toISOString(),
        estimated_duration_minutes: Math.max(1, Math.round(state.endMin - state.startMin)),
      })
    }
    await loadDashboard()
  } catch (e) {
    // Conflit bloquant (venue/technicien/fenêtre départ-arrivée) : le bloc
    // reprend sa position d'origine (on n'a jamais muté shows/transports),
    // pas de bouton « Forcer » ici — l'ajustement fin se fait sur la fiche.
    dragError.value = e.data?.detail ?? "Impossible d'appliquer ce changement d'horaire (conflit détecté)."
  } finally {
    dragState.value = null
  }
}

function handleBlockClick(block) {
  if (suppressClick) {
    suppressClick = false
    return
  }
  router.push(block.route)
}

// --- Stats ---

const showsThisMonth = computed(() => {
  const now = new Date()
  return shows.value.filter((s) => {
    const d = new Date(s.start_datetime)
    return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth()
  }).length
})

const totalItems = computed(() => materials.value.reduce((sum, m) => sum + (m.quantity ?? 0), 0))

// --- Spectacles à venir ---

const upcoming = computed(() => {
  const now = new Date()
  return shows.value
    .filter((s) => new Date(s.end_datetime) >= now && typeFilter.passes(s.event_type))
    .sort((a, b) => new Date(a.start_datetime) - new Date(b.start_datetime))
    .slice(0, 5)
    .map((s) => {
      const start = new Date(s.start_datetime)
      const end = new Date(s.end_datetime)
      const isToday = start.toDateString() === now.toDateString()
      const timeRange = `${axisTimeFmt.format(start)}–${axisTimeFmt.format(end)}`
      const conflict = conflictedShowIds.value.has(s.id)
      return {
        id: s.id,
        // Un bloc (montage/démontage/répétition rattachée) a déjà son type
        // dans `display_title` (2026-08-02, voir `Show.display_title`) —
        // lui accoler le suffixe de type le doublerait.
        title: s.parent_show
          ? s.display_title
          : `${s.title} — ${typeSuffix[s.event_type] ?? s.event_type}`,
        venue: s.venue_name,
        time: isToday ? timeRange : `${dayLabelFmt.format(start)} ${timeRange}`,
        conflict,
        rowBg: conflict ? 'oklch(0.27 0.07 35 / .5)' : 'var(--bg-row)',
        rowBorder: conflict ? '1px solid oklch(0.5 0.15 35 / .6)' : '1px solid transparent',
        dotColor: conflict ? 'oklch(0.7 0.16 35)' : 'oklch(0.72 0.13 165)',
      }
    })
})
</script>

<template>
  <AppShell>
    <div v-if="loading" class="hint">Chargement…</div>
    <div v-else-if="loadError" class="hint hint--error">
      Impossible de charger le tableau de bord. Es-tu connecté (session Django) ?
    </div>

    <div v-else class="dash">
      <div class="dash-header">
        <h1 class="page-title">Tableau de bord</h1>
        <div class="dash-date">{{ today }}</div>
      </div>

      <!-- Filtres de page (2026-08-02, demande de Samuel : les lieux sortent
           de la carte pour rejoindre les types) : type et lieu vivent au même
           niveau, au-dessus de tout. Le filtre de JOUR reste dans la carte —
           il ne concerne que la timeline, alors que ces deux-ci s'appliquent
           aussi à « Spectacles à venir » pour le type. -->
      <div class="filters">
        <div class="filters__row">
          <span class="filters__label">Type</span>
          <div
            v-for="f in typeChips"
            :key="f.label"
            class="chip"
            :class="{ 'chip--active': f.active }"
            @click="f.select($event)"
          >
            {{ f.label }}
          </div>
        </div>
        <div v-if="hasAnyEntries" class="filters__row">
          <span class="filters__label">Lieu</span>
          <div
            v-for="f in venueChips"
            :key="'venue-' + f.label"
            class="chip"
            :class="{ 'chip--active': f.active }"
            @click="f.select($event)"
          >{{ f.label }}</div>
        </div>
      </div>

      <div v-if="hasConflicts" class="dash-alert">
        <span class="dash-alert__dot" />
        <div class="dash-alert__body">
          <div class="dash-alert__title">{{ conflictCount }} conflit{{ conflictCount > 1 ? 's' : '' }} d'horaire actif{{ conflictCount > 1 ? 's' : '' }}</div>
          <div class="dash-alert__subtitle">{{ conflictSubtitle }}</div>
        </div>
        <RouterLink to="/conflits" class="dash-alert__cta">Voir le{{ conflictCount > 1 ? 's' : '' }} conflit{{ conflictCount > 1 ? 's' : '' }} →</RouterLink>
      </div>

      <div class="dash-card">
        <div class="dash-card__head">
          <div class="dash-card__title">Calendrier du projet</div>
          <div class="dash-card__window" v-if="windowLabel">{{ windowLabel }}</div>
          <ZoomControls
            v-if="timeline.hasEntries"
            :is-zoomed="isZoomed"
            :can-zoom-in="canZoomIn"
            :can-zoom-out="canZoomOut"
            @zoom-in="zoomIn"
            @zoom-out="zoomOut"
            @reset="resetZoom"
          />
        </div>
        <div v-if="hasAnyEntries" class="dash-timeline-filters">
          <div class="dash-timeline-filters__row">
            <span class="dash-timeline-filters__label">Jour</span>
            <div
              v-for="f in dayChips"
              :key="'day-' + f.label"
              class="chip"
              :class="{ 'chip--active': f.active }"
              @click="f.select($event)"
            >{{ f.label }}</div>
          </div>
        </div>
        <div v-if="dragError" class="dash-drag-error">
          {{ dragError }}
          <span class="dash-drag-error__dismiss" @click="dragError = null">✕</span>
        </div>
        <div v-if="timeline.hasEntries" class="dash-timeline">
          <div class="dash-timeline__labels">
            <div class="dash-timeline__labels-spacer" />
            <div
              v-for="row in timeline.rows"
              :key="'label-' + row.venueName"
              class="dash-timeline__venue-label"
              :style="{ height: row.rowHeight }"
            >{{ row.venueName }}</div>
          </div>

          <div ref="scrollRef" class="dash-timeline__scroll">
            <div class="dash-timeline__scroll-content" :style="{ width: `${zoomLevel * 100}%` }">
              <div class="dash-timeline__axis">
                <span
                  v-for="mark in timeline.marks"
                  :key="mark.key"
                  class="dash-timeline__axis-mark"
                  :class="{ 'dash-timeline__axis-mark--day': mark.isDayStart }"
                  :style="{ left: mark.left }"
                >{{ mark.label }}</span>
              </div>
              <div
                v-for="row in timeline.rows"
                :key="'track-' + row.venueName"
                class="dash-timeline__track"
                :style="{ height: row.rowHeight }"
              >
                <div
                  v-for="mark in timeline.marks"
                  :key="'grid-' + mark.key"
                  class="dash-timeline__gridline"
                  :class="{ 'dash-timeline__gridline--day': mark.isDayStart }"
                  :style="{ left: mark.left }"
                />
                <div
                  v-for="block in row.blocks"
                  :key="block.kind + '-' + block.id"
                  class="dash-timeline__block"
                  :class="{
                    'dash-timeline__block--transport': block.kind === 'transport',
                    'dash-timeline__block--dragging': isDragging(block),
                  }"
                  :style="blockStyle(block)"
                  @pointerdown="beginDrag(block, 'move', $event)"
                  @click="handleBlockClick(block)"
                >
                  <div class="dash-timeline__handle dash-timeline__handle--start" @pointerdown="beginDrag(block, 'resize-start', $event)" />
                  <div class="dash-timeline__block-name">{{ block.name }}</div>
                  <div class="dash-timeline__block-time">{{ blockTimeLabel(block) }}</div>
                  <div class="dash-timeline__handle dash-timeline__handle--end" @pointerdown="beginDrag(block, 'resize-end', $event)" />

                  <div class="dash-timeline__tooltip">
                    <div class="dash-timeline__tooltip-title">{{ block.name }}</div>
                    <div class="dash-timeline__tooltip-time">{{ blockTimeLabel(block) }}</div>
                    <div v-for="(line, i) in block.details" :key="i" class="dash-timeline__tooltip-line">{{ line }}</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div v-else-if="hasAnyEntries" class="row-empty">Aucun événement ne correspond aux filtres jour/lieu sélectionnés.</div>
        <div v-else-if="!windowLabel" class="row-empty">
          Ce projet n'a ni dates ni événement : il n'y a pas encore de période à
          afficher. Tu peux saisir les dates du projet dans les Réglages.
        </div>
        <div v-else class="row-empty">Aucun spectacle ni transport dans la période du projet.</div>
        <div class="dash-legend">
          <div class="dash-legend__item">
            <span class="dash-legend__swatch dash-legend__swatch--conflict" />Chevauchement
            (conflit)
          </div>
          <div class="dash-legend__item">
            <span class="dash-legend__swatch dash-legend__swatch--ok" />Spectacle
          </div>
          <div class="dash-legend__item">
            <span class="dash-legend__swatch dash-legend__swatch--transport" />Transport confirmé
          </div>
          <div class="dash-legend__item">
            <span class="dash-legend__swatch dash-legend__swatch--transport-pending" />Transport à approuver
          </div>
          <div class="dash-legend__item dash-legend__item--hint">⌘ + glisser un bloc pour ajuster son horaire</div>
        </div>
      </div>

      <div class="dash-stats">
        <div class="dash-stat">
          <div class="dash-stat__value">{{ showsThisMonth }}</div>
          <div class="dash-stat__label">spectacles ce mois</div>
        </div>
        <div class="dash-stat">
          <div class="dash-stat__value dash-stat__value--accent">{{ conflictCount }}</div>
          <div class="dash-stat__label">conflit(s) à résoudre</div>
        </div>
        <div class="dash-stat">
          <div class="dash-stat__value">{{ totalItems }}</div>
          <div class="dash-stat__label">items en inventaire</div>
        </div>
      </div>

      <div class="dash-card">
        <div class="dash-card__title">Spectacles à venir</div>
        <div class="dash-upcoming">
          <RouterLink
            v-for="show in upcoming"
            :key="show.id"
            :to="`/spectacles/${show.id}`"
            class="dash-upcoming__row"
            :style="{ background: show.rowBg, border: show.rowBorder }"
          >
            <span class="dash-upcoming__dot" :style="{ background: show.dotColor }" />
            <div class="dash-upcoming__body">
              <div class="dash-upcoming__title">{{ show.title }}</div>
              <div class="dash-upcoming__subtitle">{{ show.venue }} · {{ show.time }}</div>
            </div>
            <div v-if="show.conflict" class="dash-upcoming__badge">CONFLIT</div>
          </RouterLink>
          <div v-if="upcoming.length === 0" class="row-empty">Aucun spectacle à venir.</div>
        </div>
      </div>
    </div>
  </AppShell>
</template>

<style scoped>
.hint {
  padding: 32px 40px;
  font: 500 13px system-ui;
  color: rgba(var(--fg-rgb), 0.5);
}

.hint--error {
  color: oklch(0.78 0.16 35);
}

.row-empty {
  font: 500 12.5px system-ui;
  color: rgba(var(--fg-rgb), 0.4);
  padding: 10px 0;
}

.dash {
  display: flex;
  flex-direction: column;
  gap: 22px;
}

.dash-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

/* Deux rangées étiquetées (2026-08-02) : le filtre de lieu a rejoint celui
   de type hors de la carte. Même gabarit que `.dash-timeline-filters`, resté
   dans la carte pour le seul filtre de jour. */
.filters {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.filters__row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.filters__label {
  font: 700 10px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: rgba(var(--fg-rgb), 0.35);
  min-width: 34px;
}

.dash-date {
  font: 500 12px system-ui;
  color: rgba(var(--fg-rgb), 0.4);
  text-transform: capitalize;
}

.dash-alert {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 14px 18px;
  border-radius: var(--radius-notch-lg);
  background: oklch(0.27 0.07 35);
  border: 1px solid oklch(0.5 0.15 35);
}

.dash-alert__dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: oklch(0.7 0.16 35);
  flex: none;
  box-shadow: 0 0 0 4px oklch(0.7 0.16 35 / 0.25);
}

.dash-alert__body {
  flex: 1;
}

.dash-alert__title {
  font: 700 13.5px system-ui;
  color: #ffe3c9;
}

.dash-alert__subtitle {
  font: 400 12px system-ui;
  color: rgba(255, 217, 207, 0.75);
}

.dash-alert__cta {
  font: 600 12px system-ui;
  color: #ffe3c9;
  padding: 6px 12px;
  border: 1px solid oklch(0.6 0.15 35);
  border-radius: var(--radius-notch-sm);
  white-space: nowrap;
  cursor: pointer;
  text-decoration: none;
}

.dash-card {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-notch-lg);
  padding: 20px;
}

.dash-card__title {
  font: 700 12px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: rgba(var(--fg-rgb), 0.65);
  margin-bottom: 16px;
}

/* Titre + contrôles de zoom sur une même ligne (2026-08-02) — seule « Cette
   semaine » en a besoin ; « Spectacles à venir » garde son
   `.dash-card__title` seul, avec sa marge basse habituelle (annulée ici
   puisque c'est `.dash-card__head` qui la porte pour toute la ligne). */
.dash-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 16px;
}

.dash-card__window {
  flex: 1;
  font: 600 11px var(--font-mono);
  color: rgba(var(--fg-rgb), 0.4);
}

.dash-card__head .dash-card__title {
  margin-bottom: 0;
}

/* Puces jour/lieu (2026-08-02, suite, demande de Samuel) — portée limitée à
   « Cette semaine », contrairement aux puces de type (`.filters` plus haut)
   qui touchent aussi « Spectacles à venir ». Deux rangées avec un libellé de
   colonne (« Jour »/« Lieu ») pour ne pas les confondre au premier regard. */
.dash-timeline-filters {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 14px;
}

.dash-timeline-filters__row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.dash-timeline-filters__label {
  flex: none;
  min-width: 32px;
  font: 700 10px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: rgba(var(--fg-rgb), 0.35);
}

.dash-drag-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  border-radius: var(--radius-notch-sm);
  background: oklch(0.27 0.07 35);
  border: 1px solid oklch(0.5 0.15 35);
  color: rgba(255, 217, 207, 0.9);
  font: 500 12px system-ui;
  margin-bottom: 14px;
}

.dash-drag-error__dismiss {
  cursor: pointer;
  color: rgba(255, 217, 207, 0.6);
  flex: none;
}

/* Deux colonnes (2026-08-02, suite — défilement horizontal sous zoom) :
   étiquettes de jour fixes à gauche, axe + pistes défilables à droite dans
   `.dash-timeline__scroll` — même structure que `.parcours-labels`/
   `.parcours-scroll` sur les deux écrans Parcours. */
.dash-timeline {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.dash-timeline__labels {
  width: 140px;
  flex: none;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.dash-timeline__labels-spacer {
  height: 16px;
}

/* Une ligne par lieu, sur toute la fenêtre du projet (2026-08-02) — les
   en-têtes de jour et leur espaceur côté piste ont disparu avec le
   découpage par jour, les journées se lisent maintenant sur l'axe et sur les
   lignes verticales renforcées à minuit. */
.dash-timeline__venue-label {
  display: flex;
  align-items: center;
  font: 600 11.5px system-ui;
  color: rgba(var(--fg-rgb), 0.6);
}

.dash-timeline__scroll {
  flex: 1;
  min-width: 0;
  overflow-x: auto;
  /* `overflow-y: hidden` explicite (2026-08-02, même correction que
     `.parcours-scroll` dans style.css, bug signalé par Samuel) — sinon
     `overflow-x: auto` fait passer `overflow-y` à `auto` aussi, ce qui en
     fait une deuxième zone de défilement vertical qui capte la molette/le
     trackpad indépendamment de `.dash-timeline__labels`, désynchronisant
     les noms de jour à gauche des pistes. Le défilement vertical doit
     rester celui de la page, qui fait bouger les deux colonnes ensemble. */
  overflow-y: hidden;
}

.dash-timeline__scroll-content {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 100%;
}

.dash-timeline__axis {
  position: relative;
  height: 16px;
}

.dash-timeline__axis-mark {
  position: absolute;
  transform: translateX(-50%);
  font: 600 9.5px var(--font-mono);
  color: rgba(var(--fg-rgb), 0.35);
  white-space: nowrap;
}

.dash-timeline__track {
  position: relative;
  background: var(--bg-row);
  border-radius: var(--radius-notch-sm);
  /* Pas d'overflow:hidden : l'info-bulle au survol (position absolue,
     ancrée au bloc) doit pouvoir déborder au-dessus de la piste. */
}

.dash-timeline__gridline {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--border-card);
}

/* Changement de jour marqué plus franchement que les repères horaires : sur
   un axe continu couvrant plusieurs semaines, c'est le seul indice de la
   frontière entre deux journées (2026-08-02). */
.dash-timeline__gridline--day {
  background: rgba(var(--fg-rgb), 0.18);
}

.dash-timeline__axis-mark--day {
  color: rgba(var(--fg-rgb), 0.6);
}

.dash-timeline__block {
  position: absolute;
  height: 30px;
  border-radius: 0 6px 0 6px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 0 10px;
  cursor: grab;
  user-select: none;
  touch-action: none;
  /* Pas d'overflow:hidden ici : l'info-bulle (enfant, position absolue)
     doit pouvoir déborder du bloc. Le nom/l'heure ont déjà leur propre
     ellipsis (voir .dash-timeline__block-name/-time) donc rien n'est perdu
     visuellement à l'intérieur du bloc. */
}

.dash-timeline__block--dragging {
  cursor: grabbing;
  z-index: 25;
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.45);
}

.dash-timeline__block--dragging .dash-timeline__tooltip {
  display: none;
}

/* Poignées de redimensionnement (début/fin) — fines bandes aux bords,
   au-dessus du contenu (nom/heure) pour capter le pointeur en premier. */
.dash-timeline__handle {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 8px;
  cursor: ew-resize;
  z-index: 5;
}

.dash-timeline__handle--start {
  left: 0;
}

.dash-timeline__handle--end {
  right: 0;
}

/* Un transport se distingue d'un spectacle par une bordure pointillée,
   en plus de sa couleur (vert/fuchsia/orange/rouge — voir `timeline`). */
.dash-timeline__block--transport {
  border: 1px dashed rgba(0, 0, 0, 0.25);
}

.dash-timeline__tooltip {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 50%;
  transform: translateX(-50%);
  min-width: 170px;
  max-width: 240px;
  padding: 10px 12px;
  border-radius: var(--radius-notch-sm);
  background: var(--bg-deep);
  border: 1px solid rgba(var(--fg-rgb), 0.12);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
  opacity: 0;
  visibility: hidden;
  pointer-events: none;
  transition: opacity 0.12s ease;
  z-index: 30;
}

.dash-timeline__block:hover .dash-timeline__tooltip {
  opacity: 1;
  visibility: visible;
}

.dash-timeline__tooltip-title {
  font: 700 12px system-ui;
  color: rgb(var(--fg-rgb));
  white-space: normal;
  margin-bottom: 4px;
}

.dash-timeline__tooltip-time {
  font: 600 11px system-ui;
  color: rgba(var(--fg-rgb), 0.55);
  margin-bottom: 6px;
}

.dash-timeline__tooltip-line {
  font: 500 11.5px system-ui;
  color: rgba(var(--fg-rgb), 0.75);
  line-height: 1.4;
}

.dash-timeline__block-name {
  font: 700 11px system-ui;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.dash-timeline__block-time {
  font: 600 9.5px system-ui;
  opacity: 0.8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.dash-legend {
  display: flex;
  gap: 16px;
  margin-top: 16px;
  font: 500 11px system-ui;
  color: rgba(var(--fg-rgb), 0.45);
}

.dash-legend__item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.dash-legend__item--hint {
  margin-left: auto;
  color: rgba(var(--fg-rgb), 0.3);
  font-style: italic;
}

.dash-legend__swatch {
  width: 8px;
  height: 8px;
  border-radius: 2px;
}

.dash-legend__swatch--conflict {
  background: oklch(0.7 0.16 35);
}

.dash-legend__swatch--ok {
  background: oklch(0.72 0.13 165);
}

.dash-legend__swatch--transport {
  background: var(--transport);
}

.dash-legend__swatch--transport-pending {
  background: oklch(0.78 0.13 85);
}

.dash-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
}

.dash-stat {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-notch-lg);
  padding: 16px;
}

.dash-stat__value {
  font: 800 34px var(--font-mono);
  letter-spacing: 0.02em;
  color: rgb(var(--fg-rgb));
}

.dash-stat__value--accent {
  color: oklch(0.72 0.16 35);
}

.dash-stat__label {
  font: 500 12px system-ui;
  color: rgba(var(--fg-rgb), 0.5);
}

.dash-upcoming {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dash-upcoming__row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: var(--radius-notch-sm);
  text-decoration: none;
}

.dash-upcoming__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
}

.dash-upcoming__body {
  flex: 1;
  min-width: 0;
}

.dash-upcoming__title {
  font: 600 14px var(--font-mono);
  color: rgb(var(--fg-rgb));
}

.dash-upcoming__subtitle {
  font: 400 11.5px system-ui;
  color: rgba(var(--fg-rgb), 0.5);
}

.dash-upcoming__badge {
  font: 700 10.5px ui-monospace, monospace;
  color: oklch(0.85 0.13 35);
  background: oklch(0.7 0.16 35 / 0.18);
  padding: 3px 8px;
  border-radius: 0 10px 0 10px;
  flex: none;
}
</style>

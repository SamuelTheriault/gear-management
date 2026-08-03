<script setup>
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppShell from '../components/AppShell.vue'
import ZoomControls from '../components/ZoomControls.vue'
import { api } from '../api/client'
import { useActiveProject } from '../composables/useActiveProject'
import { useChipFilter } from '../composables/useChipFilter'
import { useZoomScroll } from '../composables/useZoomScroll'

const router = useRouter()

/**
 * Tableau de bord — port de Dashboard.dc.html, branché sur l'API réelle
 * (2026-07-30). Le port initial (voir historique) reprenait tel quel les
 * données de démonstration de la maquette ; maintenant que toutes les
 * autres sections de l'app sont branchées (phases 1-3), c'est la dernière
 * pièce statique.
 *
 * Données : GET /api/shows/?project=, GET /api/materials/?project= (pour le
 * total d'items), GET /api/projects/{id}/conflicts/ (déjà utilisé par
 * ConflitsView.vue — vue d'ensemble dédupliquée des conflits), GET
 * /api/transports/?project= (2026-07-30, suite : les déplacements
 * apparaissent maintenant dans la timeline « Cette semaine », aux côtés des
 * spectacles — un déplacement sans `scheduled_datetime` (proposition
 * `to_approve` non complétée) est ignoré, faute de fenêtre exploitable, même
 * logique que `Transport.effective_end`/`is_confirmed` côté backend).
 *
 * Filtre de type (2026-07-30, suite ; passé à `useChipFilter` le
 * 2026-08-01) : puces « Spectacles/Répétitions/Entreposage/Transports » en
 * haut de page (`typeFilter`/`typeChips`) — clic simple = un seul type,
 * ⌘+clic combine, comme partout ailleurs dans l'app. S'applique à la
 * timeline « Cette semaine » et à « Spectacles à venir ». Ne touche pas aux
 * cartes de stats (spectacles ce mois, conflits, items en inventaire), qui
 * ne se découpent pas naturellement par ce même type.
 *
 * Survol/clic sur un bloc (2026-07-30, suite) : chaque bloc de la timeline
 * porte une info-bulle (`block.details`, CSS-only via `:hover` — pas d'état
 * Vue à gérer) avec les détails utiles (lieu + type pour un spectacle,
 * technicien + contenu du camion pour un transport, conflit le cas échéant),
 * et navigue vers `/spectacles/:id` ou `/transports/:id` au clic
 * (`block.route`, résolu via `useRouter().push`). `.dash-timeline__track` et
 * `.dash-timeline__block` ont perdu leur `overflow:hidden` pour laisser
 * l'info-bulle déborder au-dessus de la piste.
 *
 * Glisser-déposer pour ajuster l'horaire (2026-07-30, suite, décision
 * Samuel) : chaque bloc a deux poignées de redimensionnement (bords gauche/
 * droit = début/fin) et se déplace en entier depuis son centre (garde la
 * durée). Horizontal seulement — on ne change pas le jour d'un événement par
 * ce biais, seulement son heure. `dragState` porte le glisser en cours,
 * converti en minutes via `DAY_SPAN_MIN` (2026-08-02, suite : la journée
 * complète fixe, pas la fenêtre zoomée — voir la note sur le défilement
 * horizontal plus bas). Au relâchement (`onDragEnd`) : PATCH `start_datetime`/
 * `end_datetime` pour un spectacle, `scheduled_datetime`/
 * `estimated_duration_minutes` pour un transport, **sans** `force` — en cas
 * de conflit (400), le bloc revient à sa position d'origine (on ne mute
 * jamais `shows`/`transports` directement pendant le glisser, seul un
 * recalcul d'affichage local le simule) et `dragError` affiche le message ;
 * même logique bloquante que le reste de l'app, mais pas de bouton
 * « Forcer » inline ici — l'ajustement fin se fait sur la fiche. Un simple
 * clic sans mouvement navigue toujours vers la fiche (`suppressClick` évite
 * la navigation accidentelle juste après un glisser réel).
 *
 * Contrairement au mockup (fenêtre de temps figée 16h–minuit, conflit
 * détecté par simple chevauchement d'horaire entre deux blocs du même
 * jour), ici : la fenêtre affichée pour « Cette semaine » est calculée
 * dynamiquement à partir des horaires réels de la semaine (avec un peu de
 * marge), et un bloc n'est coloré en conflit que s'il apparaît réellement
 * dans le rapport de conflits du projet (`conflictedShowIds`) — un simple
 * chevauchement horaire entre deux spectacles à des lieux différents et
 * sans ressource partagée n'est PAS un conflit dans cette app (voir
 * architecture.md, section 4d).
 *
 * Zoom (2026-08-02, demande de Samuel) : `weekEntries`/`weekDays` (jours +
 * lanes) sont maintenant calculés INDÉPENDAMMENT de la fenêtre affichée —
 * seule `autoWindow` (la fenêtre event-bounded ci-dessus, désormais isolée
 * dans son propre computed) dépend des vrais horaires. `zoomWindow`
 * restreint optionnellement cette fenêtre (paliers `zoomIn`/`zoomOut`,
 * `ZoomControls.vue`, même composant que les deux écrans Parcours) ;
 * `activeWindow` = `zoomWindow ?? autoWindow` fait foi pour la granularité
 * de l'axe et pour le défilement — PAS pour la position des blocs (voir
 * ci-dessous).
 *
 * Défilement horizontal sous zoom (2026-08-02, suite, demande de Samuel :
 * « se déplacer dans la vue ») : même mécanisme que les deux écrans
 * Parcours (`useZoomScroll.js`) — plutôt que de filtrer/rogner les blocs à
 * la fenêtre active, `weekWindow` positionne maintenant TOUS les blocs de
 * chaque jour relativement à la journée COMPLÈTE fixe (0-1440 min,
 * `DAY_SPAN_MIN`), une fois pour toutes. `.dash-timeline__scroll-content`
 * (axe + pistes des jours) s'élargit à `zoomLevel * 100 %` dans
 * `.dash-timeline__scroll` (`overflow-x: auto`) — `zoomLevel = DAY_SPAN_MIN
 * / activeWindow.span`, donc déjà > 1 par défaut (avant tout clic sur
 * zoom) puisque `autoWindow` est plus étroite que la journée complète.
 * `useZoomScroll` repositionne le défilement (`scrollFraction =
 * activeWindow.start / DAY_SPAN_MIN`) à chaque zoomIn/zoomOut/resetZoom.
 * Les positions `left`/`width` des blocs ne dépendent donc plus JAMAIS du
 * zoom — seule la largeur du conteneur change, exactement comme pour le
 * Parcours Matériel/Technicien. Corollaire : `blockStyle` (aperçu pendant
 * un glisser) et `onDragMove` (conversion pixel → minutes) utilisent
 * maintenant `DAY_SPAN_MIN` directement plutôt que `weekWindow.span` — le
 * `trackWidthPx` mesuré (`getBoundingClientRect`) représente déjà la
 * journée complète à l'échelle du zoom courant.
 *
 * Sous-lignes par lieu (2026-08-02, suite, demande de Samuel) : chaque jour
 * de « Cette semaine » n'est plus UNE piste (avec empilement générique de
 * « voies » en cas de chevauchement, sans indication de quoi est où) —
 * `weekDays` groupe maintenant les entrées du jour PAR LIEU
 * (`venueName`/`originVenueName`/`destinationVenueName`), chaque lieu
 * devenant sa propre sous-ligne avec son propre empilement de voies (utile
 * pour un montage/spectacle/démontage dont les fenêtres effectives se
 * touchent au même lieu). Un lieu sans événement le(s) jour(s) affiché(s)
 * n'a simplement pas d'entrée dans la `Map` — rien à cacher explicitement.
 * Un spectacle a un seul lieu ; un transport relie une origine à une
 * destination et apparaît donc dans les DEUX lignes de lieu correspondantes
 * (décision Samuel — pas de lieu unique à choisir pour un transport), sauf
 * cas limite origine = destination (une seule ligne). Comme un transport
 * peut apparaître deux fois, chaque occurrence est une COPIE indépendante
 * de l'entrée (`{ ...item }` dans `pushTo`) : la voie (`lane`) assignée
 * dans une ligne de lieu ne doit pas écraser celle assignée dans l'autre.
 * Gabarit à deux colonnes inchangé — label et piste gagnent un niveau
 * supplémentaire : un en-tête de jour (`.dash-timeline__day-header`, texte
 * seul) suivi d'une ligne par lieu (`.dash-timeline__venue-label`), avec un
 * espaceur de même hauteur (`.dash-timeline__day-spacer`) côté piste pour
 * garder les deux colonnes alignées, comme `.dash-timeline__labels-spacer`
 * le fait déjà pour l'axe.
 *
 * Filtres jour/lieu (2026-08-02, suite, demande de Samuel) : deux nouvelles
 * rangées de puces (`dayChips`/`venueChips`, `dayFilter`/`venueFilter`,
 * même `useChipFilter` que le filtre de type) au-dessus de la timeline
 * « Cette semaine » — décidé avec Samuel (`AskUserQuestion`) : puces
 * multi-sélection (pas un sélecteur mono-jour façon Parcours), listant
 * SEULEMENT les jours/lieux réellement présents cette semaine (pas la
 * liste complète des lieux du projet), et portée limitée à cette carte —
 * « Spectacles à venir » n'est pas affecté, contrairement au filtre de
 * type qui touche les deux.
 *
 * `availableDays`/`availableVenues` énumèrent les options à partir de
 * `weekEntries` (déjà filtré par type) — AVANT le filtre jour/lieu
 * lui-même, pour que les puces restent stables pendant qu'on filtre (une
 * puce ne disparaît pas parce qu'on vient de cocher une autre puce). Un
 * transport touche DEUX lieux (origine + destination) : il compte pour les
 * deux dans `availableVenues`, et `venueFilter.passes(...)` est vérifié
 * séparément à chaque `pushTo` dans `weekDays` (pas une seule fois par
 * entrée) — si seule l'origine est sélectionnée, le transport reste visible
 * dans la ligne d'origine mais disparaît de la ligne de destination,
 * cohérent avec le fait qu'il y apparaît déjà en double (voir plus haut).
 * `visibleWeekEntries` (jour + lieu, lieu au sens large : au moins UN des
 * deux lieux d'un transport passe) alimente à la fois `weekDays` et
 * `autoWindow` — le zoom « Réinitialiser » se recentre donc automatiquement
 * sur ce qui reste visible après filtrage, pas sur la semaine entière.
 *
 * **Différence assumée avec les Parcours** : le bouton « Réinitialiser »
 * ramène à `autoWindow` (premier événement au dernier ± 30 min), PAS à
 * 0h-24h — sur cet écran, contrairement aux Parcours, la fenêtre par défaut
 * n'a jamais été la journée complète. `zoomOut` peut en revanche aller
 * au-delà d'`autoWindow`, jusqu'à 0h-24h, si on veut voir la journée entière
 * malgré tout. Le zoom ne se réinitialise PAS après un glisser-déposer
 * réussi (`onDragEnd` → `loadDashboard`) — seul un changement de projet le
 * fait : perdre son zoom juste après avoir ajusté un bloc précisément
 * grâce à lui serait contre-productif.
 */

const { activeProjectId } = useActiveProject()

const loading = ref(false)
const loadError = ref(null)
const shows = ref([])
const materials = ref([])
const transports = ref([])
const report = ref({ venue_conflicts: [], material_conflicts: [], technician_conflicts: [], conflict_count: 0 })

async function loadDashboard() {
  if (!activeProjectId.value) return
  loading.value = true
  loadError.value = null
  try {
    const [showsData, materialsData, reportData, transportsData] = await Promise.all([
      api.get('/shows/', { project: activeProjectId.value }),
      api.get('/materials/', { project: activeProjectId.value }),
      api.get(`/projects/${activeProjectId.value}/conflicts/`),
      api.get('/transports/', { project: activeProjectId.value }),
    ])
    shows.value = Array.isArray(showsData) ? showsData : (showsData.results ?? [])
    materials.value = Array.isArray(materialsData) ? materialsData : (materialsData.results ?? [])
    report.value = reportData
    transports.value = Array.isArray(transportsData) ? transportsData : (transportsData.results ?? [])
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

const typeChips = computed(() => {
  const defs = [
    { key: 'performance', label: 'Spectacles' },
    { key: 'rehearsal', label: 'Répétitions' },
    { key: 'storage', label: 'Entreposage' },
    // Blocs rattachés à un événement (2026-07-31) : ce sont des `Show` comme
    // les autres, ils arrivent donc dans la même liste et se filtrent pareil.
    { key: 'setup', label: 'Montages' },
    { key: 'teardown', label: 'Démontages' },
    { key: 'transport', label: 'Transports' },
  ]
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

// --- Cette semaine ---

function startOfWeek(d) {
  const date = new Date(d)
  const day = date.getDay()
  const diff = (day === 0 ? -6 : 1) - day // décale vers lundi
  date.setDate(date.getDate() + diff)
  date.setHours(0, 0, 0, 0)
  return date
}

function endOfWeek(d) {
  const start = startOfWeek(d)
  const end = new Date(start)
  end.setDate(end.getDate() + 6)
  end.setHours(23, 59, 59, 999)
  return end
}

function minutesOfDay(date) {
  return date.getHours() * 60 + date.getMinutes()
}

function fmtMinutes(minutes) {
  const h = Math.floor(minutes / 60)
  const m = Math.round(minutes % 60)
  return `${h}h${m ? String(m).padStart(2, '0') : '00'}`
}

const dayLabelFmt = new Intl.DateTimeFormat('fr-CA', { weekday: 'short', day: 'numeric', month: 'short' })

// Fusionne spectacles et transports en une seule liste d'entrées de la
// semaine — indépendant de la fenêtre affichée (zoomée ou non), pour que
// zoomer/dézoomer ne recalcule jamais quels événements existent, seulement
// comment ils se positionnent.
const weekEntries = computed(() => {
  const weekStart = startOfWeek(new Date())
  const weekEnd = endOfWeek(new Date())
  const entries = []
  for (const show of shows.value) {
    if (!typeFilter.passes(show.event_type)) continue
    const start = new Date(show.start_datetime)
    if (start < weekStart || start > weekEnd) continue
    entries.push({
      kind: 'show',
      id: show.id,
      date: start,
      start,
      end: new Date(show.end_datetime),
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
    if (start < weekStart || start > weekEnd) continue
    const typeLabel = t.transport_type === 'delivery' ? 'Livraison' : 'Ramassage'
    const from = t.origin_venue_code || t.origin_venue_name
    const to = t.destination_venue_code || t.destination_venue_name
    entries.push({
      kind: 'transport',
      id: t.id,
      date: start,
      start,
      end: new Date(t.effective_end),
      name: `${typeLabel} · ${from} → ${to}`,
      status: t.status,
      conflict: !!t.has_technician_conflict,
      technicianName: (t.technician_names ?? []).join(', '),
      materialsSummary: t.is_empty ? 'Camion vide' : `${(t.materials ?? []).length} article(s)`,
      // Noms complets (pas les codes utilisés dans `name` ci-dessus) : ce
      // sont les clés de regroupement par lieu (voir `weekDays`).
      originVenueName: t.origin_venue_name,
      destinationVenueName: t.destination_venue_name,
      route: `/transports/${t.id}`,
    })
  }
  return entries
})

// Options des puces jour/lieu : seulement ce qui est réellement présent
// cette semaine (après filtre de type, AVANT le filtre jour/lieu lui-même —
// une puce ne doit pas disparaître parce qu'on vient d'en cocher une autre).
const availableDays = computed(() => {
  const map = new Map()
  for (const entry of weekEntries.value) {
    const key = entry.date.toDateString()
    if (!map.has(key)) map.set(key, entry.date)
  }
  return [...map.entries()]
    .sort((a, b) => a[1] - b[1])
    .map(([key, date]) => ({ key, label: dayLabelFmt.format(date) }))
})

const dayChips = computed(() => [
  { label: 'Tous', active: dayFilter.selected.value.size === 0, select: () => dayFilter.selectAll() },
  ...availableDays.value.map((d) => ({
    label: d.label,
    active: dayFilter.isSelected(d.key),
    select: (event) => dayFilter.toggle(d.key, event),
  })),
])

// Un transport touche deux lieux (origine + destination) : il compte pour
// les deux ici, même s'il n'apparaîtra en double dans la timeline que si les
// deux passent le filtre (voir `pushTo` dans `weekDays`).
const availableVenues = computed(() => {
  const set = new Set()
  for (const entry of weekEntries.value) {
    if (entry.kind === 'show') {
      if (entry.venueName) set.add(entry.venueName)
    } else {
      if (entry.originVenueName) set.add(entry.originVenueName)
      if (entry.destinationVenueName) set.add(entry.destinationVenueName)
    }
  }
  return [...set].sort((a, b) => a.localeCompare(b, 'fr'))
})

const venueChips = computed(() => [
  { label: 'Tous', active: venueFilter.selected.value.size === 0, select: () => venueFilter.selectAll() },
  ...availableVenues.value.map((name) => ({
    label: name,
    active: venueFilter.isSelected(name),
    select: (event) => venueFilter.toggle(name, event),
  })),
])

const hasAnyEntriesThisWeek = computed(() => weekEntries.value.length > 0)

// Entrées qui passent le filtre jour ET (au sens large pour un transport :
// au moins UN des deux lieux) le filtre lieu — alimente `weekDays` ET
// `autoWindow`, pour que le zoom « Réinitialiser » se recentre sur ce qui
// reste visible après filtrage plutôt que sur la semaine entière.
const visibleWeekEntries = computed(() => weekEntries.value.filter((entry) => {
  if (!dayFilter.passes(entry.date.toDateString())) return false
  if (entry.kind === 'show') return venueFilter.passes(entry.venueName)
  return venueFilter.passes(entry.originVenueName) || venueFilter.passes(entry.destinationVenueName)
}))

const LANE_HEIGHT = 34

// Empile les entrées qui se chevauchent en « voies » (lane 0, 1, 2…) et
// renvoie la hauteur de piste correspondante — factorisé pour être appliqué
// PAR LIEU (voir `weekDays` ci-dessous) plutôt qu'une seule fois par jour.
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

// Groupement par jour PUIS par lieu à l'intérieur du jour (2026-08-02, suite,
// demande de Samuel) — chaque lieu devient sa propre sous-ligne, avec son
// propre empilement de voies. Un lieu sans événement le(s) jour(s) affiché(s)
// n'a simplement pas d'entrée dans la Map — rien à cacher explicitement.
// Indépendant du zoom, comme avant : la hauteur d'une piste et la ligne
// verticale d'un bloc ne doivent pas sauter en zoomant.
//
// Source `visibleWeekEntries` (2026-08-02, suite) plutôt que `weekEntries` :
// le filtre jour est déjà appliqué à ce stade (voir sa définition), le
// filtre lieu est réappliqué plus finement ci-dessous (par lieu, pas par
// entrée entière) pour qu'un transport partiellement filtré (un seul de ses
// deux lieux sélectionné) ne perde que la ligne correspondante.
const weekDays = computed(() => {
  const byDay = new Map()
  for (const entry of visibleWeekEntries.value) {
    const key = entry.date.toDateString()
    const startMin = minutesOfDay(entry.start)
    const endMin = Math.max(startMin + 15, minutesOfDay(entry.end)) // évite une largeur nulle si même heure
    if (!byDay.has(key)) byDay.set(key, { date: entry.date, items: [] })
    byDay.get(key).items.push({ ...entry, start: startMin, end: endMin })
  }
  return [...byDay.values()]
    .sort((a, b) => a.date - b.date)
    .map(({ date, items }) => {
      const byVenue = new Map()
      // Copie l'entrée (`{ ...item }`) plutôt que de partager la référence :
      // un transport peut être poussé dans DEUX lieux (origine +
      // destination), chacun avec sa propre voie (`lane`) assignée par
      // `packLanes` — muter la même référence deux fois écraserait la
      // première assignation.
      const pushTo = (venueName, item) => {
        if (!venueName) return
        if (!venueFilter.passes(venueName)) return
        if (!byVenue.has(venueName)) byVenue.set(venueName, [])
        byVenue.get(venueName).push({ ...item })
      }
      for (const it of items) {
        if (it.kind === 'show') {
          pushTo(it.venueName, it)
        } else if (it.originVenueName === it.destinationVenueName) {
          // Cas limite (théoriquement invalide côté métier) : une seule ligne.
          pushTo(it.originVenueName, it)
        } else {
          pushTo(it.originVenueName, it)
          pushTo(it.destinationVenueName, it)
        }
      }
      const venues = [...byVenue.entries()]
        .map(([venueName, venueItems]) => {
          const { items: sorted, rowHeight } = packLanes(venueItems)
          return { venueName, items: sorted, rowHeight }
        })
        // Le lieu qui démarre le plus tôt ce jour-là en premier — ordre
        // cohérent avec le tri chronologique des jours eux-mêmes.
        .sort((a, b) => a.items[0].start - b.items[0].start)
      return { date, label: dayLabelFmt.format(date), venues }
    })
    .filter((day) => day.venues.length > 0)
})

// Fenêtre AUTOMATIQUE : du premier au dernier événement VISIBLE (jour/lieu
// filtrés, 2026-08-02, suite) de la semaine, ±30 min de marge — c'est la
// fenêtre par défaut (zoom non actif) ET ce que cible le bouton
// Réinitialiser, PAS 0h-24h (voir la note de tête du module).
const autoWindow = computed(() => {
  const entries = visibleWeekEntries.value
  if (entries.length === 0) return null
  let winStart = 24 * 60
  let winEnd = 0
  for (const entry of entries) {
    const startMin = minutesOfDay(entry.start)
    const endMin = Math.max(startMin + 15, minutesOfDay(entry.end))
    winStart = Math.min(winStart, startMin)
    winEnd = Math.max(winEnd, endMin)
  }
  winStart = Math.max(0, winStart - 30)
  winEnd = Math.min(24 * 60, winEnd + 30)
  return { start: winStart, end: winEnd, span: winEnd - winStart || 1 }
})

// --- Zoom (2026-08-02, demande de Samuel) ---

const DAY_SPAN_MIN = 24 * 60
const ZOOM_FACTOR = 0.6
const MIN_ZOOM_SPAN_MIN = 15

// { start, end, span } en minutes de la journée, ou `null` = fenêtre
// automatique (`autoWindow`). Contrairement à `useParcours.js`, `null` NE
// représente PAS 0h-24h ici — c'est pourquoi `zoomOut` ne retombe jamais sur
// `null` en approchant la journée complète (seul `resetZoom` le fait).
const zoomWindow = ref(null)

function clampWindow(start, span) {
  const clampedSpan = Math.min(Math.max(span, MIN_ZOOM_SPAN_MIN), DAY_SPAN_MIN)
  const clampedStart = Math.max(0, Math.min(DAY_SPAN_MIN - clampedSpan, start))
  return { start: clampedStart, end: clampedStart + clampedSpan, span: clampedSpan }
}

const activeWindow = computed(() => zoomWindow.value ?? autoWindow.value)
const isZoomed = computed(() => zoomWindow.value != null)
const canZoomIn = computed(() => !!activeWindow.value && activeWindow.value.span > MIN_ZOOM_SPAN_MIN + 0.5)
const canZoomOut = computed(() => !!activeWindow.value && activeWindow.value.span < DAY_SPAN_MIN - 0.5)

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

// zoomLevel/scrollFraction (2026-08-02, suite) : mêmes formules que
// `useParcours.js`, voir la note de tête sur le défilement horizontal.
const zoomLevel = computed(() => {
  if (!activeWindow.value) return 1
  return DAY_SPAN_MIN / activeWindow.value.span
})

const scrollFraction = computed(() => {
  if (!activeWindow.value) return 0
  return activeWindow.value.start / DAY_SPAN_MIN
})

const scrollRef = ref(null)
useZoomScroll(scrollRef, zoomLevel, scrollFraction)

// --- Cette semaine : rendu ---
//
// Les positions des blocs (left/width) sont TOUJOURS relatives à la journée
// complète (0-1440 min) — jamais à la fenêtre zoomée, voir la note de tête.
// Seule la graduation de l'axe (densité des repères) dépend de la fenêtre
// active, pour rester lisible à n'importe quel niveau de zoom.
const weekWindow = computed(() => {
  if (weekEntries.value.length === 0 || !activeWindow.value) return { days: [], hasEntries: false, hourMarks: [] }
  const span = activeWindow.value.span

  const step = span <= 60 ? 10 : span <= 180 ? 15 : span <= 360 ? 30 : span <= 720 ? 60 : 120
  const hourMarks = []
  for (let m = 0; m <= DAY_SPAN_MIN; m += step) {
    hourMarks.push({ minute: m, label: fmtMinutes(m), left: `${(m / DAY_SPAN_MIN) * 100}%` })
  }

  const days = weekDays.value.map((day) => {
    const venues = day.venues.map((venue) => {
      const blocks = []
      for (const it of venue.items) {
        const left = (it.start / DAY_SPAN_MIN) * 100
        const width = (Math.max(it.end - it.start, 1) / DAY_SPAN_MIN) * 100

        // Rouge = conflit (chevauchement réel, spectacle ou technicien de
        // transport). Sinon : vert pour un spectacle, fuchsia pour un
        // transport confirmé (`--transport`, 2026-08-02 — était `--accent`,
        // se confondait avec des couleurs de lieu mauve du Parcours sous le
        // thème clair), orange pour une proposition à approuver — mêmes
        // couleurs de statut que TransportsView.vue.
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
          // Bloc rattaché (montage/démontage, 2026-07-31) : teinte plus
          // sourde que l'événement qu'il encadre, pour lire la séquence
          // montage → spectacle → démontage d'un coup d'œil.
          color = it.typeColor
          textColor = 'rgba(var(--fg-rgb),.9)'
        }
        // Lignes de détail pour l'info-bulle au survol — voir note du module.
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

        blocks.push({
          id: it.id,
          kind: it.kind,
          dayDate: day.date,
          startMin: it.start,
          endMin: it.end,
          left: `${left}%`,
          width: `${width}%`,
          top: `${it.lane * LANE_HEIGHT}px`,
          name: it.name,
          time: `${fmtMinutes(it.start)}–${fmtMinutes(it.end)}`,
          color,
          textColor,
          details,
          route: it.route,
        })
      }
      return { venueName: venue.venueName, blocks, rowHeight: venue.rowHeight }
    })
    return { label: day.label, venues }
  })

  return { days, hasEntries: days.length > 0, hourMarks }
})

// --- Glisser-déposer pour ajuster l'horaire (voir note du module) ---

const MIN_DURATION_MINUTES = 15

// { kind, id, mode: 'move'|'resize-start'|'resize-end', dayDate,
//   originStartMin, originEndMin, startMin, endMin, pointerStartX, trackWidthPx }
const dragState = ref(null)
const dragError = ref(null)
let suppressClick = false

function minutesToDate(dayDate, minutes) {
  const d = new Date(dayDate)
  d.setHours(0, Math.round(minutes), 0, 0)
  return d
}

function blockStyle(block) {
  const state = dragState.value
  if (state && state.kind === block.kind && state.id === block.id) {
    // Relatif à la journée complète, comme le rendu normal — voir la note
    // de tête sur le défilement horizontal sous zoom.
    return {
      top: block.top,
      left: `${(state.startMin / DAY_SPAN_MIN) * 100}%`,
      width: `${((state.endMin - state.startMin) / DAY_SPAN_MIN) * 100}%`,
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
    return `${fmtMinutes(state.startMin)}–${fmtMinutes(state.endMin)}`
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
    dayDate: block.dayDate,
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
  // trackWidthPx représente toujours la journée complète (0-1440 min) à
  // l'échelle du zoom courant — voir la note de tête.
  const deltaMin = (deltaPx / state.trackWidthPx) * DAY_SPAN_MIN

  let newStart = state.originStartMin
  let newEnd = state.originEndMin
  if (state.mode === 'move') {
    const duration = state.originEndMin - state.originStartMin
    newStart = Math.max(0, Math.min(1440 - duration, state.originStartMin + deltaMin))
    newEnd = newStart + duration
  } else if (state.mode === 'resize-start') {
    newStart = Math.max(0, Math.min(state.originEndMin - MIN_DURATION_MINUTES, state.originStartMin + deltaMin))
  } else {
    newEnd = Math.min(1440, Math.max(state.originStartMin + MIN_DURATION_MINUTES, state.originEndMin + deltaMin))
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
  const newStart = minutesToDate(state.dayDate, state.startMin)
  const newEnd = minutesToDate(state.dayDate, state.endMin)
  try {
    if (state.kind === 'show') {
      await api.patch(`/shows/${state.id}/`, {
        start_datetime: newStart.toISOString(),
        end_datetime: newEnd.toISOString(),
      })
    } else {
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
      const timeRange = `${fmtMinutes(minutesOfDay(start))}–${fmtMinutes(minutesOfDay(end))}`
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

      <div class="filters">
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
          <div class="dash-card__title">Cette semaine</div>
          <ZoomControls
            v-if="weekWindow.hasEntries"
            :is-zoomed="isZoomed"
            :can-zoom-in="canZoomIn"
            :can-zoom-out="canZoomOut"
            @zoom-in="zoomIn"
            @zoom-out="zoomOut"
            @reset="resetZoom"
          />
        </div>
        <div v-if="hasAnyEntriesThisWeek" class="dash-timeline-filters">
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
          <div class="dash-timeline-filters__row">
            <span class="dash-timeline-filters__label">Lieu</span>
            <div
              v-for="f in venueChips"
              :key="'venue-' + f.label"
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
        <div v-if="weekWindow.hasEntries" class="dash-timeline">
          <div class="dash-timeline__labels">
            <div class="dash-timeline__labels-spacer" />
            <template v-for="day in weekWindow.days" :key="'daylabel-' + day.label">
              <div class="dash-timeline__day-header">{{ day.label }}</div>
              <div
                v-for="venue in day.venues"
                :key="'venuelabel-' + day.label + '-' + venue.venueName"
                class="dash-timeline__venue-label"
                :style="{ height: venue.rowHeight }"
              >{{ venue.venueName }}</div>
            </template>
          </div>

          <div ref="scrollRef" class="dash-timeline__scroll">
            <div class="dash-timeline__scroll-content" :style="{ width: `${zoomLevel * 100}%` }">
              <div class="dash-timeline__axis">
                <span
                  v-for="mark in weekWindow.hourMarks"
                  :key="mark.minute"
                  class="dash-timeline__axis-mark"
                  :style="{ left: mark.left }"
                >{{ mark.label }}</span>
              </div>
              <template v-for="day in weekWindow.days" :key="'daytrack-' + day.label">
                <div class="dash-timeline__day-spacer" />
                <div
                  v-for="venue in day.venues"
                  :key="'venuetrack-' + day.label + '-' + venue.venueName"
                  class="dash-timeline__track"
                  :style="{ height: venue.rowHeight }"
                >
                  <div
                    v-for="mark in weekWindow.hourMarks"
                    :key="'grid-' + mark.minute"
                    class="dash-timeline__gridline"
                    :style="{ left: mark.left }"
                  />
                  <div
                    v-for="block in venue.blocks"
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
              </template>
            </div>
          </div>
        </div>
        <div v-else-if="hasAnyEntriesThisWeek" class="row-empty">Aucun événement ne correspond aux filtres jour/lieu sélectionnés.</div>
        <div v-else class="row-empty">Aucun spectacle ni transport cette semaine.</div>
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

.filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
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

/* Sous-lignes par lieu (2026-08-02, suite, demande de Samuel) : chaque jour
   est maintenant un en-tête (`.dash-timeline__day-header`, texte seul) suivi
   d'une ligne par lieu (`.dash-timeline__venue-label`, indentée pour montrer
   la hiérarchie). Côté piste, `.dash-timeline__day-spacer` occupe la même
   hauteur que l'en-tête pour garder les deux colonnes alignées — même
   principe que `.dash-timeline__labels-spacer` pour l'axe. */
.dash-timeline__day-header {
  display: flex;
  align-items: flex-end;
  height: 22px;
  box-sizing: border-box;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--border-card);
  font: 700 11px system-ui;
  color: rgba(var(--fg-rgb), 0.7);
}

.dash-timeline__day-spacer {
  height: 22px;
  box-sizing: border-box;
  border-bottom: 1px solid var(--border-card);
}

.dash-timeline__venue-label {
  display: flex;
  align-items: center;
  padding-left: 10px;
  font: 500 11.5px system-ui;
  color: rgba(var(--fg-rgb), 0.5);
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
   en plus de sa couleur (lavande/orange/rouge — voir weekWindow). */
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

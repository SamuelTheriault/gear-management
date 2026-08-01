<script setup>
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppShell from '../components/AppShell.vue'
import { api } from '../api/client'
import { useActiveProject } from '../composables/useActiveProject'

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
 * Filtre de type (2026-07-30, suite) : puces « Spectacles/Répétitions/
 * Entreposage/Transports » en haut de page (`typeFilters`/`typeChips`),
 * bascule indépendante par type (pas un select unique) — s'applique à la
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
 * converti en minutes via `weekWindow.winStart`/`span` (mêmes valeurs que le
 * rendu normal). Au relâchement (`onDragEnd`) : PATCH `start_datetime`/
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
// on doit voir d'un coup d'œil que la salle est occupée avant et après.
const typeColors = {
  setup: 'oklch(0.5 0.1 165)',
  teardown: 'oklch(0.46 0.08 255)',
}

// --- Filtre de catégories (2026-07-30, suite) ---
// Filtre les types d'entrées affichées dans la timeline « Cette semaine » et
// dans « Spectacles à venir » — les 3 event_type de Show (Spectacle/
// Répétition/Entreposage) plus Transport (n'apparaît que dans la timeline).
// Bascule indépendante par type (pas un select unique façon MaterielView) :
// on veut pouvoir combiner librement, ex. cacher les répétitions tout en
// gardant spectacles + transports visibles.
const typeFilters = ref({
  performance: true,
  rehearsal: true,
  storage: true,
  // Blocs rattachés à un événement (2026-07-31) : ce sont des `Show` comme
  // les autres, ils arrivent donc dans la même liste et se filtrent pareil.
  setup: true,
  teardown: true,
  transport: true,
})

const typeChips = computed(() => {
  const defs = [
    { key: 'performance', label: 'Spectacles' },
    { key: 'rehearsal', label: 'Répétitions' },
    { key: 'storage', label: 'Entreposage' },
    { key: 'setup', label: 'Montages' },
    { key: 'teardown', label: 'Démontages' },
    { key: 'transport', label: 'Transports' },
  ]
  const allActive = defs.every((d) => typeFilters.value[d.key])
  return [
    {
      label: 'Tous',
      active: allActive,
      select: () => defs.forEach((d) => { typeFilters.value[d.key] = true }),
    },
    ...defs.map((d) => ({
      label: d.label,
      active: typeFilters.value[d.key],
      select: () => { typeFilters.value[d.key] = !typeFilters.value[d.key] },
    })),
  ]
})

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

const weekWindow = computed(() => {
  const weekStart = startOfWeek(new Date())
  const weekEnd = endOfWeek(new Date())

  // Fusionne spectacles et transports en une seule liste d'entrées avant de
  // répartir par jour, pour que les deux partagent la même fenêtre horaire
  // et le même algorithme d'attribution de « voie » (évite le chevauchement
  // visuel entre un bloc spectacle et un bloc transport le même jour).
  const weekEntries = []
  for (const show of shows.value) {
    if (!typeFilters.value[show.event_type]) continue
    const start = new Date(show.start_datetime)
    if (start < weekStart || start > weekEnd) continue
    weekEntries.push({
      kind: 'show',
      id: show.id,
      date: start,
      start,
      end: new Date(show.end_datetime),
      name: show.title,
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
    if (!typeFilters.value.transport) continue
    // Une proposition auto non complétée (to_approve sans heure) n'a pas de
    // fenêtre exploitable — voir Transport.effective_end côté backend.
    if (!t.scheduled_datetime || !t.effective_end) continue
    const start = new Date(t.scheduled_datetime)
    if (start < weekStart || start > weekEnd) continue
    const typeLabel = t.transport_type === 'delivery' ? 'Livraison' : 'Ramassage'
    const from = t.origin_venue_code || t.origin_venue_name
    const to = t.destination_venue_code || t.destination_venue_name
    weekEntries.push({
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
      route: `/transports/${t.id}`,
    })
  }

  if (weekEntries.length === 0) return { days: [], hasEntries: false, hourMarks: [], winStart: 0, span: 1 }

  let winStart = 24 * 60
  let winEnd = 0
  const byDay = new Map()
  for (const entry of weekEntries) {
    const key = entry.date.toDateString()
    const startMin = minutesOfDay(entry.start)
    const endMin = Math.max(startMin + 15, minutesOfDay(entry.end)) // évite une largeur nulle si même heure
    winStart = Math.min(winStart, startMin)
    winEnd = Math.max(winEnd, endMin)
    if (!byDay.has(key)) byDay.set(key, { date: entry.date, items: [] })
    // On garde toute l'entrée (id/route/venueName/technicianName/…) pour
    // construire l'info-bulle et le lien de navigation plus bas — seuls
    // `start`/`end` sont remplacés par leurs équivalents en minutes.
    byDay.get(key).items.push({ ...entry, start: startMin, end: endMin })
  }
  winStart = Math.max(0, winStart - 30)
  winEnd = Math.min(24 * 60, winEnd + 30)
  const span = winEnd - winStart || 1

  // Graduation adaptative : plus la fenêtre est large, plus l'écart entre
  // les repères d'heure augmente, pour éviter que les libellés se chevauchent.
  const step = span <= 240 ? 30 : span <= 720 ? 60 : 120
  const hourMarks = []
  for (let m = Math.ceil(winStart / step) * step; m <= winEnd; m += step) {
    hourMarks.push({ minute: m, label: fmtMinutes(m), left: `${((m - winStart) / span) * 100}%` })
  }

  const days = [...byDay.values()]
    .sort((a, b) => a.date - b.date)
    .map(({ date, items }) => {
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
      const blocks = sorted.map((it) => {
        // Rouge = conflit (chevauchement réel, spectacle ou technicien de
        // transport). Sinon : vert pour un spectacle, lavande pour un
        // transport confirmé, orange pour une proposition à approuver —
        // mêmes couleurs de statut que TransportsView.vue.
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
            color = 'var(--accent)'
            textColor = '#211c33'
          }
        } else if (it.typeColor) {
          // Bloc rattaché (montage/démontage, 2026-07-31) : teinte plus
          // sourde que l'événement qu'il encadre, pour lire la séquence
          // montage → spectacle → démontage d'un coup d'œil.
          color = it.typeColor
          textColor = 'rgba(255,255,255,.9)'
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

        return {
          id: it.id,
          kind: it.kind,
          dayDate: date,
          startMin: it.start,
          endMin: it.end,
          left: `${((it.start - winStart) / span) * 100}%`,
          width: `${((it.end - it.start) / span) * 100}%`,
          top: `${it.lane * 34}px`,
          name: it.name,
          time: `${fmtMinutes(it.start)}–${fmtMinutes(it.end)}`,
          color,
          textColor,
          details,
          route: it.route,
        }
      })
      return { label: dayLabelFmt.format(date), blocks, rowHeight: `${laneEnds.length * 34 - 4}px` }
    })

  return { days, hasEntries: true, hourMarks, winStart, span }
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
    const { winStart, span } = weekWindow.value
    return {
      top: block.top,
      left: `${((state.startMin - winStart) / span) * 100}%`,
      width: `${((state.endMin - state.startMin) / span) * 100}%`,
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
  const { span } = weekWindow.value
  const deltaMin = (deltaPx / state.trackWidthPx) * span

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
    .filter((s) => new Date(s.end_datetime) >= now && typeFilters.value[s.event_type])
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
        title: `${s.title} — ${typeSuffix[s.event_type] ?? s.event_type}`,
        venue: s.venue_name,
        time: isToday ? timeRange : `${dayLabelFmt.format(start)} ${timeRange}`,
        conflict,
        rowBg: conflict ? 'oklch(0.27 0.07 35 / .5)' : '#1b1f25',
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
          @click="f.select"
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
        <div class="dash-card__title">Cette semaine</div>
        <div v-if="dragError" class="dash-drag-error">
          {{ dragError }}
          <span class="dash-drag-error__dismiss" @click="dragError = null">✕</span>
        </div>
        <div v-if="weekWindow.hasEntries" class="dash-timeline">
          <div class="dash-timeline__row dash-timeline__row--axis">
            <div class="dash-timeline__label"></div>
            <div class="dash-timeline__axis">
              <span
                v-for="mark in weekWindow.hourMarks"
                :key="mark.minute"
                class="dash-timeline__axis-mark"
                :style="{ left: mark.left }"
              >{{ mark.label }}</span>
            </div>
          </div>
          <div v-for="day in weekWindow.days" :key="day.label" class="dash-timeline__row">
            <div class="dash-timeline__label">{{ day.label }}</div>
            <div class="dash-timeline__track" :style="{ height: day.rowHeight }">
              <div
                v-for="mark in weekWindow.hourMarks"
                :key="'grid-' + mark.minute"
                class="dash-timeline__gridline"
                :style="{ left: mark.left }"
              />
              <div
                v-for="block in day.blocks"
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
  color: rgba(255, 255, 255, 0.5);
}

.hint--error {
  color: oklch(0.78 0.16 35);
}

.row-empty {
  font: 500 12.5px system-ui;
  color: rgba(255, 255, 255, 0.4);
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
  color: rgba(255, 255, 255, 0.4);
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
  color: rgba(255, 255, 255, 0.65);
  margin-bottom: 16px;
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

.dash-timeline {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.dash-timeline__row {
  display: grid;
  grid-template-columns: 140px 1fr;
  gap: 12px;
  align-items: center;
}

.dash-timeline__label {
  font: 600 12px system-ui;
  color: rgba(255, 255, 255, 0.55);
}

.dash-timeline__row--axis {
  margin-bottom: -4px;
}

.dash-timeline__axis {
  position: relative;
  height: 16px;
}

.dash-timeline__axis-mark {
  position: absolute;
  transform: translateX(-50%);
  font: 600 9.5px var(--font-mono);
  color: rgba(255, 255, 255, 0.35);
  white-space: nowrap;
}

.dash-timeline__track {
  position: relative;
  background: #1b1f25;
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
  background: #0e1013;
  border: 1px solid rgba(255, 255, 255, 0.12);
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
  color: #fff;
  white-space: normal;
  margin-bottom: 4px;
}

.dash-timeline__tooltip-time {
  font: 600 11px system-ui;
  color: rgba(255, 255, 255, 0.55);
  margin-bottom: 6px;
}

.dash-timeline__tooltip-line {
  font: 500 11.5px system-ui;
  color: rgba(255, 255, 255, 0.75);
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
  color: rgba(255, 255, 255, 0.45);
}

.dash-legend__item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.dash-legend__item--hint {
  margin-left: auto;
  color: rgba(255, 255, 255, 0.3);
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
  background: var(--accent);
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
  color: #fff;
}

.dash-stat__value--accent {
  color: oklch(0.72 0.16 35);
}

.dash-stat__label {
  font: 500 12px system-ui;
  color: rgba(255, 255, 255, 0.5);
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
  color: #fff;
}

.dash-upcoming__subtitle {
  font: 400 11.5px system-ui;
  color: rgba(255, 255, 255, 0.5);
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

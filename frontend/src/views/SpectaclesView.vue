<script setup>
import { ref, computed, watch } from 'vue'
import AppShell from '../components/AppShell.vue'
import { api } from '../api/client'
import { useActiveProject } from '../composables/useActiveProject'
import { useChipFilter } from '../composables/useChipFilter'
import { EVENT_TYPE_META } from '../constants/eventTypeMeta'

/**
 * Liste des spectacles — port de Spectacles.dc.html, branché sur l'API réelle
 * (/api/shows/, /api/venues/) plutôt que sur les données de démonstration du
 * prototype. Voir schema.md section 5 pour les champs de `Show`.
 *
 * Filtre « Jour » (2026-08-02, demande de Samuel) : réutilise `s.date` (déjà
 * calculé), trié chronologiquement par `start_datetime` — pas de bucket
 * « À planifier » à gérer ici, contrairement à Transports, `start_datetime`
 * étant obligatoire sur `Show`. Voir la note dédiée dans CLAUDE.md.
 */

const { activeProjectId } = useActiveProject()

const shows = ref([])
const venues = ref([])
const loading = ref(false)
const loadError = ref(null)

// Couleurs personnalisables depuis Réglages (2026-08-02) — voir
// constants/eventTypeMeta.js, source unique partagée avec SpectacleDetailView.vue,
// MaterielDetailView.vue et DashboardView.vue.
const typeMeta = EVENT_TYPE_META

const dateFmt = new Intl.DateTimeFormat('fr-CA', { weekday: 'short', day: 'numeric', month: 'short' })
const timeFmt = new Intl.DateTimeFormat('fr-CA', { hour: '2-digit', minute: '2-digit', hour12: false })

function formatRange(startIso, endIso) {
  const start = new Date(startIso)
  const end = new Date(endIso)
  return {
    date: dateFmt.format(start),
    time: `${timeFmt.format(start)}–${timeFmt.format(end)}`,
  }
}

async function loadShows() {
  if (!activeProjectId.value) return
  loading.value = true
  loadError.value = null
  try {
    const [showsData, venuesData] = await Promise.all([
      api.get('/shows/', { project: activeProjectId.value }),
      api.get('/venues/', { project: activeProjectId.value }),
    ])
    const rawShows = Array.isArray(showsData) ? showsData : (showsData.results ?? [])
    venues.value = Array.isArray(venuesData) ? venuesData : (venuesData.results ?? [])

    // Conflit = un chevauchement (lieu, matériel ou technicien) toujours en
    // place sur ce spectacle — voir GET /api/shows/{id}/conflicts/. Un appel
    // par spectacle ; le volume typique (quelques dizaines/mois) reste léger.
    const withConflicts = await Promise.all(
      rawShows.map(async (s) => {
        try {
          const c = await api.get(`/shows/${s.id}/conflicts/`)
          const conflict =
            (c.venue_conflicts?.length ?? 0) +
              (c.material_conflicts?.length ?? 0) +
              (c.technician_conflicts?.length ?? 0) >
            0
          return { ...s, conflict }
        } catch {
          return { ...s, conflict: false }
        }
      }),
    )
    shows.value = withConflicts
  } catch (e) {
    loadError.value = e
  } finally {
    loading.value = false
  }
}

watch(activeProjectId, loadShows, { immediate: true })

const decorated = computed(() =>
  shows.value.map((s) => {
    const meta = typeMeta[s.event_type] ?? typeMeta.performance
    const { date, time } = formatRange(s.start_datetime, s.end_datetime)
    return {
      ...s,
      date,
      time,
      typeLabel: meta.label,
      typeColor: meta.color,
      typeBg: meta.bg,
      dot: s.conflict ? 'oklch(0.7 0.16 35)' : meta.dot,
    }
  }),
)

// ⌘+clic pour combiner plusieurs valeurs (2026-08-01, à la demande de
// Samuel — même comportement que toutes les puces de filtre de l'app, voir
// useChipFilter.js). Trois groupes indépendants (jour, type, lieu), combinés
// en ET.
const dayFilter = useChipFilter()
const typeFilter = useChipFilter()
const venueFilter = useChipFilter()

// Options de jour (2026-08-02, demande de Samuel) : `start_datetime` est
// obligatoire sur `Show` (pas de bucket « À planifier » à gérer, contrairement
// à Transport), donc un simple tri chronologique par première occurrence.
const dayOptions = computed(() => {
  const byLabel = new Map()
  decorated.value.forEach((s) => {
    if (!byLabel.has(s.date)) byLabel.set(s.date, new Date(s.start_datetime))
  })
  return [...byLabel.entries()].sort(([, a], [, b]) => a - b).map(([label]) => label)
})

const dayFilters = computed(() => [
  { label: 'Tous les jours', active: dayFilter.selected.value.size === 0, select: () => dayFilter.selectAll() },
  ...dayOptions.value.map((d) => ({
    label: d,
    active: dayFilter.isSelected(d),
    select: (event) => dayFilter.toggle(d, event),
  })),
])

const typeFilters = computed(() => [
  { label: 'Tous', active: typeFilter.selected.value.size === 0, select: () => typeFilter.selectAll() },
  ...['Répétition', 'Représentation', 'Entreposage', 'Montage', 'Démontage'].map((label) => ({
    label,
    active: typeFilter.isSelected(label),
    select: (event) => typeFilter.toggle(label, event),
  })),
])

const venueOptions = computed(() => {
  const seen = new Map()
  decorated.value.forEach((s) => {
    if (s.venue) seen.set(s.venue, s.venue_name)
  })
  return [...seen.entries()].map(([id, name]) => ({ id, name }))
})

const venueFilters = computed(() => [
  { label: 'Tous les lieux', active: venueFilter.selected.value.size === 0, select: () => venueFilter.selectAll() },
  ...venueOptions.value.map((v) => ({
    label: v.name,
    active: venueFilter.isSelected(v.id),
    select: (event) => venueFilter.toggle(v.id, event),
  })),
])

const matching = computed(() =>
  decorated.value.filter(
    (s) => dayFilter.passes(s.date) && typeFilter.passes(s.typeLabel) && venueFilter.passes(s.venue),
  ),
)

/**
 * Regroupe les blocs rattachés (montage/démontage/répétition liée, voir
 * `Show.parent_show`, 2026-07-31) sous leur événement principal, en retrait —
 * même lecture que les composants d'un kit dans l'inventaire.
 *
 * Un bloc dont l'événement est masqué par un filtre reste affiché au premier
 * niveau, plutôt que de disparaître silencieusement.
 */
const filtered = computed(() => {
  const liste = matching.value
  const visibles = new Set(liste.map((s) => s.id))

  const enfants = new Map()
  liste.forEach((s) => {
    if (s.parent_show == null || !visibles.has(s.parent_show)) return
    if (!enfants.has(s.parent_show)) enfants.set(s.parent_show, [])
    enfants.get(s.parent_show).push(s)
  })

  const ordonne = []
  liste.forEach((s) => {
    if (s.parent_show != null && visibles.has(s.parent_show)) return
    ordonne.push({ ...s, nested: false })
    ;(enfants.get(s.id) ?? [])
      .sort((a, b) => new Date(a.start_datetime) - new Date(b.start_datetime))
      .forEach((child) => ordonne.push({ ...child, nested: true }))
  })
  return ordonne
})

// --- Ajout rapide d'un spectacle ---

const eventTypeOptions = [
  { value: 'rehearsal', label: 'Répétition' },
  { value: 'performance', label: 'Représentation' },
  { value: 'storage', label: 'Entreposage' },
]

const form = ref({
  title: '',
  venue: '',
  event_type: 'performance',
  start: '',
  end: '',
})
const formError = ref(null)
// venue/start_datetime/end_datetime sont obligatoires côté modèle (Show,
// models.py) — pas nullables. Le prototype laissait ces champs libres ; on
// valide donc les trois ici plutôt que de laisser l'API renvoyer un 400 générique.
const fieldErrors = ref({ title: false, venue: false, start: false, end: false })
const conflictDetail = ref(null)
const submitting = ref(false)

const canSubmit = computed(() => form.value.title.trim().length > 0 && !submitting.value)

function validateForm() {
  const errors = {
    title: !form.value.title.trim(),
    venue: !form.value.venue,
    start: !form.value.start,
    end: !form.value.end,
  }
  fieldErrors.value = errors
  if (!errors.start && !errors.end && new Date(form.value.end) <= new Date(form.value.start)) {
    errors.end = true
    fieldErrors.value = errors
    formError.value = 'La fin doit être après le début.'
    return false
  }
  return !Object.values(errors).some(Boolean)
}

async function submitShow(force = false) {
  formError.value = null
  conflictDetail.value = null
  if (!validateForm()) return

  submitting.value = true
  try {
    await api.post('/shows/', {
      project: activeProjectId.value,
      title: form.value.title.trim(),
      venue: form.value.venue,
      event_type: form.value.event_type,
      start_datetime: new Date(form.value.start).toISOString(),
      end_datetime: new Date(form.value.end).toISOString(),
      force,
    })
    form.value = { title: '', venue: '', event_type: 'performance', start: '', end: '' }
    fieldErrors.value = { title: false, venue: false, start: false, end: false }
    await loadShows()
  } catch (e) {
    if (e.data?.conflicts) {
      conflictDetail.value = e.data
    } else {
      formError.value = e.data?.detail ?? "Impossible d'enregistrer le spectacle."
    }
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <AppShell>
    <div class="page">
      <div class="page-header">
        <h1 class="page-title">Spectacles</h1>
        <div class="page-count">{{ filtered.length }} résultat(s)</div>
      </div>

      <div class="filters">
        <div class="filters__row">
          <div
            v-for="f in dayFilters"
            :key="f.label"
            class="chip chip--small"
            :class="{ 'chip--active': f.active }"
            @click="f.select($event)"
          >
            {{ f.label }}
          </div>
        </div>
        <div class="filters__row">
          <div
            v-for="f in typeFilters"
            :key="f.label"
            class="chip"
            :class="{ 'chip--active': f.active }"
            @click="f.select($event)"
          >
            {{ f.label }}
          </div>
        </div>
        <div class="filters__row">
          <div
            v-for="f in venueFilters"
            :key="f.label"
            class="chip chip--small"
            :class="{ 'chip--active': f.active }"
            @click="f.select($event)"
          >
            {{ f.label }}
          </div>
        </div>
      </div>

      <div v-if="loading" class="hint">Chargement…</div>
      <div v-else-if="loadError" class="hint hint--error">
        Impossible de charger les spectacles. Es-tu connecté (session Django) ?
      </div>

      <template v-else>
        <div v-if="filtered.length > 0" class="show-list">
          <div
            v-for="show in filtered"
            :key="show.id"
            class="show-row"
            :class="{ 'show-row--nested': show.nested }"
          >
            <div class="show-row__bar" :style="{ background: show.dot }" />
            <div class="show-row__body">
              <div class="show-row__top">
                <div class="show-row__title">{{ show.display_title }}</div>
                <div
                  class="show-row__type"
                  :style="{ color: show.typeColor, background: show.typeBg }"
                >
                  {{ show.typeLabel }}
                </div>
                <div v-if="show.conflict" class="show-row__conflict">CONFLIT</div>
              </div>
              <div class="show-row__meta">{{ show.venue_name }} · {{ show.date }} · {{ show.time }}</div>
            </div>
            <RouterLink :to="`/spectacles/${show.id}`" class="show-row__link">Voir la fiche →</RouterLink>
          </div>
        </div>
        <div v-else class="empty">
          <div class="empty__icon" />
          <div class="empty__title">Aucun spectacle ne correspond</div>
          <div class="empty__subtitle">Essaie un autre type ou un autre lieu.</div>
        </div>
      </template>

      <div class="add-form">
        <div class="add-form__title">Ajouter un spectacle</div>
        <div class="add-form__row">
          <label class="add-form__field add-form__field--wide">
            <span class="add-form__label">Titre</span>
            <input
              v-model="form.title"
              placeholder="ex. Vertiges"
              class="add-form__input"
              :class="{ 'add-form__input--error': fieldErrors.title }"
              @input="fieldErrors.title = false"
            />
          </label>
          <label class="add-form__field">
            <span class="add-form__label">Lieu</span>
            <select
              v-model="form.venue"
              class="add-form__input"
              :class="{ 'add-form__input--error': fieldErrors.venue }"
              @change="fieldErrors.venue = false"
            >
              <option value="" disabled>Lieu…</option>
              <option v-for="v in venues" :key="v.id" :value="v.id">{{ v.name }}</option>
            </select>
          </label>
          <label class="add-form__field">
            <span class="add-form__label">Type</span>
            <select v-model="form.event_type" class="add-form__input">
              <option v-for="t in eventTypeOptions" :key="t.value" :value="t.value">{{ t.label }}</option>
            </select>
          </label>
          <!-- Les horaires commencent toujours une nouvelle ligne (voir
               .add-form__break) : titre/lieu/type d'un côté, la fenêtre
               horaire de l'autre. `step` est en secondes — 300 donne des
               minutes par pas de 5 dans le sélecteur natif. -->
          <div class="add-form__break" />
          <label class="add-form__field add-form__field--date">
            <span class="add-form__label">Début</span>
            <input
              v-model="form.start"
              type="datetime-local"
              step="300"
              class="add-form__input"
              :class="{ 'add-form__input--error': fieldErrors.start }"
              @input="fieldErrors.start = false"
            />
          </label>
          <label class="add-form__field add-form__field--date">
            <span class="add-form__label">Fin</span>
            <input
              v-model="form.end"
              type="datetime-local"
              step="300"
              class="add-form__input"
              :class="{ 'add-form__input--error': fieldErrors.end }"
              @input="fieldErrors.end = false"
            />
          </label>
          <div
            class="add-form__submit"
            :class="{ 'add-form__submit--disabled': !canSubmit }"
            @click="canSubmit && submitShow(false)"
          >
            + Ajouter
          </div>
        </div>
        <div v-if="fieldErrors.title" class="add-form__error">Le titre du spectacle est requis.</div>
        <div v-if="fieldErrors.venue" class="add-form__error">Choisis un lieu.</div>
        <div v-if="fieldErrors.start || fieldErrors.end" class="add-form__error">
          L'heure de début et de fin sont requises.
        </div>
        <div v-if="formError" class="add-form__error">{{ formError }}</div>
        <div v-if="conflictDetail" class="add-form__conflict">
          <div class="add-form__conflict-text">{{ conflictDetail.detail }}</div>
          <div class="add-form__submit add-form__submit--force" @click="submitShow(true)">
            Forcer la création malgré le conflit
          </div>
        </div>
      </div>
    </div>
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
  color: rgba(var(--fg-rgb), 0.4);
}

.filters {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.filters__row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.chip--small {
  padding: 6px 12px;
  border-radius: 0 6px 0 6px;
  font: 500 11.5px system-ui;
}

.hint {
  font: 500 13px system-ui;
  color: rgba(var(--fg-rgb), 0.5);
}

.hint--error {
  color: oklch(0.78 0.16 35);
}

.show-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* Bloc rattaché (montage/démontage) affiché en retrait sous son événement,
   avec le trait de raccordement — même lecture que les composants d'un kit
   dans l'inventaire (2026-07-31). */
.show-row--nested {
  position: relative;
  margin-left: 26px;
  border-left: 2px solid rgba(var(--accent-rgb), 0.25);
}

.show-row--nested::before {
  content: '';
  position: absolute;
  left: -14px;
  top: 50%;
  width: 14px;
  height: 2px;
  background: rgba(var(--accent-rgb), 0.25);
}

.show-row {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-notch-lg);
  padding: 16px 18px;
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.show-row__bar {
  width: 6px;
  align-self: stretch;
  border-radius: 0 4px 0 4px;
  flex: none;
}

.show-row__body {
  flex: 1;
  min-width: 200px;
}

.show-row__top {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.show-row__title {
  font: 600 15px var(--font-mono);
  color: rgb(var(--fg-rgb));
}

.show-row__type {
  font: 700 10px system-ui;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 2px 8px;
  border-radius: 0 6px 0 6px;
}

.show-row__conflict {
  font: 700 10px system-ui;
  color: oklch(0.85 0.13 35);
  background: oklch(0.7 0.16 35 / 0.18);
  padding: 2px 8px;
  border-radius: 0 10px 0 10px;
}

.show-row__meta {
  font: 400 12.5px system-ui;
  color: rgba(var(--fg-rgb), 0.5);
  margin-top: 4px;
}

.show-row__link {
  font: 600 11px system-ui;
  color: var(--link);
  cursor: pointer;
  white-space: nowrap;
  text-decoration: none;
}

.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 64px 20px;
  background: var(--bg-card);
  border: 1px dashed rgba(var(--fg-rgb), 0.15);
  border-radius: var(--radius-notch-lg);
}

.empty__icon {
  width: 40px;
  height: 40px;
  border-radius: 0 10px 0 10px;
  background: rgba(var(--fg-rgb), 0.06);
}

.empty__title {
  font: 600 13px system-ui;
  color: rgba(var(--fg-rgb), 0.6);
}

.empty__subtitle {
  font: 400 12px system-ui;
  color: rgba(var(--fg-rgb), 0.4);
  text-align: center;
  max-width: 280px;
}

</style>

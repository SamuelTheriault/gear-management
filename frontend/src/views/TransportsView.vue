<script setup>
import { ref, computed, watch } from 'vue'
import AppShell from '../components/AppShell.vue'
import { api } from '../api/client'
import { useActiveProject } from '../composables/useActiveProject'
import { useChipFilter } from '../composables/useChipFilter'

/**
 * Liste des transports — port de Transports.dc.html, branché sur l'API réelle
 * (/api/transports/). `TransportViewSet` n'avait pas de filtre `?project=`
 * (Transport n'a pas de FK project direct, isolé via `show`) — ajouté le
 * 2026-07-29 en portant cet écran (`show__project_id`).
 *
 * `has_technician_conflict` (dérivé sur TransportSerializer) sert pour
 * l'indicateur CONFLIT ; `is_empty` pour « Camion vide ».
 *
 * Fenêtre départ/arrivée (2026-07-30, décision Samuel) : le formulaire
 * d'ajout rapide n'a pas encore de Transport créé, donc pas de
 * `departure_show`/`arrival_show` à lire depuis l'API (ces champs n'existent
 * que sur un Transport existant — voir TransportSerializer). On reproduit
 * donc ici, côté client, exactement la même déduction que
 * `find_departure_show`/`find_arrival_show` (conflicts.py) à partir des
 * `shows`/`venues` déjà chargés pour le formulaire — même logique, mêmes
 * exemptions (lieu d'entrepôt = pas de borne), pour proposer une heure par
 * défaut et afficher les heures de référence avant même de soumettre.
 *
 * Filtre « Jour » (2026-08-02, demande de Samuel) : réutilise `t.day` (déjà
 * calculé) comme clé, trié chronologiquement avec « À planifier » (pas de
 * `scheduled_datetime`) toujours en dernier — voir la note dédiée dans
 * CLAUDE.md.
 *
 * Tournées multi-arrêts (2026-08-04, décision de Samuel) : un transport est
 * une séquence d'arrêts (`stops`) — le trajet affiché enchaîne TOUS les
 * arrêts (codes courts), plus seulement départ → arrivée, et le champ
 * `transport_type` (livraison/ramassage) a disparu du modèle : plus de
 * sélecteur de type dans le formulaire d'ajout, icône neutre unique. Le
 * formulaire d'ajout rapide reste volontairement un simple A → B (il crée
 * une tournée à 2 arrêts via le chemin de compat de l'API) — les arrêts
 * intermédiaires s'ajoutent sur la fiche. La déduction locale des spectacles
 * de référence suit la nouvelle règle du backend (get_transport_reference_shows) :
 * le spectacle desservi est le spectacle d'ARRIVÉE s'il se joue au lieu
 * d'arrivée, de DÉPART s'il se joue au lieu de départ, sinon les deux bouts
 * sont déduits autour de sa fenêtre.
 */

const { activeProjectId } = useActiveProject()

const transports = ref([])
const loading = ref(false)
const loadError = ref(null)

const statusMeta = {
  confirmed: { label: 'Confirmé', color: 'oklch(0.72 0.13 165)', bg: 'oklch(0.72 0.13 165 / .16)' },
  to_approve: { label: 'À approuver', color: 'oklch(0.78 0.13 85)', bg: 'oklch(0.78 0.13 85 / .16)' },
}

const dateFmt = new Intl.DateTimeFormat('fr-CA', { weekday: 'short', day: 'numeric', month: 'short' })
const timeFmt = new Intl.DateTimeFormat('fr-CA', { hour: '2-digit', minute: '2-digit', hour12: false })

function initials(name) {
  return (name || '')
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join('')
}

async function loadTransports() {
  if (!activeProjectId.value) return
  loading.value = true
  loadError.value = null
  try {
    const data = await api.get('/transports/', { project: activeProjectId.value })
    transports.value = Array.isArray(data) ? data : (data.results ?? [])
  } catch (e) {
    loadError.value = e
  } finally {
    loading.value = false
  }
}

watch(activeProjectId, loadTransports, { immediate: true })

const decorated = computed(() =>
  transports.value.map((t) => {
    const status = statusMeta[t.status] ?? statusMeta.confirmed
    const start = t.scheduled_datetime ? new Date(t.scheduled_datetime) : null
    const itemCount = t.materials?.length ?? 0
    const unitCount = (t.materials ?? []).reduce((sum, m) => sum + (m.quantity || 0), 0)
    const stops = t.stops ?? []
    return {
      ...t,
      // Trajet = la séquence complète des arrêts (codes courts si dispo) —
      // remplace l'ancien couple départ → arrivée + flèche typée.
      routeCodes: stops.map((s) => s.venue_code || s.venue_name).join(' → '),
      routeFull: stops.map((s) => s.venue_name).join(' → '),
      stopCount: stops.length,
      statusColor: status.color,
      statusBg: status.bg,
      statusLabel: status.label,
      day: start ? dateFmt.format(start) : 'À planifier',
      timeLabel: start ? `${dateFmt.format(start)} · ${timeFmt.format(start)}` : `À planifier`,
      durationLabel: t.estimated_duration_minutes ? `≈ ${t.estimated_duration_minutes} min` : '—',
      // Plusieurs techniciens possibles depuis le 2026-07-30 (voir
      // TransportTechnician) : `technician_names` remplace `technician_name`.
      hasTech: (t.technician_names ?? []).length > 0,
      techInitials: (t.technician_names ?? []).map(initials).join(' '),
      techLabel: (t.technician_names ?? []).join(', ') || 'Non assigné',
      techColor: (t.technician_names ?? []).length > 0 ? 'rgba(var(--fg-rgb),.75)' : 'rgba(var(--fg-rgb),.35)',
      materielLabel: itemCount > 0 ? `${itemCount} item(s) · ${unitCount} unité(s)` : 'Camion vide',
    }
  }),
)

// ⌘+clic pour combiner plusieurs valeurs (2026-08-01, à la demande de
// Samuel — même comportement que toutes les puces de filtre de l'app, voir
// useChipFilter.js). Quatre groupes indépendants (jour, spectacle, statut,
// technicien), combinés en ET.
const dayFilter = useChipFilter()
const showFilter = useChipFilter()
const statusFilter = useChipFilter()
const techFilter = useChipFilter()
const groupBy = ref('jour')

// Options de jour (2026-08-02, demande de Samuel) : la liste n'est PAS
// bornée à une semaine comme le Dashboard — elle peut couvrir tout le
// projet — donc triée chronologiquement plutôt que dans l'ordre de l'API,
// avec « À planifier » (pas de `scheduled_datetime`) toujours en dernier
// plutôt que mélangé aux vraies dates.
const dayOptions = computed(() => {
  const byLabel = new Map()
  decorated.value.forEach((t) => {
    if (!byLabel.has(t.day)) {
      byLabel.set(t.day, t.scheduled_datetime ? new Date(t.scheduled_datetime) : null)
    }
  })
  return [...byLabel.entries()]
    .sort(([, a], [, b]) => {
      if (!a && !b) return 0
      if (!a) return 1
      if (!b) return -1
      return a - b
    })
    .map(([label]) => label)
})

const showOptions = computed(() => [...new Set(decorated.value.map((t) => t.show_title))])
const techOptions = computed(() => {
  // Un déplacement pouvant mobiliser plusieurs personnes, chacune devient une
  // option de filtre à part entière.
  const names = new Set(decorated.value.flatMap((t) => t.technician_names ?? []))
  return [...names, 'Non assigné']
})

function mkAllChip(chipFilter, label = 'Tous') {
  return { label, active: chipFilter.selected.value.size === 0, select: () => chipFilter.selectAll() }
}

function mkChip(chipFilter, value, label = value) {
  return { label, active: chipFilter.isSelected(value), select: (event) => chipFilter.toggle(value, event) }
}

const dayFilters = computed(() => [
  mkAllChip(dayFilter, 'Tous les jours'),
  ...dayOptions.value.map((d) => mkChip(dayFilter, d)),
])
const showFilters = computed(() => [mkAllChip(showFilter), ...showOptions.value.map((s) => mkChip(showFilter, s))])
const statusFilters = computed(() => [
  mkAllChip(statusFilter),
  mkChip(statusFilter, 'confirmed', 'Confirmé'),
  mkChip(statusFilter, 'to_approve', 'À approuver'),
])
const techFilters = computed(() => [mkAllChip(techFilter), ...techOptions.value.map((t) => mkChip(techFilter, t))])

// Le filtre technicien a une sémantique un peu différente des deux autres :
// un déplacement peut avoir plusieurs personnes assignées, il correspond
// dès qu'UNE d'entre elles est dans la sélection (OU au sein du groupe,
// comme les autres champs, mais sur un tableau plutôt qu'une valeur seule).
function techMatches(t) {
  if (techFilter.selected.value.size === 0) return true
  const names = t.technician_names ?? []
  if (names.length === 0) return techFilter.isSelected('Non assigné')
  return names.some((n) => techFilter.isSelected(n))
}

const filtered = computed(() =>
  decorated.value.filter(
    (t) =>
      dayFilter.passes(t.day) &&
      showFilter.passes(t.show_title) &&
      statusFilter.passes(t.status) &&
      techMatches(t),
  ),
)

const groups = computed(() => {
  const key = groupBy.value === 'jour' ? 'day' : 'show_title'
  const order = []
  const byKey = {}
  filtered.value.forEach((t) => {
    const k = t[key]
    if (!byKey[k]) {
      byKey[k] = []
      order.push(k)
    }
    byKey[k].push(t)
  })
  return order.map((k) => ({ label: k, items: byKey[k] }))
})

// --- Ajout rapide d'un transport ---

const shows = ref([])
const venues = ref([])
const form = ref({
  show: '',
  origin_venue: '',
  destination_venue: '',
  scheduled_datetime: '',
})
const formError = ref(null)
const fieldErrors = ref({ show: false, origin_venue: false, destination_venue: false, scheduled_datetime: false })
const conflictDetail = ref(null)
const submitting = ref(false)

async function loadFormOptions() {
  if (!activeProjectId.value) return
  const [showsData, venuesData] = await Promise.all([
    api.get('/shows/', { project: activeProjectId.value }),
    api.get('/venues/', { project: activeProjectId.value }),
  ])
  shows.value = Array.isArray(showsData) ? showsData : (showsData.results ?? [])
  venues.value = Array.isArray(venuesData) ? venuesData : (venuesData.results ?? [])
}

watch(activeProjectId, loadFormOptions, { immediate: true })

const referenceFmt = new Intl.DateTimeFormat('fr-CA', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })

function fmtReference(iso) {
  return referenceFmt.format(new Date(iso))
}

// Réplique exacte de `find_departure_show`/`find_arrival_show` (conflicts.py) :
// le spectacle le plus proche chronologiquement à ce lieu, `null` si le lieu
// est un entrepôt ou si aucun spectacle candidat n'existe.
function findDepartureShowLocal(venueId, beforeDate, excludeShowId) {
  const venue = venues.value.find((v) => v.id === venueId)
  if (!venue || venue.is_storage || !beforeDate) return null
  const prior = shows.value.filter(
    (s) => s.venue === venueId && s.id !== excludeShowId && new Date(s.effective_end) <= beforeDate,
  )
  if (prior.length === 0) return null
  return prior.reduce((latest, s) => (new Date(s.effective_end) > new Date(latest.effective_end) ? s : latest))
}

function findArrivalShowLocal(venueId, afterDate, excludeShowId) {
  const venue = venues.value.find((v) => v.id === venueId)
  if (!venue || venue.is_storage || !afterDate) return null
  const upcoming = shows.value.filter(
    (s) => s.venue === venueId && s.id !== excludeShowId && new Date(s.effective_start) >= afterDate,
  )
  if (upcoming.length === 0) return null
  return upcoming.reduce((earliest, s) => (new Date(s.effective_start) < new Date(earliest.effective_start) ? s : earliest))
}

const referenceShows = computed(() => {
  // Même règle que le backend depuis le retrait de `transport_type`
  // (2026-08-04, voir get_transport_reference_shows) : c'est le LIEU du
  // spectacle desservi qui dit s'il est le bout d'arrivée ou de départ.
  const show = shows.value.find((s) => s.id === form.value.show)
  if (!show) return { departureShow: null, arrivalShow: null }
  if (form.value.destination_venue && show.venue === form.value.destination_venue) {
    const departureShow = form.value.origin_venue
      ? findDepartureShowLocal(form.value.origin_venue, new Date(show.effective_start), show.id)
      : null
    return { departureShow, arrivalShow: show }
  }
  if (form.value.origin_venue && show.venue === form.value.origin_venue) {
    const arrivalShow = form.value.destination_venue
      ? findArrivalShowLocal(form.value.destination_venue, new Date(show.effective_end), show.id)
      : null
    return { departureShow: show, arrivalShow }
  }
  return {
    departureShow: form.value.origin_venue
      ? findDepartureShowLocal(form.value.origin_venue, new Date(show.effective_start), show.id)
      : null,
    arrivalShow: form.value.destination_venue
      ? findArrivalShowLocal(form.value.destination_venue, new Date(show.effective_end), show.id)
      : null,
  }
})

// Propose l'heure de départ effective comme valeur par défaut — seulement
// tant que le champ est encore vide (n'écrase jamais une heure déjà saisie
// à la main), même esprit que TransportDetailView.vue.
watch(referenceShows, (refs) => {
  if (!form.value.scheduled_datetime && refs.departureShow) {
    form.value.scheduled_datetime = refs.departureShow.effective_end.slice(0, 16)
  }
})

const canSubmit = computed(() => !submitting.value)

function validateForm() {
  const errors = {
    show: !form.value.show,
    origin_venue: !form.value.origin_venue,
    destination_venue: !form.value.destination_venue,
    scheduled_datetime: !form.value.scheduled_datetime,
  }
  fieldErrors.value = errors
  if (
    !errors.origin_venue &&
    !errors.destination_venue &&
    form.value.origin_venue === form.value.destination_venue
  ) {
    errors.destination_venue = true
    fieldErrors.value = errors
    formError.value = "Le lieu d'arrivée doit être différent du lieu de départ."
    return false
  }
  return !Object.values(errors).some(Boolean)
}

async function submitTransport(force = false) {
  formError.value = null
  conflictDetail.value = null
  if (!validateForm()) return

  submitting.value = true
  try {
    // Ajout rapide = tournée simple à 2 arrêts, via le contrat de compat
    // origin/destination de l'API (2026-08-04) — les arrêts intermédiaires
    // s'ajoutent ensuite sur la fiche.
    await api.post('/transports/', {
      show: form.value.show,
      status: 'confirmed',
      origin_venue: form.value.origin_venue,
      destination_venue: form.value.destination_venue,
      scheduled_datetime: new Date(form.value.scheduled_datetime).toISOString(),
      force,
    })
    form.value = {
      show: '',
      origin_venue: '',
      destination_venue: '',
      scheduled_datetime: '',
    }
    fieldErrors.value = { show: false, origin_venue: false, destination_venue: false, scheduled_datetime: false }
    await loadTransports()
  } catch (e) {
    // `conflicts` (technicien) et `departure_show`/`arrival_show` (fenêtre
    // départ/arrivée) partagent le même bandeau « Forcer » — voir
    // TransportSerializer.validate() et TransportDetailView.vue.
    if (e.data?.conflicts || e.data?.departure_show || e.data?.arrival_show) {
      conflictDetail.value = e.data
    } else {
      formError.value = e.data?.detail ?? e.data?.destination_venue?.[0] ?? "Impossible d'enregistrer le transport."
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
        <h1 class="page-title">Transports</h1>
        <div class="page-count">{{ filtered.length }} transport(s)</div>
      </div>

      <div class="filters">
        <div class="filters__row">
          <div class="filters__label">Jour</div>
          <div
            v-for="f in dayFilters"
            :key="f.label"
            class="chip"
            :class="{ 'chip--active': f.active }"
            @click="f.select($event)"
          >
            {{ f.label }}
          </div>
        </div>
        <div class="filters__row">
          <div class="filters__label">Spectacle</div>
          <div
            v-for="f in showFilters"
            :key="f.label"
            class="chip"
            :class="{ 'chip--active': f.active }"
            @click="f.select($event)"
          >
            {{ f.label }}
          </div>
        </div>
        <div class="filters__row">
          <div class="filters__label">Statut</div>
          <div
            v-for="f in statusFilters"
            :key="f.label"
            class="chip"
            :class="{ 'chip--active': f.active }"
            @click="f.select($event)"
          >
            {{ f.label }}
          </div>
        </div>
        <div class="filters__row filters__row--split">
          <div class="filters__row">
            <div class="filters__label">Technicien</div>
            <div
              v-for="f in techFilters"
              :key="f.label"
              class="chip"
              :class="{ 'chip--active': f.active }"
              @click="f.select($event)"
            >
              {{ f.label }}
            </div>
          </div>
          <div class="group-toggle">
            <div class="group-toggle__item" :class="{ 'group-toggle__item--active': groupBy === 'jour' }" @click="groupBy = 'jour'">
              Par jour
            </div>
            <div
              class="group-toggle__item"
              :class="{ 'group-toggle__item--active': groupBy === 'spectacle' }"
              @click="groupBy = 'spectacle'"
            >
              Par spectacle
            </div>
          </div>
        </div>
      </div>

      <div v-if="loading" class="hint">Chargement…</div>
      <div v-else-if="loadError" class="hint hint--error">
        Impossible de charger les transports. Es-tu connecté (session Django) ?
      </div>

      <template v-else>
        <div v-if="filtered.length > 0" class="groups">
          <div v-for="grp in groups" :key="grp.label" class="group">
            <div class="group__label">{{ grp.label }}</div>
            <div v-for="t in grp.items" :key="t.id" class="transport-row">
              <div class="transport-row__icon">
                <span>→</span>
                <!-- Nombre d'arrêts en badge dès que la tournée dépasse le
                     simple A → B (2026-08-04). -->
                <span v-if="t.stopCount > 2" class="transport-row__stop-count">{{ t.stopCount }}</span>
              </div>
              <div class="transport-row__route">
                <div class="transport-row__codes" :title="t.routeFull">{{ t.routeCodes }}</div>
                <div class="transport-row__show">{{ t.show_title }}</div>
              </div>
              <div class="transport-row__time">
                <div class="transport-row__time-main">{{ t.timeLabel }}</div>
                <div class="transport-row__time-sub">{{ t.durationLabel }}</div>
              </div>
              <div class="transport-row__tech">
                <div v-if="t.hasTech" class="transport-row__avatar">{{ t.techInitials }}</div>
                <div class="transport-row__tech-label" :style="{ color: t.techColor }">{{ t.techLabel }}</div>
                <div v-if="t.has_technician_conflict" class="transport-row__conflict">CONFLIT</div>
              </div>
              <div class="transport-row__materiel">{{ t.materielLabel }}</div>
              <div class="transport-row__status" :style="{ color: t.statusColor, background: t.statusBg }">
                {{ t.statusLabel }}
              </div>
              <RouterLink :to="`/transports/${t.id}`" class="transport-row__link">Voir la fiche →</RouterLink>
            </div>
          </div>
        </div>
        <div v-else class="empty">
          <div class="empty__icon" />
          <div class="empty__title">Aucun transport ne correspond à ces filtres</div>
        </div>
      </template>

      <div class="add-form">
        <div class="add-form__title">Ajouter un transport</div>
        <div v-if="referenceShows.departureShow || referenceShows.arrivalShow" class="reference-times">
          <div v-if="referenceShows.departureShow" class="reference-times__item">
            <span class="reference-times__label">Fin du départ</span>
            <span class="reference-times__value">{{ referenceShows.departureShow.display_title }} · {{ fmtReference(referenceShows.departureShow.effective_end) }}</span>
          </div>
          <div v-if="referenceShows.arrivalShow" class="reference-times__item">
            <span class="reference-times__label">Début de l'arrivée</span>
            <span class="reference-times__value">{{ referenceShows.arrivalShow.display_title }} · {{ fmtReference(referenceShows.arrivalShow.effective_start) }}</span>
          </div>
        </div>
        <div class="add-form__row">
          <label class="add-form__field">
            <span class="add-form__label">Spectacle</span>
            <select
              v-model="form.show"
              class="add-form__input"
              :class="{ 'add-form__input--error': fieldErrors.show }"
              @change="fieldErrors.show = false"
            >
              <option value="" disabled>Spectacle…</option>
              <option v-for="s in shows" :key="s.id" :value="s.id">{{ s.display_title }}</option>
            </select>
          </label>
          <label class="add-form__field">
            <span class="add-form__label">Lieu de départ</span>
            <select
              v-model="form.origin_venue"
              class="add-form__input"
              :class="{ 'add-form__input--error': fieldErrors.origin_venue }"
              @change="fieldErrors.origin_venue = false"
            >
              <option value="" disabled>Lieu de départ…</option>
              <option v-for="v in venues" :key="v.id" :value="v.id">{{ v.name }}</option>
            </select>
          </label>
          <label class="add-form__field">
            <span class="add-form__label">Lieu d'arrivée</span>
            <select
              v-model="form.destination_venue"
              class="add-form__input"
              :class="{ 'add-form__input--error': fieldErrors.destination_venue }"
              @change="fieldErrors.destination_venue = false"
            >
              <option value="" disabled>Lieu d'arrivée…</option>
              <option v-for="v in venues" :key="v.id" :value="v.id">{{ v.name }}</option>
            </select>
          </label>
          <!-- Même règle que sur Spectacles : l'horaire commence une
               nouvelle ligne (voir .add-form__break), et `step="300"`
               (secondes) donne des minutes par pas de 5. -->
          <div class="add-form__break" />
          <label class="add-form__field add-form__field--date">
            <span class="add-form__label">Heure prévue</span>
            <input
              v-model="form.scheduled_datetime"
              type="datetime-local"
              step="300"
              class="add-form__input"
              :class="{ 'add-form__input--error': fieldErrors.scheduled_datetime }"
              @input="fieldErrors.scheduled_datetime = false"
            />
          </label>
          <div
            class="add-form__submit"
            :class="{ 'add-form__submit--disabled': !canSubmit }"
            @click="canSubmit && submitTransport(false)"
          >
            + Ajouter
          </div>
        </div>
        <div v-if="fieldErrors.show" class="add-form__error">Choisis un spectacle.</div>
        <div v-if="fieldErrors.origin_venue || fieldErrors.destination_venue" class="add-form__error">
          Choisis les lieux de départ et d'arrivée.
        </div>
        <div v-if="fieldErrors.scheduled_datetime" class="add-form__error">L'heure prévue est requise.</div>
        <div v-if="formError" class="add-form__error">{{ formError }}</div>
        <div v-if="conflictDetail" class="add-form__conflict">
          <div class="add-form__conflict-text">{{ conflictDetail.detail }}</div>
          <div class="add-form__submit add-form__submit--force" @click="submitTransport(true)">
            Forcer malgré le conflit
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
  align-items: center;
}

.filters__row--split {
  justify-content: space-between;
}

.filters__label {
  font: 700 10.5px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: rgba(var(--fg-rgb), 0.35);
  margin-right: 2px;
}

.group-toggle {
  display: flex;
  gap: 4px;
  background: var(--bg-row);
  border-radius: var(--radius-notch-sm);
  padding: 3px;
  flex: none;
}

.group-toggle__item {
  padding: 6px 13px;
  border-radius: 0 6px 0 6px;
  font: 600 11.5px system-ui;
  cursor: pointer;
  color: rgba(var(--fg-rgb), 0.5);
}

.group-toggle__item--active {
  background: rgba(var(--accent-rgb), 0.18);
  color: var(--accent);
}

.hint {
  font: 500 13px system-ui;
  color: rgba(var(--fg-rgb), 0.5);
}

.hint--error {
  color: oklch(0.78 0.16 35);
}

.groups {
  display: flex;
  flex-direction: column;
  gap: 22px;
}

.group {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.group__label {
  font: 700 11px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: rgba(var(--fg-rgb), 0.4);
}

.transport-row {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-notch-lg);
  padding: 16px 18px;
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.transport-row__icon {
  width: 30px;
  height: 30px;
  border-radius: var(--radius-notch-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
  font: 700 13px system-ui;
  /* Icône neutre unique depuis le retrait de livraison/ramassage
     (2026-08-04) — même teinte que les blocs transport du Dashboard. */
  position: relative;
  background: color-mix(in oklab, var(--transport) 18%, transparent);
  color: var(--transport);
}

.transport-row__stop-count {
  position: absolute;
  top: -6px;
  right: -6px;
  min-width: 15px;
  height: 15px;
  padding: 0 3px;
  border-radius: 0 5px 0 5px;
  background: var(--transport);
  color: #0b0d10;
  font: 700 9.5px var(--font-mono);
  display: flex;
  align-items: center;
  justify-content: center;
}

.transport-row__route {
  min-width: 150px;
  max-width: 180px;
}

.transport-row__codes {
  font: 700 14px var(--font-mono);
  color: rgb(var(--fg-rgb));
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.transport-row__arrow {
  color: rgba(var(--fg-rgb), 0.35);
}

.transport-row__show {
  font: 400 11px system-ui;
  color: rgba(var(--fg-rgb), 0.4);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.transport-row__time {
  min-width: 130px;
}

.transport-row__time-main {
  font: 600 13px system-ui;
  color: rgba(var(--fg-rgb), 0.8);
}

.transport-row__time-sub {
  font: 400 11px system-ui;
  color: rgba(var(--fg-rgb), 0.4);
}

.transport-row__tech {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 170px;
}

.transport-row__avatar {
  width: 22px;
  height: 22px;
  border-radius: 0 6px 0 6px;
  background: oklch(0.65 0.15 290 / 0.25);
  color: var(--accent);
  display: flex;
  align-items: center;
  justify-content: center;
  font: 700 9.5px system-ui;
  flex: none;
}

.transport-row__tech-label {
  font: 500 12.5px system-ui;
}

.transport-row__conflict {
  font: 700 9.5px system-ui;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: oklch(0.85 0.13 35);
  background: oklch(0.7 0.16 35 / 0.18);
  padding: 2px 7px;
  border-radius: 0 6px 0 6px;
}

.transport-row__materiel {
  font: 600 11px system-ui;
  color: rgba(var(--fg-rgb), 0.5);
  min-width: 110px;
}

.transport-row__status {
  font: 700 10px system-ui;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 4px 10px;
  border-radius: 0 6px 0 6px;
  white-space: nowrap;
}

.transport-row__link {
  font: 600 11px system-ui;
  color: var(--link);
  cursor: pointer;
  white-space: nowrap;
  margin-left: auto;
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

.reference-times {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 24px;
  padding: 10px 12px;
  border-radius: var(--radius-notch-sm);
  background: var(--bg-row);
  border: 1px solid var(--border-card);
}

.reference-times__item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.reference-times__label {
  font: 700 10px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: rgba(var(--fg-rgb), 0.4);
}

.reference-times__value {
  font: 500 12.5px system-ui;
  color: rgba(var(--fg-rgb), 0.8);
}

</style>

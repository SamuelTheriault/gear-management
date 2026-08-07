<script setup>
import { ref, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppShell from '../components/AppShell.vue'
import LeaveEditPrompt from '../components/LeaveEditPrompt.vue'
import { api } from '../api/client'
import { useFicheEdition } from '../composables/useFicheEdition'
import { useSuppressionFiche } from '../composables/useSuppressionFiche'

/**
 * Fiche camion — chantier Camion (2026-08-06, décisions de Samuel).
 *
 * La fiche porte la LOCATION : période de réservation (une seule par camion
 * — une deuxième location = une deuxième fiche), numéros de réservation et
 * de contrat, notes. Le « km estimé » vient du backend
 * (TruckSerializer.estimated_km) : somme des distances Google Routes des
 * tournées CONFIRMÉES assignées à ce camion — « calculé selon les trajets
 * google maps approuvés ». `km_is_partial` → « au moins X km » (des segments
 * sans GPS/estimation ne sont pas comptés).
 *
 * Utilisation : chronologie des tournées assignées
 * (GET /api/transports/?truck={id}, filtre ajouté avec l'entité), avec
 * l'avertissement hors réservation par tournée
 * (`truck_reservation_warning`) — même esprit que la fiche technicien.
 *
 * Édition via useFicheEdition (un seul PATCH), suppression via
 * useSuppressionFiche — le backend refuse la suppression d'un camion encore
 * assigné à des tournées ou du dernier camion du projet (message affiché tel
 * quel dans la boîte de confirmation).
 */

const route = useRoute()

const truck = ref(null)
const transports = ref([])
const loading = ref(false)
const loadError = ref(null)

const dateFmt = new Intl.DateTimeFormat('fr-CA', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })
const shortFmt = new Intl.DateTimeFormat('fr-CA', { weekday: 'short', day: 'numeric', month: 'short' })
const timeFmt = new Intl.DateTimeFormat('fr-CA', { hour: '2-digit', minute: '2-digit', hour12: false })

function fmtDateOnly(iso) {
  // Les dates de réservation sont des dates pures ('2026-08-14') : les
  // parser en local (T00:00) évite le décalage UTC d'un jour.
  return dateFmt.format(new Date(`${iso}T00:00`))
}

async function loadTruck() {
  const id = route.params.id
  loading.value = true
  loadError.value = null
  try {
    truck.value = await api.get(`/trucks/${id}/`)
    const trData = await api.get('/transports/', { truck: id })
    transports.value = Array.isArray(trData) ? trData : (trData.results ?? [])
  } catch (e) {
    loadError.value = e
  } finally {
    loading.value = false
  }
}

watch(() => route.params.id, loadTruck, { immediate: true })

// --- Édition de la fiche ---

const {
  editing, draft, saving, saveError, fieldErrors, canSave,
  startEdit, cancelEdit, save: saveTruck,
  leavePrompt, leaveSaving, leaveError, stayOnPage, saveAndLeave,
} = useFicheEdition({
  entity: truck,
  endpoint: '/trucks',
  fields: ['name', 'reservation_start', 'reservation_end', 'reservation_number', 'contract_number', 'notes'],
  errorMessage: 'Impossible d’enregistrer le camion.',
  toDraft: (t) => ({
    name: t.name ?? '',
    reservation_start: t.reservation_start ?? '',
    reservation_end: t.reservation_end ?? '',
    reservation_number: t.reservation_number ?? '',
    contract_number: t.contract_number ?? '',
    notes: t.notes ?? '',
  }),
  isValid: (d) => d.name.trim().length > 0,
  toPayload: (d) => ({
    name: d.name.trim(),
    // '' → null : un champ date vidé retire la borne (nullable côté modèle).
    reservation_start: d.reservation_start || null,
    reservation_end: d.reservation_end || null,
    reservation_number: d.reservation_number.trim(),
    contract_number: d.contract_number.trim(),
    notes: d.notes.trim(),
  }),
})

watch(() => route.params.id, cancelEdit)

// --- Suppression : les gardes vivent côté backend (camion utilisé, dernier
// camion du projet) — leur message s'affiche dans la boîte de confirmation.
const {
  confirming, deleting, deleteError, askDelete, cancelDelete, confirmDelete,
} = useSuppressionFiche({ endpoint: '/trucks', redirectTo: '/camions',
  beforeRedirect: () => cancelEdit(),
})

const reservationLabel = computed(() => {
  const t = truck.value
  if (!t || (!t.reservation_start && !t.reservation_end)) return 'Aucune réservation saisie'
  const debut = t.reservation_start ? fmtDateOnly(t.reservation_start) : '…'
  const fin = t.reservation_end ? fmtDateOnly(t.reservation_end) : '…'
  return `${debut} → ${fin}`
})

const kmLabel = computed(() => {
  const t = truck.value
  if (!t) return ''
  return t.km_is_partial ? `au moins ${t.estimated_km} km` : `${t.estimated_km} km`
})

// Chronologie d'utilisation : tournées triées par heure de départ, les
// propositions sans heure en fin de liste — même convention que partout.
const decoratedTransports = computed(() =>
  transports.value
    .map((tr) => ({
      ...tr,
      routeLabel: (tr.stops ?? []).map((s) => s.venue_code || s.venue_name).join(' → '),
      routeFull: (tr.stops ?? []).map((s) => s.venue_name).join(' → '),
      when: tr.scheduled_datetime
        ? `${shortFmt.format(new Date(tr.scheduled_datetime))} · ${timeFmt.format(new Date(tr.scheduled_datetime))}`
        : 'À planifier',
      durationLabel: tr.estimated_duration_minutes ? `≈ ${tr.estimated_duration_minutes} min` : '',
      isProposal: tr.status === 'to_approve',
    }))
    .sort((a, b) => {
      if (!a.scheduled_datetime && !b.scheduled_datetime) return 0
      if (!a.scheduled_datetime) return 1
      if (!b.scheduled_datetime) return -1
      return new Date(a.scheduled_datetime) - new Date(b.scheduled_datetime)
    }),
)
</script>

<template>
  <AppShell>
    <div v-if="loading" class="hint">Chargement…</div>
    <div v-else-if="loadError" class="hint hint--error">
      Impossible de charger ce camion. Es-tu connecté (session Django) ?
    </div>

    <div v-else-if="truck" class="page">
      <div class="breadcrumb"><RouterLink to="/camions">Camions</RouterLink> / {{ truck.name }}</div>

      <div class="header card">
        <div class="header__icon" aria-hidden="true">⌗</div>
        <div class="header__body">
          <div class="header__name">{{ truck.name }}</div>
          <div class="header__role">{{ reservationLabel }}</div>
        </div>
        <div class="fiche-actions">
          <button v-if="!editing" type="button" class="fiche-btn" @click="startEdit">
            Modifier la fiche
          </button>
          <template v-else>
            <button
              type="button"
              class="fiche-btn fiche-btn--primary"
              :disabled="!canSave"
              @click="saveTruck()"
            >
              {{ saving ? 'Enregistrement…' : 'Enregistrer' }}
            </button>
            <button type="button" class="fiche-btn" :disabled="saving" @click="cancelEdit">
              Annuler
            </button>
          </template>
        </div>
      </div>

      <!-- Mode édition : un seul PATCH à l'enregistrement -->
      <div v-if="editing" class="fiche-edit-card">
        <div class="fiche-grid">
          <label class="fiche-field fiche-field--full">
            <span class="fiche-label">Nom</span>
            <input
              v-model="draft.name"
              class="fiche-input"
              :class="{ 'fiche-input--error': fieldErrors.name }"
            />
            <span v-if="fieldErrors.name" class="fiche-error">{{ fieldErrors.name }}</span>
          </label>

          <label class="fiche-field">
            <span class="fiche-label">Réservé du</span>
            <input
              v-model="draft.reservation_start"
              type="date"
              class="fiche-input"
              :class="{ 'fiche-input--error': fieldErrors.reservation_start }"
            />
            <span v-if="fieldErrors.reservation_start" class="fiche-error">{{ fieldErrors.reservation_start }}</span>
          </label>

          <label class="fiche-field">
            <span class="fiche-label">au</span>
            <input
              v-model="draft.reservation_end"
              type="date"
              class="fiche-input"
              :class="{ 'fiche-input--error': fieldErrors.reservation_end }"
            />
            <span v-if="fieldErrors.reservation_end" class="fiche-error">{{ fieldErrors.reservation_end }}</span>
          </label>

          <label class="fiche-field">
            <span class="fiche-label">N° de réservation</span>
            <input v-model="draft.reservation_number" class="fiche-input" />
          </label>

          <label class="fiche-field">
            <span class="fiche-label">N° de contrat</span>
            <input v-model="draft.contract_number" class="fiche-input" />
          </label>

          <label class="fiche-field fiche-field--full">
            <span class="fiche-label">Notes</span>
            <textarea
              v-model="draft.notes"
              rows="4"
              class="fiche-input fiche-input--area"
              placeholder="Assurances, franchise, état au départ, contact du loueur…"
            />
          </label>
        </div>

        <div v-if="!draft.name.trim()" class="fiche-error">Le nom du camion est requis.</div>
        <div v-if="saveError" class="fiche-error">{{ saveError }}</div>

        <div class="fiche-danger">
          <div class="fiche-danger__hint">
            Un camion encore assigné à des tournées — ou le dernier du projet — ne peut pas être supprimé.
          </div>
          <button type="button" class="fiche-btn fiche-btn--danger" @click="askDelete">
            Supprimer ce camion
          </button>
        </div>
      </div>

      <div v-if="confirming" class="fiche-confirm-backdrop" @click.self="cancelDelete">
        <div class="fiche-confirm">
          <div class="fiche-confirm__title">Supprimer « {{ truck.name }} » ?</div>
          <p class="fiche-confirm__text">Cette action est définitive.</p>
          <div v-if="deleteError" class="fiche-error">{{ deleteError }}</div>
          <div class="fiche-confirm__actions">
            <button type="button" class="fiche-btn" :disabled="deleting" @click="cancelDelete">
              Annuler
            </button>
            <button
              type="button"
              class="fiche-btn fiche-btn--danger"
              :disabled="deleting"
              @click="confirmDelete(truck.id)"
            >
              {{ deleting ? 'Suppression…' : 'Supprimer' }}
            </button>
          </div>
        </div>
      </div>

      <template v-if="!editing">
        <div class="card summary-grid">
          <div>
            <div class="summary-label">Km estimé</div>
            <div class="summary-value">{{ kmLabel }}</div>
            <div v-if="truck.km_is_partial" class="summary-sub">
              Des segments sans distance connue ne sont pas comptés.
            </div>
          </div>
          <div>
            <div class="summary-label">N° de réservation</div>
            <div class="summary-value">{{ truck.reservation_number || '—' }}</div>
          </div>
          <div>
            <div class="summary-label">N° de contrat</div>
            <div class="summary-value">{{ truck.contract_number || '—' }}</div>
          </div>
          <div>
            <div class="summary-label">Tournées assignées</div>
            <div class="summary-value">{{ truck.transport_count }}</div>
          </div>
        </div>

        <div v-if="truck.notes" class="card">
          <div class="card-title">Notes</div>
          <div class="card-text">{{ truck.notes }}</div>
        </div>
      </template>

      <div class="card">
        <div class="card-title" style="margin-bottom: 12px">Utilisation du camion</div>
        <div v-if="decoratedTransports.length > 0" class="row-list">
          <RouterLink
            v-for="tr in decoratedTransports"
            :key="tr.id"
            :to="`/transports/${tr.id}`"
            class="row row--clickable"
          >
            <span
              class="row__dot"
              :style="{ background: tr.isProposal ? 'oklch(0.78 0.13 85)' : 'var(--transport)' }"
              :title="tr.isProposal ? 'Proposition à approuver' : 'Tournée confirmée'"
            />
            <div class="row__body">
              <div class="row__title" :title="tr.routeFull">{{ tr.routeLabel }}</div>
              <div class="row__subtitle">
                {{ tr.when }}<template v-if="tr.durationLabel"> · {{ tr.durationLabel }}</template>
              </div>
              <div v-if="tr.truck_reservation_warning" class="row__warning">
                {{ tr.truck_reservation_warning }}
              </div>
            </div>
            <div v-if="tr.isProposal" class="row__proposal">À approuver</div>
          </RouterLink>
        </div>
        <div v-else class="row-empty">Aucune tournée assignée à ce camion.</div>
      </div>
    </div>

    <LeaveEditPrompt
      :visible="leavePrompt"
      :saving="leaveSaving"
      :error="leaveError"
      @stay="stayOnPage"
      @save="saveAndLeave"
    />
  </AppShell>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 18px;
  max-width: 620px;
}

.hint {
  padding: 32px 40px;
  font: 500 13px system-ui;
  color: rgba(var(--fg-rgb), 0.58);
}

.hint--error {
  color: oklch(0.78 0.16 35);
}

.breadcrumb {
  font: 500 12px system-ui;
  color: rgba(var(--fg-rgb), 0.48);
}

.breadcrumb :deep(a) {
  color: var(--link);
  text-decoration: none;
}

.card {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-notch-lg);
  padding: 20px;
}

.header {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.header__icon {
  width: 44px;
  height: 44px;
  border-radius: 0 12px 0 12px;
  background: color-mix(in oklab, var(--transport) 20%, transparent);
  color: var(--transport);
  display: flex;
  align-items: center;
  justify-content: center;
  font: 700 18px system-ui;
  flex: none;
}

.header__body {
  flex: 1;
  min-width: 0;
}

.header__name {
  font: 700 17px var(--font-mono);
  color: rgb(var(--fg-rgb));
}

.header__role {
  font: 400 12.5px system-ui;
  color: rgba(var(--fg-rgb), 0.58);
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 18px;
}

.summary-label {
  font: 700 11px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: rgba(var(--fg-rgb), 0.45);
}

.summary-value {
  font: 600 14px system-ui;
  color: rgb(var(--fg-rgb));
  margin-top: 4px;
}

.summary-sub {
  font: 400 11px system-ui;
  color: rgba(var(--fg-rgb), 0.45);
  margin-top: 2px;
}

.card-title {
  font: 700 12px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: rgba(var(--fg-rgb), 0.65);
}

.card-text {
  margin-top: 8px;
  font: 400 13px/1.6 system-ui;
  color: rgba(var(--fg-rgb), 0.7);
  white-space: pre-wrap;
}

.row-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: var(--radius-notch-sm);
  background: var(--bg-row);
  text-decoration: none;
}

.row--clickable:hover {
  background: color-mix(in oklab, var(--bg-row) 80%, var(--accent) 8%);
}

.row__dot {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  flex: none;
}

.row__body {
  flex: 1;
  min-width: 0;
}

.row__title {
  font: 600 13px system-ui;
  color: rgb(var(--fg-rgb));
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.row__subtitle {
  font: 400 11.5px system-ui;
  color: rgba(var(--fg-rgb), 0.5);
}

.row__warning {
  font: 500 11.5px system-ui;
  color: oklch(0.85 0.13 35);
  margin-top: 2px;
}

.row__proposal {
  font: 700 9.5px system-ui;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: oklch(0.78 0.13 85);
  background: oklch(0.78 0.13 85 / 0.16);
  padding: 3px 8px;
  border-radius: 0 6px 0 6px;
  flex: none;
}

.row-empty {
  font: 500 12.5px system-ui;
  color: rgba(var(--fg-rgb), 0.4);
  padding: 10px 12px;
}
</style>

<script setup>
import { ref, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppShell from '../components/AppShell.vue'
import LeaveEditPrompt from '../components/LeaveEditPrompt.vue'
import { api } from '../api/client'
import PartagerFicheModal from '../components/PartagerFicheModal.vue'
import { useFicheEdition } from '../composables/useFicheEdition'
import { useSuppressionFiche } from '../composables/useSuppressionFiche'

/**
 * Fiche technicien — port de TechnicienDetail.dc.html, branché sur l'API
 * réelle. `contact_info` est un champ texte libre unique côté modèle
 * (téléphone/courriel non séparés comme dans le prototype).
 *
 * Édition : bouton « Modifier la fiche » dans l'entête, toute la fiche
 * bascule en formulaire et part en un seul PATCH — voir useFicheEdition.
 * `project` est volontairement exclu (déplacer un technicien de projet
 * casserait ses assignations).
 *
 * Spectacles assignés : GET /api/show-technicians/?technician={id} (filtre
 * ajouté le 2026-07-28, voir ShowTechnicianViewSet). Conflit calculé via
 * GET /api/shows/{id}/conflicts/ par spectacle assigné.
 * Transports assignés : GET /api/transports/?technician={id} (filtre ajouté
 * en même temps sur TransportViewSet).
 *
 * En-tête à avatar (`header__avatar`/`header__name`/`header__role`) plutôt
 * que le simple `.header__title` des quatre autres fiches (Lieu, Matériel,
 * Spectacle, Transport) — point 7 de l'audit ergonomie/navigation du
 * 2026-07-31, tranché avec Samuel : choix assumé, pas une dérive à
 * corriger. L'avatar aide à repérer un nom dans une liste de rendez-vous ;
 * ça ne se justifie pas pour les quatre autres fiches, qui titrent une
 * entité (lieu, matériel, spectacle, transport) plutôt qu'une personne.
 */

const route = useRoute()

// Panneau de partage (chantier « sorties de rapports », 2026-08-08) —
// voir components/PartagerFicheModal.vue.
const partageOuvert = ref(false)

const technician = ref(null)
const showAssignments = ref([])
const transports = ref([])
const conflictShowIds = ref(new Set())
const loading = ref(false)
const loadError = ref(null)

const dateFmt = new Intl.DateTimeFormat('fr-CA', { weekday: 'short', day: 'numeric', month: 'short' })
const timeFmt = new Intl.DateTimeFormat('fr-CA', { hour: '2-digit', minute: '2-digit', hour12: false })

function initials(name) {
  return (name || '?')
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join('')
}

async function loadTechnician() {
  const id = route.params.id
  loading.value = true
  loadError.value = null
  try {
    technician.value = await api.get(`/technicians/${id}/`)

    const [stData, trData] = await Promise.all([
      api.get('/show-technicians/', { technician: id }),
      api.get('/transports/', { technician: id }),
    ])
    showAssignments.value = Array.isArray(stData) ? stData : (stData.results ?? [])
    transports.value = Array.isArray(trData) ? trData : (trData.results ?? [])

    // Détails du spectacle (venue, horaire) pour chaque assignation — pas
    // exposés directement sur ShowTechnicianSerializer.
    const showsData = await api.get('/shows/', { project: technician.value.project })
    const showsList = Array.isArray(showsData) ? showsData : (showsData.results ?? [])
    const showsById = new Map(showsList.map((s) => [s.id, s]))
    showAssignments.value = showAssignments.value.map((a) => ({ ...a, showDetail: showsById.get(a.show) }))

    const conflictChecks = await Promise.all(
      showAssignments.value.map(async (a) => {
        try {
          const c = await api.get(`/shows/${a.show}/conflicts/`)
          const hit = (c.technician_conflicts ?? []).some((tc) => tc.technician_id === Number(id))
          return hit ? a.show : null
        } catch {
          return null
        }
      }),
    )
    conflictShowIds.value = new Set(conflictChecks.filter((id) => id !== null))
  } catch (e) {
    loadError.value = e
  } finally {
    loading.value = false
  }
}

watch(() => route.params.id, loadTechnician, { immediate: true })

// --- Édition de la fiche ---

const {
  editing, draft, saving, saveError, fieldErrors, canSave,
  startEdit, cancelEdit, save: saveTechnician,
  leavePrompt, leaveSaving, leaveError, stayOnPage, saveAndLeave,
} = useFicheEdition({
  entity: technician,
  endpoint: '/technicians',
  fields: ['name', 'specialty', 'contact_info', 'notes'],
  errorMessage: 'Impossible d’enregistrer le technicien.',
  toDraft: (t) => ({
    name: t.name ?? '',
    specialty: t.specialty ?? '',
    contact_info: t.contact_info ?? '',
    notes: t.notes ?? '',
  }),
  isValid: (d) => d.name.trim().length > 0,
  toPayload: (d) => ({
    name: d.name.trim(),
    specialty: d.specialty.trim(),
    contact_info: d.contact_info.trim(),
    notes: d.notes.trim(),
  }),
})

// Changer de technicien sans quitter la vue ne doit pas conserver un
// formulaire à moitié rempli sur le précédent.
watch(() => route.params.id, cancelEdit)

// --- Suppression (2026-08-04, même comportement que Spectacle/Transport) ---
// Autorisée même si le technicien a un historique d'assignations — pas de
// blocage façon Lieu. `TechnicianSerializer.deletion_impact` compte ce qui
// disparaît en cascade (ShowTechnician/TransportTechnician, tables de
// liaison en CASCADE).
const {
  confirming, deleting, deleteError, askDelete, cancelDelete, confirmDelete,
} = useSuppressionFiche({ endpoint: '/technicians', redirectTo: '/techniciens',
  beforeRedirect: () => cancelEdit(),
})

const deletionImpact = computed(() => technician.value?.deletion_impact ?? null)
const hasCascade = computed(
  () => !!deletionImpact.value && Object.values(deletionImpact.value).some((n) => n > 0),
)

const decoratedShows = computed(() =>
  showAssignments.value
    .filter((a) => a.showDetail)
    .map((a) => {
      const start = new Date(a.showDetail.start_datetime)
      return {
        ...a,
        title: a.showDetail.title,
        venue: a.showDetail.venue_name,
        date: dateFmt.format(start),
        time: timeFmt.format(start),
        conflict: conflictShowIds.value.has(a.show),
      }
    })
    .sort((a, b) => new Date(a.showDetail.start_datetime) - new Date(b.showDetail.start_datetime)),
)

const decoratedTransports = computed(() =>
  transports.value.map((tr) => ({
    ...tr,
    // Tournées multi-arrêts (2026-08-04) : séquence complète, plus de type.
    routeLabel: (tr.stops ?? []).map((s) => s.venue_name).join(' → '),
    time: tr.scheduled_datetime ? timeFmt.format(new Date(tr.scheduled_datetime)) : 'à planifier',
  })),
)
</script>

<template>
  <AppShell>
    <div v-if="loading" class="hint">Chargement…</div>
    <div v-else-if="loadError" class="hint hint--error">
      Impossible de charger ce technicien. Es-tu connecté (session Django) ?
    </div>

    <div v-else-if="technician" class="page">
      <div class="breadcrumb"><RouterLink to="/techniciens">Techniciens</RouterLink> / {{ technician.name }}</div>

      <div class="header card">
        <div class="header__avatar">{{ initials(technician.name) }}</div>
        <div class="header__body">
          <div class="header__name">{{ technician.name }}</div>
          <div class="header__role">{{ technician.specialty || '—' }}</div>
        </div>
        <div class="fiche-actions">
          <button v-if="!editing" type="button" class="fiche-btn" @click="partageOuvert = true">
            Partager / Imprimer
          </button>
          <button v-if="!editing" type="button" class="fiche-btn" @click="startEdit">
            Modifier la fiche
          </button>
          <template v-else>
            <button
              type="button"
              class="fiche-btn fiche-btn--primary"
              :disabled="!canSave"
              @click="saveTechnician()"
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
          <label class="fiche-field">
            <span class="fiche-label">Nom</span>
            <input
              v-model="draft.name"
              class="fiche-input"
              :class="{ 'fiche-input--error': fieldErrors.name }"
            />
            <span v-if="fieldErrors.name" class="fiche-error">{{ fieldErrors.name }}</span>
          </label>

          <label class="fiche-field">
            <span class="fiche-label">Spécialité</span>
            <input
              v-model="draft.specialty"
              placeholder="ex. Son, Éclairage, Vidéo"
              class="fiche-input"
              :class="{ 'fiche-input--error': fieldErrors.specialty }"
            />
            <span v-if="fieldErrors.specialty" class="fiche-error">{{ fieldErrors.specialty }}</span>
          </label>

          <label class="fiche-field fiche-field--full">
            <span class="fiche-label">Coordonnées</span>
            <input
              v-model="draft.contact_info"
              placeholder="Téléphone / courriel"
              class="fiche-input"
              :class="{ 'fiche-input--error': fieldErrors.contact_info }"
            />
            <span v-if="fieldErrors.contact_info" class="fiche-error">{{ fieldErrors.contact_info }}</span>
          </label>

          <label class="fiche-field fiche-field--full">
            <span class="fiche-label">Notes</span>
            <textarea v-model="draft.notes" rows="4" class="fiche-input fiche-input--area" />
          </label>
        </div>

        <div v-if="!draft.name.trim()" class="fiche-error">Le nom du technicien est requis.</div>
        <div v-if="saveError" class="fiche-error">{{ saveError }}</div>

        <div class="fiche-danger">
          <div class="fiche-danger__hint">
            Supprimer ce technicien retire aussi ses assignations et ses déplacements.
          </div>
          <button type="button" class="fiche-btn fiche-btn--danger" @click="askDelete">
            Supprimer ce technicien
          </button>
        </div>
      </div>

      <div v-if="confirming" class="fiche-confirm-backdrop" @click.self="cancelDelete">
        <div class="fiche-confirm">
          <div class="fiche-confirm__title">Supprimer « {{ technician.name }} » ?</div>
          <p class="fiche-confirm__text">Cette action est définitive.</p>
          <template v-if="hasCascade">
            <p class="fiche-confirm__text">Seront supprimés en même temps :</p>
            <ul class="fiche-confirm__list">
              <li v-if="deletionImpact.shows > 0">
                {{ deletionImpact.shows }} assignation(s) de spectacle
              </li>
              <li v-if="deletionImpact.transports > 0">
                {{ deletionImpact.transports }} assignation(s) de transport
              </li>
            </ul>
          </template>
          <div v-if="deleteError" class="fiche-error">{{ deleteError }}</div>
          <div class="fiche-confirm__actions">
            <button type="button" class="fiche-btn" :disabled="deleting" @click="cancelDelete">
              Annuler
            </button>
            <button
              type="button"
              class="fiche-btn fiche-btn--danger"
              :disabled="deleting"
              @click="confirmDelete(technician.id)"
            >
              {{ deleting ? 'Suppression…' : 'Supprimer' }}
            </button>
          </div>
        </div>
      </div>

      <template v-if="!editing">
        <div v-if="technician.contact_info" class="contact-card">
          {{ technician.contact_info }}
        </div>

        <div v-if="technician.notes" class="card">
          <div class="card-title">Notes</div>
          <div class="card-text">{{ technician.notes }}</div>
        </div>
      </template>

      <div class="card">
        <div class="card-title" style="margin-bottom: 12px">Spectacles assignés</div>
        <div v-if="decoratedShows.length > 0" class="row-list">
          <RouterLink
            v-for="s in decoratedShows"
            :key="s.id"
            :to="`/spectacles/${s.show}`"
            class="row row--clickable"
          >
            <span class="row__dot" :style="{ background: s.conflict ? 'oklch(0.7 0.16 35)' : 'oklch(0.72 0.13 165)' }" />
            <div class="row__body">
              <div class="row__title">{{ s.title }}</div>
              <div class="row__subtitle">{{ s.venue }} · {{ s.date }} {{ s.time }}</div>
            </div>
            <div v-if="s.conflict" class="row__conflict">CONFLIT</div>
          </RouterLink>
        </div>
        <div v-else class="row-empty">Aucun spectacle assigné.</div>
      </div>

      <div class="card">
        <div class="card-title" style="margin-bottom: 12px">Transports assignés</div>
        <div v-if="decoratedTransports.length > 0" class="row-list">
          <RouterLink
            v-for="tr in decoratedTransports"
            :key="tr.id"
            :to="`/transports/${tr.id}`"
            class="row row--clickable"
          >
            <div class="row__body row__body--flex">{{ tr.routeLabel }}</div>
            <div class="row__time">{{ tr.time }}</div>
          </RouterLink>
        </div>
        <div v-else class="row-empty">Aucun transport assigné.</div>
      </div>
    </div>

    <!-- Quitter une fiche en cours d'édition demande d'abord quoi faire
         (2026-08-05) — voir useLeaveGuard.js. -->
    <LeaveEditPrompt
      :visible="leavePrompt"
      :saving="leaveSaving"
      :error="leaveError"
      @stay="stayOnPage"
      @save="saveAndLeave"
    />
    <PartagerFicheModal
      v-if="partageOuvert && technician"
      kind="technician"
      :project-id="technician.project"
      :target-id="technician.id"
      :label="technician.name"
      @close="partageOuvert = false"
    />
  </AppShell>
  </template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 18px;
  max-width: 560px;
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
  padding: 18px;
}

.header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
}

.header__avatar {
  width: 56px;
  height: 56px;
  border-radius: var(--radius-notch-lg);
  background: oklch(0.65 0.15 290 / 0.25);
  color: var(--accent);
  display: flex;
  align-items: center;
  justify-content: center;
  font: 700 18px system-ui;
  flex: none;
}

.header__body {
  flex: 1;
}

.header__name {
  font: 700 19px var(--font-mono);
  color: rgb(var(--fg-rgb));
}

.header__role {
  font: 400 13px system-ui;
  color: rgba(var(--fg-rgb), 0.58);
}

.contact-card {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: 0 10px 0 10px;
  padding: 16px 14px;
  text-align: center;
  font: 600 14px system-ui;
  color: var(--link);
}


.card-text {
  font: 400 13.5px/1.6 system-ui;
  color: rgba(var(--fg-rgb), 0.75);
  margin-top: 12px;
}

.row-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  border-radius: 0 10px 0 10px;
  background: var(--bg-row);
  min-height: 44px;
}

/* Ligne entière cliquable (2026-08-05) — voir la même règle sur la fiche
   lieu. */
.row--clickable {
  text-decoration: none;
  cursor: pointer;
}

.row--clickable:hover {
  background: rgba(var(--fg-rgb), 0.09);
}

.row__dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex: none;
}

.row__body {
  flex: 1;
  min-width: 0;
}

.row__body--flex {
  font: 500 13px system-ui;
  color: rgba(var(--fg-rgb), 0.8);
}

.row__title {
  font: 600 14px system-ui;
  color: rgb(var(--fg-rgb));
  text-decoration: none;
  display: block;
}

.row__subtitle {
  font: 400 12px system-ui;
  color: rgba(var(--fg-rgb), 0.58);
}

.row__conflict {
  font: 700 10px system-ui;
  color: oklch(0.85 0.13 35);
  background: oklch(0.7 0.16 35 / 0.18);
  padding: 3px 8px;
  border-radius: 0 10px 0 10px;
}

.row__time {
  font: 600 13px system-ui;
  color: rgba(var(--fg-rgb), 0.58);
}

.row-empty {
  font: 500 12.5px system-ui;
  color: rgba(var(--fg-rgb), 0.48);
  padding: 10px 12px;
}
</style>

<script setup>
import { ref, computed, watch } from 'vue'
import AppShell from '../components/AppShell.vue'
import { api } from '../api/client'
import { useActiveProject } from '../composables/useActiveProject'

/**
 * Liste des camions — chantier Camion (2026-08-06, décision de Samuel).
 *
 * Chaque projet a toujours au moins un camion (créé par défaut à l'ouverture
 * du projet — voir signals.creer_camion_par_defaut côté backend) : chaque
 * tournée est assignée à un camion. Cet écran liste la flotte du projet avec
 * l'essentiel (période de réservation, km estimé, nombre de tournées) et
 * permet l'ajout rapide par nom — la réservation se complète sur la fiche.
 *
 * `estimated_km`/`km_is_partial` viennent de TruckSerializer : somme des
 * distances Google Routes des tournées CONFIRMÉES. « au moins » quand des
 * segments n'ont pas de distance connue (lieux sans GPS, durée manuelle).
 */

const { activeProjectId } = useActiveProject()

const trucks = ref([])
const loading = ref(false)
const loadError = ref(null)

const dateFmt = new Intl.DateTimeFormat('fr-CA', { day: 'numeric', month: 'short', year: 'numeric' })

async function loadTrucks() {
  if (!activeProjectId.value) return
  loading.value = true
  loadError.value = null
  try {
    const data = await api.get('/trucks/', { project: activeProjectId.value })
    trucks.value = Array.isArray(data) ? data : (data.results ?? [])
  } catch (e) {
    loadError.value = e
  } finally {
    loading.value = false
  }
}

watch(activeProjectId, loadTrucks, { immediate: true })

const decorated = computed(() =>
  trucks.value.map((t) => {
    let reservation = 'Aucune réservation'
    if (t.reservation_start || t.reservation_end) {
      const debut = t.reservation_start ? dateFmt.format(new Date(`${t.reservation_start}T00:00`)) : '…'
      const fin = t.reservation_end ? dateFmt.format(new Date(`${t.reservation_end}T00:00`)) : '…'
      reservation = `${debut} → ${fin}`
    }
    return {
      ...t,
      reservation,
      kmLabel: t.km_is_partial ? `≥ ${t.estimated_km} km` : `${t.estimated_km} km`,
    }
  }),
)

// --- Ajout rapide d'un camion ---

const form = ref({ name: '' })
const formError = ref(null)
const nameError = ref(false)
const submitting = ref(false)

const canSubmit = computed(() => form.value.name.trim().length > 0 && !submitting.value)

async function addTruck() {
  formError.value = null
  const name = form.value.name.trim()
  if (!name) {
    nameError.value = true
    return
  }
  submitting.value = true
  try {
    await api.post('/trucks/', { project: activeProjectId.value, name })
    form.value = { name: '' }
    nameError.value = false
    await loadTrucks()
  } catch (e) {
    formError.value = e.data?.detail ?? "Impossible d'enregistrer le camion."
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <AppShell>
    <div class="page">
      <div class="page-header">
        <h1 class="page-title">Camions</h1>
        <div class="page-count">{{ decorated.length }} camion(s)</div>
      </div>

      <div v-if="loading" class="hint">Chargement…</div>
      <div v-else-if="loadError" class="hint hint--error">
        Impossible de charger les camions. Es-tu connecté (session Django) ?
      </div>

      <template v-else>
        <div v-if="decorated.length > 0" class="list">
          <div v-for="t in decorated" :key="t.id" class="row">
            <div class="row__icon" aria-hidden="true">⌗</div>
            <div class="row__body">
              <div class="row__name" :title="t.name">{{ t.name }}</div>
              <div class="row__meta">
                {{ t.reservation }}
                <template v-if="t.reservation_number"> · rés. {{ t.reservation_number }}</template>
              </div>
            </div>
            <div class="row__badge row__badge--km" :title="t.km_is_partial ? 'Des segments sans distance connue ne sont pas comptés' : ''">
              {{ t.kmLabel }}
            </div>
            <div class="row__badge">{{ t.transport_count }} tournée(s)</div>
            <RouterLink :to="`/camions/${t.id}`" class="row__link">Voir la fiche →</RouterLink>
          </div>
        </div>
        <div v-else class="empty">
          <div class="empty__icon" />
          <div class="empty__title">Aucun camion pour ce projet</div>
        </div>
      </template>

      <div class="add-form">
        <div class="add-form__title">Ajouter un camion</div>
        <div class="add-form__row">
          <label class="add-form__field add-form__field--wide">
            <span class="add-form__label">Nom</span>
            <input
              v-model="form.name"
              placeholder="ex. Cube 16 pi — semaine 2"
              class="add-form__input"
              :class="{ 'add-form__input--error': nameError }"
              @input="nameError = false"
              @keyup.enter="canSubmit && addTruck()"
            />
          </label>
          <div
            class="add-form__submit"
            :class="{ 'add-form__submit--disabled': !canSubmit }"
            @click="canSubmit && addTruck()"
          >
            + Ajouter
          </div>
        </div>
        <div v-if="nameError" class="add-form__error">Le nom du camion est requis.</div>
        <div v-if="formError" class="add-form__error">{{ formError }}</div>
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
  color: rgba(var(--fg-rgb), 0.48);
}

.hint {
  font: 500 13px system-ui;
  color: rgba(var(--fg-rgb), 0.58);
}

.hint--error {
  color: oklch(0.78 0.16 35);
}

.list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.row {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-notch-lg);
  padding: 18px;
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.row__icon {
  width: 40px;
  height: 40px;
  border-radius: 0 10px 0 10px;
  background: color-mix(in oklab, var(--transport) 20%, transparent);
  color: var(--transport);
  display: flex;
  align-items: center;
  justify-content: center;
  font: 700 16px system-ui;
  flex: none;
}

.row__body {
  flex: 1;
  min-width: 0;
}

.row__name {
  font: 600 14.5px var(--font-mono);
  color: rgb(var(--fg-rgb));
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.row__meta {
  font: 400 12px system-ui;
  color: rgba(var(--fg-rgb), 0.58);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.row__badge {
  font: 700 10px system-ui;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: oklch(0.72 0.13 165);
  background: oklch(0.72 0.13 165 / 0.16);
  padding: 3px 9px;
  border-radius: 0 6px 0 6px;
  white-space: nowrap;
  flex: none;
}

.row__badge--km {
  color: var(--transport);
  background: color-mix(in oklab, var(--transport) 16%, transparent);
}

.row__link {
  font: 600 11px system-ui;
  color: var(--link);
  cursor: pointer;
  white-space: nowrap;
  flex: none;
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
  color: rgba(var(--fg-rgb), 0.68);
}
</style>

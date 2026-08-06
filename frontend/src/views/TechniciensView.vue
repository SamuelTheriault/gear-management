<script setup>
import { ref, computed, watch } from 'vue'
import AppShell from '../components/AppShell.vue'
import { api } from '../api/client'
import { useActiveProject } from '../composables/useActiveProject'

/**
 * Liste des techniciens — port de Techniciens.dc.html, branché sur l'API
 * réelle (/api/technicians/). `specialty` est un champ texte libre côté
 * modèle (pas de choix fixes comme dans le prototype) — remplacé par un input
 * texte plutôt qu'un select à options figées.
 */

const { activeProjectId } = useActiveProject()

const technicians = ref([])
const showCounts = ref(new Map())
const loading = ref(false)
const loadError = ref(null)

function initials(name) {
  return (name || '?')
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join('')
}

async function loadTechnicians() {
  if (!activeProjectId.value) return
  loading.value = true
  loadError.value = null
  try {
    const data = await api.get('/technicians/', { project: activeProjectId.value })
    technicians.value = Array.isArray(data) ? data : (data.results ?? [])

    // Nombre de spectacles assignés — un appel par technicien (voir
    // ShowTechnicianViewSet.get_queryset, filtre ?technician= ajouté le
    // 2026-07-28 en portant cet écran).
    const counts = await Promise.all(
      technicians.value.map(async (t) => {
        try {
          const st = await api.get('/show-technicians/', { technician: t.id })
          const list = Array.isArray(st) ? st : (st.results ?? [])
          return [t.id, list.length]
        } catch {
          return [t.id, 0]
        }
      }),
    )
    showCounts.value = new Map(counts)
  } catch (e) {
    loadError.value = e
  } finally {
    loading.value = false
  }
}

watch(activeProjectId, loadTechnicians, { immediate: true })

const decorated = computed(() =>
  technicians.value.map((t) => ({
    ...t,
    initials: initials(t.name),
    showCount: showCounts.value.get(t.id) ?? 0,
  })),
)

// --- Ajout rapide d'un technicien ---

const form = ref({ name: '', specialty: '', contact_info: '' })
const formError = ref(null)
const nameError = ref(false)
const submitting = ref(false)

const canSubmit = computed(() => form.value.name.trim().length > 0 && !submitting.value)

async function addTechnician() {
  formError.value = null
  const name = form.value.name.trim()
  if (!name) {
    nameError.value = true
    return
  }
  submitting.value = true
  try {
    await api.post('/technicians/', {
      project: activeProjectId.value,
      name,
      specialty: form.value.specialty.trim(),
      contact_info: form.value.contact_info.trim(),
    })
    form.value = { name: '', specialty: '', contact_info: '' }
    nameError.value = false
    await loadTechnicians()
  } catch (e) {
    formError.value = e.data?.detail ?? "Impossible d'enregistrer le technicien."
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <AppShell>
    <div class="page">
      <div class="page-header">
        <h1 class="page-title">Techniciens</h1>
        <div class="page-count">{{ decorated.length }} technicien(s)</div>
      </div>

      <div v-if="loading" class="hint">Chargement…</div>
      <div v-else-if="loadError" class="hint hint--error">
        Impossible de charger les techniciens. Es-tu connecté (session Django) ?
      </div>

      <template v-else>
        <div v-if="decorated.length > 0" class="list">
          <div v-for="t in decorated" :key="t.id" class="row">
            <div class="row__avatar">{{ t.initials }}</div>
            <div class="row__body">
              <div class="row__name" :title="t.name">{{ t.name }}</div>
              <div class="row__role">{{ t.specialty || '—' }}</div>
            </div>
            <div class="row__badge">{{ t.showCount }} spec.</div>
            <RouterLink :to="`/techniciens/${t.id}`" class="row__link">Voir la fiche →</RouterLink>
          </div>
        </div>
        <div v-else class="empty">
          <div class="empty__icon" />
          <div class="empty__title">Aucun technicien pour ce projet</div>
        </div>
      </template>

      <div class="add-form">
        <div class="add-form__title">Ajouter un technicien</div>
        <div class="add-form__row">
          <label class="add-form__field add-form__field--wide">
            <span class="add-form__label">Nom complet</span>
            <input
              v-model="form.name"
              class="add-form__input"
              :class="{ 'add-form__input--error': nameError }"
              @input="nameError = false"
            />
          </label>
          <label class="add-form__field">
            <span class="add-form__label">Spécialité</span>
            <input v-model="form.specialty" placeholder="ex. Régie son" class="add-form__input" />
          </label>
          <label class="add-form__field">
            <span class="add-form__label">Coordonnées</span>
            <input v-model="form.contact_info" placeholder="Téléphone / courriel" class="add-form__input" />
          </label>
          <div
            class="add-form__submit"
            :class="{ 'add-form__submit--disabled': !canSubmit }"
            @click="canSubmit && addTechnician()"
          >
            + Ajouter
          </div>
        </div>
        <div v-if="nameError" class="add-form__error">Le nom du technicien est requis.</div>
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
}

.row__avatar {
  width: 40px;
  height: 40px;
  border-radius: 0 10px 0 10px;
  background: oklch(0.65 0.15 290 / 0.25);
  color: var(--accent);
  display: flex;
  align-items: center;
  justify-content: center;
  font: 700 14px system-ui;
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

.row__role {
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

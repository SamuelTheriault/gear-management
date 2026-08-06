<script setup>
import { ref, computed, watch } from 'vue'
import AppShell from '../components/AppShell.vue'
import { api } from '../api/client'
import { useActiveProject } from '../composables/useActiveProject'
import { useEscapeKey } from '../composables/useEscapeKey'

/**
 * Gestion des catégories de matériel (`/api/material-categories/`) — ajoutée
 * le 2026-07-30 à la demande de Samuel. Jusque-là les 9 catégories étaient
 * codées en dur dans le modèle Django et leurs couleurs dans les vues Vue.
 *
 * Isolées par projet (voir `MaterialCategory`) : cet écran ne montre et ne
 * crée que les catégories du projet actif.
 *
 * Suppression : `Material.category` est en PROTECT côté backend. L'API refuse
 * donc de supprimer une catégorie utilisée sans `?reassign_to=` — on affiche
 * alors une confirmation qui demande vers quelle catégorie basculer le
 * matériel concerné (ou « aucune », la FK étant nullable).
 */

const { activeProjectId } = useActiveProject()

const categories = ref([])
const loading = ref(false)
const loadError = ref(null)

// Palette proposée à la création/édition. Ce sont les couleurs des 9
// catégories historiques (voir MaterialCategory.DEFAULTS côté backend), plus
// quelques teintes libres pour les nouvelles.
const PALETTE = [
  'oklch(0.75 0.13 200)',
  'oklch(0.78 0.13 85)',
  'oklch(0.72 0.13 255)',
  'oklch(0.75 0.13 165)',
  'oklch(0.75 0.13 320)',
  'oklch(0.72 0.13 145)',
  'oklch(0.72 0.13 105)',
  'oklch(0.75 0.13 20)',
  'oklch(0.7 0.16 35)',
  'oklch(0.7 0.14 300)',
  'oklch(0.8 0.1 60)',
  'rgba(var(--fg-rgb),.5)',
]

async function loadCategories() {
  if (!activeProjectId.value) return
  loading.value = true
  loadError.value = null
  try {
    const data = await api.get('/material-categories/', { project: activeProjectId.value })
    categories.value = Array.isArray(data) ? data : (data.results ?? [])
  } catch (e) {
    loadError.value = e
  } finally {
    loading.value = false
  }
}

watch(activeProjectId, loadCategories, { immediate: true })

const totalMaterials = computed(() =>
  categories.value.reduce((sum, c) => sum + (c.material_count ?? 0), 0),
)

// --- Ajout ---

const form = ref({ name: '', color: PALETTE[0] })
const formError = ref(null)
const nameError = ref(false)
const submitting = ref(false)

const canSubmit = computed(() => form.value.name.trim().length > 0 && !submitting.value)

async function addCategory() {
  formError.value = null
  const name = form.value.name.trim()
  if (!name) {
    nameError.value = true
    return
  }
  submitting.value = true
  try {
    await api.post('/material-categories/', {
      project: activeProjectId.value,
      name,
      color: form.value.color,
    })
    form.value = { name: '', color: PALETTE[0] }
    nameError.value = false
    await loadCategories()
  } catch (e) {
    formError.value = e.data?.name?.[0] ?? e.data?.detail ?? "Impossible d'enregistrer la catégorie."
  } finally {
    submitting.value = false
  }
}

// --- Édition inline ---
// Pas de `useFicheEdition` ici : ce composable gère UNE fiche de détail, alors
// que cet écran édite des lignes d'une liste (plusieurs entités sur la même
// page, une seule ouverte à la fois).

const editingId = ref(null)
const editDraft = ref({ name: '', color: '' })
const editError = ref(null)
const savingEdit = ref(false)

function startEdit(category) {
  editingId.value = category.id
  editDraft.value = { name: category.name, color: category.color }
  editError.value = null
}

function cancelEdit() {
  editingId.value = null
  editError.value = null
}

async function saveEdit() {
  if (!editDraft.value.name.trim()) return
  savingEdit.value = true
  editError.value = null
  try {
    await api.patch(`/material-categories/${editingId.value}/`, {
      name: editDraft.value.name.trim(),
      color: editDraft.value.color,
    })
    editingId.value = null
    await loadCategories()
  } catch (e) {
    editError.value = e.data?.name?.[0] ?? e.data?.detail ?? "Impossible d'enregistrer les changements."
  } finally {
    savingEdit.value = false
  }
}

// --- Suppression (avec réassignation si la catégorie est utilisée) ---

const deleting = ref(null)
const reassignTo = ref('')
const deleteError = ref(null)
const deletingBusy = ref(false)

const reassignOptions = computed(() =>
  categories.value.filter((c) => c.id !== deleting.value?.id),
)

function startDelete(category) {
  deleting.value = category
  reassignTo.value = ''
  deleteError.value = null
}

function cancelDelete() {
  deleting.value = null
  deleteError.value = null
}

// Échap ferme la confirmation, même geste que le clic sur le fond.
useEscapeKey(() => {
  if (deleting.value) cancelDelete()
})

async function confirmDelete() {
  deletingBusy.value = true
  deleteError.value = null
  try {
    // Le backend n'exige `reassign_to` que si la catégorie est utilisée, mais
    // l'envoyer systématiquement évite un aller-retour : la chaîne vide
    // signifie explicitement « laisser sans catégorie ».
    const query = deleting.value.material_count > 0 ? `?reassign_to=${reassignTo.value}` : ''
    await api.delete(`/material-categories/${deleting.value.id}/${query}`)
    deleting.value = null
    await loadCategories()
  } catch (e) {
    deleteError.value =
      e.data?.reassign_to ?? e.data?.detail ?? 'Impossible de supprimer la catégorie.'
  } finally {
    deletingBusy.value = false
  }
}
</script>

<template>
  <AppShell>
    <div class="page">
      <div class="page-header">
        <h1 class="page-title">Catégories de matériel</h1>
        <div class="page-count">
          {{ categories.length }} catégorie(s) · {{ totalMaterials }} item(s) classés
        </div>
      </div>

      <div v-if="loading" class="hint">Chargement…</div>
      <div v-else-if="loadError" class="hint hint--error">
        Impossible de charger les catégories. Es-tu connecté (session Django) ?
      </div>

      <template v-else>
        <div v-if="categories.length > 0" class="list">
          <div v-for="c in categories" :key="c.id" class="row">
            <template v-if="editingId !== c.id">
              <span class="row__dot" :style="{ background: c.color }" />
              <div class="row__body">
                <div class="row__name">{{ c.name }}</div>
                <div class="row__meta">
                  {{ c.material_count }} matériel(s)
                </div>
              </div>
              <button type="button" class="fiche-btn" @click="startEdit(c)">Modifier</button>
              <button type="button" class="fiche-btn fiche-btn--danger" @click="startDelete(c)">
                Supprimer
              </button>
            </template>

            <template v-else>
              <span class="row__dot" :style="{ background: editDraft.color }" />
              <div class="row__edit">
                <input v-model="editDraft.name" class="fiche-input" />
                <div class="swatches">
                  <button
                    v-for="color in PALETTE"
                    :key="color"
                    type="button"
                    class="swatch"
                    :class="{ 'swatch--active': editDraft.color === color }"
                    :style="{ background: color }"
                    :title="color"
                    @click="editDraft.color = color"
                  />
                </div>
                <div v-if="editError" class="fiche-error">{{ editError }}</div>
              </div>
              <button
                type="button"
                class="fiche-btn fiche-btn--primary"
                :disabled="savingEdit || !editDraft.name.trim()"
                @click="saveEdit()"
              >
                {{ savingEdit ? 'Enregistrement…' : 'Enregistrer' }}
              </button>
              <button type="button" class="fiche-btn" :disabled="savingEdit" @click="cancelEdit">
                Annuler
              </button>
            </template>
          </div>
        </div>
        <div v-else class="empty">
          <div class="empty__icon" />
          <div class="empty__title">Aucune catégorie pour ce projet</div>
        </div>
      </template>

      <div class="add-form">
        <div class="add-form__title">Ajouter une catégorie</div>
        <div class="add-form__row">
          <label class="add-form__field add-form__field--wide">
            <span class="add-form__label">Nom de la catégorie</span>
            <input
              v-model="form.name"
              placeholder="ex. Machinerie"
              class="add-form__input"
              :class="{ 'add-form__input--error': nameError }"
              @input="nameError = false"
            />
          </label>
          <label class="add-form__field add-form__field--wide">
            <span class="add-form__label">Couleur</span>
            <div class="swatches">
              <button
                v-for="color in PALETTE"
                :key="color"
                type="button"
                class="swatch"
                :class="{ 'swatch--active': form.color === color }"
                :style="{ background: color }"
                :title="color"
                @click="form.color = color"
              />
            </div>
          </label>
          <div
            class="add-form__submit"
            :class="{ 'add-form__submit--disabled': !canSubmit }"
            @click="canSubmit && addCategory()"
          >
            + Ajouter
          </div>
        </div>
        <div v-if="nameError" class="add-form__error">Le nom de la catégorie est requis.</div>
        <div v-if="formError" class="add-form__error">{{ formError }}</div>
      </div>
    </div>

    <!-- Confirmation de suppression -->
    <div v-if="deleting" class="modal-overlay" @click.self="cancelDelete">
      <div class="modal">
        <div class="modal__title">Supprimer « {{ deleting.name }} » ?</div>

        <div v-if="deleting.material_count > 0" class="modal__body">
          <p class="modal__text">
            {{ deleting.material_count }} matériel(s) utilisent cette catégorie. Choisis
            vers quelle catégorie les basculer avant la suppression.
          </p>
          <label class="fiche-field">
            <span class="fiche-label">Basculer vers</span>
            <select v-model="reassignTo" class="fiche-input">
              <option value="">Aucune catégorie</option>
              <option v-for="c in reassignOptions" :key="c.id" :value="c.id">{{ c.name }}</option>
            </select>
          </label>
        </div>
        <p v-else class="modal__text">
          Aucun matériel n'utilise cette catégorie — la suppression est sans effet
          sur l'inventaire.
        </p>

        <div v-if="deleteError" class="fiche-error">{{ deleteError }}</div>

        <div class="modal__actions">
          <button type="button" class="fiche-btn" :disabled="deletingBusy" @click="cancelDelete">
            Annuler
          </button>
          <button
            type="button"
            class="fiche-btn fiche-btn--danger"
            :disabled="deletingBusy"
            @click="confirmDelete()"
          >
            {{ deletingBusy ? 'Suppression…' : 'Supprimer' }}
          </button>
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
  max-width: 820px;
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
  gap: 8px;
}

.row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: 0 10px 0 10px;
}

.row__dot {
  width: 12px;
  height: 12px;
  border-radius: 3px;
  flex: none;
}

.row__body {
  flex: 1;
  min-width: 0;
}

.row__name {
  font: 600 14px system-ui;
  color: rgb(var(--fg-rgb));
}

.row__meta {
  font: 400 11.5px system-ui;
  color: rgba(var(--fg-rgb), 0.48);
  margin-top: 2px;
}

.row__edit {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.swatches {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.swatch {
  width: 22px;
  height: 22px;
  border-radius: 0 5px 0 5px;
  border: 2px solid transparent;
  cursor: pointer;
  padding: 0;
}

.swatch--active {
  border-color: rgb(var(--fg-rgb));
}

.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 56px 20px;
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

.modal {
  width: 100%;
  max-width: 420px;
  background: var(--bg-card);
  border: 1px solid rgba(var(--fg-rgb), 0.12);
  border-radius: var(--radius-notch-lg);
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.modal__title {
  font: 700 15px var(--font-mono);
  color: rgb(var(--fg-rgb));
}

.modal__body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.modal__text {
  margin: 0;
  font: 400 13px/1.5 system-ui;
  color: rgba(var(--fg-rgb), 0.72);
}

.modal__actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>

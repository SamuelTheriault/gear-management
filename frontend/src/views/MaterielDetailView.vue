<script setup>
import { ref, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppShell from '../components/AppShell.vue'
import { api } from '../api/client'
import { useFicheEdition } from '../composables/useFicheEdition'

/**
 * Fiche matériel — port de MaterielDetail.dc.html, branché sur l'API réelle.
 *
 * Édition : bouton « Modifier la fiche » dans l'entête, toute la fiche
 * bascule en formulaire et part en un seul PATCH — voir useFicheEdition.
 *
 * Composants : matériel dont `parent_material` pointe vers ce matériel
 * (`component_ids` sur le matériel courant donne les ids, on charge la liste
 * du projet pour avoir les noms/lieux/statuts).
 *
 * Assignations actuelles : `GET /api/show-materials/?material={id}` — filtre
 * ajouté côté backend le 2026-07-28 en portant cet écran (ShowMaterialViewSet
 * n'avait aucun filtre par query param avant, donc `?material=` était
 * silencieusement ignoré et renvoyait TOUTES les assignations, tous
 * spectacles confondus — bug trouvé ici, corrigé dans views.py).
 */

const route = useRoute()

const material = ref(null)
const components = ref([])
const assignments = ref([])
const conflictShowIds = ref(new Set())
const loading = ref(false)
const loadError = ref(null)

// Options des listes déroulantes du mode édition (chargées avec la fiche).
const projectMaterials = ref([])
const projectVenues = ref([])
const projectCategories = ref([])

const NO_CATEGORY = { label: 'Sans catégorie', color: 'rgba(255,255,255,.3)' }

const ownershipMeta = {
  owned: { label: 'Propriété', color: 'oklch(0.72 0.13 165)', bg: 'oklch(0.72 0.13 165 / .16)' },
  rental: { label: 'Location', color: 'oklch(0.8 0.13 85)', bg: 'oklch(0.8 0.13 85 / .16)' },
}

const dateTimeFmt = new Intl.DateTimeFormat('fr-CA', {
  weekday: 'short',
  day: 'numeric',
  month: 'short',
})
const timeFmt = new Intl.DateTimeFormat('fr-CA', { hour: '2-digit', minute: '2-digit', hour12: false })

function fmtRange(startIso, endIso) {
  const start = new Date(startIso)
  const end = new Date(endIso)
  return `${dateTimeFmt.format(start)} ${timeFmt.format(start)}–${timeFmt.format(end)}`
}

async function loadMaterial() {
  const id = route.params.id
  loading.value = true
  loadError.value = null
  try {
    material.value = await api.get(`/materials/${id}/`)

    const [materialsData, assignmentsData, venuesData, categoriesData] = await Promise.all([
      api.get('/materials/', { project: material.value.project, include_inactive: true }),
      api.get('/show-materials/', { material: id }),
      api.get('/venues/', { project: material.value.project }),
      api.get('/material-categories/', { project: material.value.project }),
    ])
    const materialsList = Array.isArray(materialsData) ? materialsData : (materialsData.results ?? [])
    projectMaterials.value = materialsList
    projectVenues.value = Array.isArray(venuesData) ? venuesData : (venuesData.results ?? [])
    projectCategories.value = Array.isArray(categoriesData) ? categoriesData : (categoriesData.results ?? [])
    components.value = materialsList.filter((m) => m.parent_material === Number(id))
    assignments.value = Array.isArray(assignmentsData) ? assignmentsData : (assignmentsData.results ?? [])

    // Conflit = ce matériel apparaît dans material_conflicts des conflits du
    // spectacle assigné (voir GET /api/shows/{id}/conflicts/). Un appel par
    // assignation ; volume typique faible.
    const conflictChecks = await Promise.all(
      assignments.value.map(async (a) => {
        try {
          const c = await api.get(`/shows/${a.show}/conflicts/`)
          const hit = (c.material_conflicts ?? []).some((mc) => mc.material_id === Number(id))
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

watch(() => route.params.id, loadMaterial, { immediate: true })

// `category_name`/`category_color` sont dupliqués en lecture seule par
// MaterialSerializer (voir MaterialCategory, ajoutée le 2026-07-30).
const catInfo = computed(() =>
  material.value?.category
    ? { label: material.value.category_name, color: material.value.category_color }
    : NO_CATEGORY,
)
const ownInfo = computed(() => ownershipMeta[material.value?.ownership_status] ?? ownershipMeta.owned)

const decoratedComponents = computed(() =>
  components.value.map((c) => {
    const own = ownershipMeta[c.ownership_status] ?? ownershipMeta.owned
    return { ...c, ownLabel: own.label, ownColor: own.color, ownBg: own.bg }
  }),
)

const decoratedAssignments = computed(() =>
  assignments.value.map((a) => ({
    ...a,
    conflict: conflictShowIds.value.has(a.show),
  })),
)

// --- Édition de la fiche ---
// `project` est volontairement exclu : déplacer un matériel vers un autre
// projet casserait ses assignations, son lieu d'entreposage et son parent
// (isolation par projet, voir schema.md section 11).

const {
  editing, draft, saving, saveError, fieldErrors, canSave,
  startEdit, cancelEdit, save,
} = useFicheEdition({
  entity: material,
  endpoint: '/materials',
  fields: [
    'name', 'description', 'category', 'ownership_status', 'quantity',
    'venue', 'parent_material', 'is_active', 'notes',
  ],
  errorMessage: 'Impossible d’enregistrer le matériel.',
  toDraft: (m) => ({
    name: m.name ?? '',
    description: m.description ?? '',
    category: m.category ?? '',
    ownership_status: m.ownership_status ?? 'owned',
    quantity: m.quantity ?? 1,
    venue: m.venue ?? '',
    parent_material: m.parent_material ?? '',
    is_active: Boolean(m.is_active),
    notes: m.notes ?? '',
  }),
  // Le lieu d'origine ne peut plus être vidé (obligatoire depuis le 2026-07-30).
  isValid: (d) => d.name.trim().length > 0 && Number(d.quantity) >= 1 && d.venue !== '',
  toPayload: (d) => ({
    name: d.name.trim(),
    description: d.description.trim(),
    category: d.category === '' ? null : Number(d.category),
    ownership_status: d.ownership_status,
    quantity: Number(d.quantity),
    venue: Number(d.venue),
    // `parent_material` reste nullable : « aucun » doit partir en `null`, pas
    // en chaîne vide.
    parent_material: d.parent_material === '' ? null : Number(d.parent_material),
    is_active: d.is_active,
    notes: d.notes.trim(),
  }),
})

async function saveMaterial() {
  // Recharge derrière l'enregistrement : changer le parent ou la quantité
  // modifie l'arbre des composants affiché plus bas.
  if (await save()) await loadMaterial()
}

// Le backend refuse un parent qui n'a pas quantity=1, et le matériel ne peut
// pas être son propre parent (MaterialSerializer.validate_parent_material) —
// on retire ces cas de la liste plutôt que de laisser l'utilisateur se faire
// refuser l'enregistrement.
const parentOptions = computed(() =>
  projectMaterials.value.filter(
    (m) => m.id !== material.value?.id && m.quantity === 1 && m.parent_material == null,
  ),
)

// Règles de MaterialSerializer.validate() : un matériel en plusieurs
// exemplaires ne peut ni avoir un parent, ni être un kit. On l'annonce dans
// le formulaire au lieu d'attendre l'erreur 400.
const quantityLocked = computed(
  () => draft.value?.parent_material !== '' || components.value.length > 0,
)

watch(() => route.params.id, cancelEdit)
</script>

<template>
  <AppShell>
    <div v-if="loading" class="hint">Chargement…</div>
    <div v-else-if="loadError" class="hint hint--error">
      Impossible de charger ce matériel. Es-tu connecté (session Django) ?
    </div>

    <div v-else-if="material" class="page">
      <div class="breadcrumb"><RouterLink to="/materiel">Matériel</RouterLink> / {{ material.name }}</div>

      <div class="header">
        <div>
          <div class="header__top">
            <span class="header__dot" :style="{ background: catInfo.color }" />
            <h1 class="header__title">{{ material.name }}</h1>
          </div>
          <div class="header__meta">
            {{ catInfo.label }} · {{ material.venue_name ?? 'Sans lieu' }} · {{ ownInfo.label }}
          </div>
        </div>
        <div v-if="!material.is_active" class="header__badge header__badge--inactive">Inactif</div>
        <div class="fiche-actions">
          <button v-if="!editing" type="button" class="fiche-btn" @click="startEdit">
            Modifier la fiche
          </button>
          <template v-else>
            <button
              type="button"
              class="fiche-btn fiche-btn--primary"
              :disabled="!canSave"
              @click="saveMaterial()"
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
          <label class="fiche-field fiche-field--wide">
            <span class="fiche-label">Nom</span>
            <input
              v-model="draft.name"
              class="fiche-input"
              :class="{ 'fiche-input--error': fieldErrors.name }"
            />
            <span v-if="fieldErrors.name" class="fiche-error">{{ fieldErrors.name }}</span>
          </label>

          <label class="fiche-field">
            <span class="fiche-label">Catégorie</span>
            <select v-model="draft.category" class="fiche-input">
              <option value="">Sans catégorie</option>
              <option v-for="c in projectCategories" :key="c.id" :value="c.id">{{ c.name }}</option>
            </select>
            <span v-if="fieldErrors.category" class="fiche-error">{{ fieldErrors.category }}</span>
          </label>

          <label class="fiche-field">
            <span class="fiche-label">Propriété</span>
            <select v-model="draft.ownership_status" class="fiche-input">
              <option value="owned">Propriété</option>
              <option value="rental">Location</option>
            </select>
          </label>

          <label class="fiche-field">
            <span class="fiche-label">Quantité</span>
            <input
              v-model="draft.quantity"
              type="number"
              min="1"
              :disabled="quantityLocked"
              class="fiche-input"
              :class="{ 'fiche-input--error': fieldErrors.quantity }"
            />
            <span v-if="fieldErrors.quantity" class="fiche-error">{{ fieldErrors.quantity }}</span>
            <span v-else-if="quantityLocked" class="fiche-hint">
              Figée à 1 : ce matériel fait partie d'un kit ou en est un.
            </span>
          </label>

          <label class="fiche-field">
            <span class="fiche-label">Lieu d'origine *</span>
            <select
              v-model="draft.venue"
              class="fiche-input"
              :class="{ 'fiche-input--error': fieldErrors.venue }"
            >
              <option value="" disabled>Choisir un lieu…</option>
              <option v-for="v in projectVenues" :key="v.id" :value="v.id">{{ v.name }}</option>
            </select>
            <span v-if="fieldErrors.venue" class="fiche-error">{{ fieldErrors.venue }}</span>
          </label>

          <label class="fiche-field">
            <span class="fiche-label">Fait partie du kit</span>
            <select
              v-model="draft.parent_material"
              class="fiche-input"
              :class="{ 'fiche-input--error': fieldErrors.parent_material }"
            >
              <option value="">Aucun (matériel autonome)</option>
              <option v-for="m in parentOptions" :key="m.id" :value="m.id">{{ m.name }}</option>
            </select>
            <span v-if="fieldErrors.parent_material" class="fiche-error">
              {{ fieldErrors.parent_material }}
            </span>
          </label>

          <label class="fiche-field">
            <span class="fiche-label">Statut</span>
            <select v-model="draft.is_active" class="fiche-input">
              <option :value="true">Actif</option>
              <option :value="false">Inactif (masqué de l'inventaire)</option>
            </select>
          </label>

          <label class="fiche-field fiche-field--full">
            <span class="fiche-label">Description</span>
            <textarea v-model="draft.description" rows="3" class="fiche-input fiche-input--area" />
          </label>

          <label class="fiche-field fiche-field--full">
            <span class="fiche-label">Notes</span>
            <textarea v-model="draft.notes" rows="3" class="fiche-input fiche-input--area" />
          </label>
        </div>

        <div class="fiche-hint">
          Un matériel inactif reste en base et garde son historique — il est
          seulement masqué de la liste d'inventaire.
        </div>
        <div v-if="!draft.name.trim()" class="fiche-error">Le nom du matériel est requis.</div>
        <div v-if="draft.venue === ''" class="fiche-error">
          Le lieu d'origine est requis — c'est là que le matériel doit revenir en fin de projet.
        </div>
        <div v-if="saveError" class="fiche-error">{{ saveError }}</div>
      </div>

      <div v-else-if="material.description" class="card">
        <div class="card-title">Description</div>
        <div class="card-text">{{ material.description }}</div>
      </div>

      <div v-if="!editing && material.notes" class="card">
        <div class="card-title">Notes</div>
        <div class="card-text">{{ material.notes }}</div>
      </div>

      <div class="card">
        <div class="card-title" style="margin-bottom: 14px">Composants</div>
        <div v-if="decoratedComponents.length > 0" class="tree">
          <div v-for="c in decoratedComponents" :key="c.id" class="tree-item">
            <RouterLink :to="`/materiel/${c.id}`" class="tree-item__body">
              <div class="tree-item__name">{{ c.name }}</div>
              <div class="tree-item__meta">{{ c.venue_name ?? 'Sans lieu' }}</div>
            </RouterLink>
            <div class="badge" :style="{ color: c.ownColor, background: c.ownBg }">{{ c.ownLabel }}</div>
          </div>
        </div>
        <div v-else class="row-empty">Aucun composant.</div>
      </div>

      <div class="card">
        <div class="card-title" style="margin-bottom: 14px">Assignations actuelles</div>
        <div v-if="decoratedAssignments.length > 0" class="row-list">
          <div v-for="a in decoratedAssignments" :key="a.id" class="row">
            <span class="row__dot" :style="{ background: a.conflict ? 'oklch(0.7 0.16 35)' : 'oklch(0.72 0.13 165)' }" />
            <div class="row__body">
              <div class="row__title">
                {{ a.show_title }}<span v-if="a.quantity > 1"> ×{{ a.quantity }}</span>
              </div>
              <RouterLink :to="`/spectacles/${a.show}`" class="row__link">Voir le spectacle →</RouterLink>
            </div>
            <div v-if="a.conflict" class="row__conflict">CONFLIT</div>
          </div>
        </div>
        <div v-else class="row-empty">Aucune assignation en cours.</div>
      </div>
    </div>
  </AppShell>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 20px;
  max-width: 920px;
}

.hint {
  padding: 32px 40px;
  font: 500 13px system-ui;
  color: rgba(255, 255, 255, 0.5);
}

.hint--error {
  color: oklch(0.78 0.16 35);
}

.breadcrumb {
  font: 500 12px system-ui;
  color: rgba(255, 255, 255, 0.4);
}

.breadcrumb :deep(a) {
  color: #a5b4fc;
  text-decoration: none;
}

.header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
}

.header__top {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header__dot {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  flex: none;
}

.header__meta {
  font: 400 13px system-ui;
  color: rgba(255, 255, 255, 0.5);
  margin-top: 6px;
}

.header__badge {
  font: 700 10px system-ui;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 6px 12px;
  border-radius: var(--radius-notch-sm);
}

.header__badge--inactive {
  color: rgba(255, 255, 255, 0.5);
  background: rgba(255, 255, 255, 0.08);
}

.card {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-notch-lg);
  padding: 20px;
}

.card-title {
  font: 700 12px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: rgba(255, 255, 255, 0.65);
}

.card-text {
  font: 400 13.5px/1.6 system-ui;
  color: rgba(255, 255, 255, 0.75);
  margin-top: 14px;
}

.tree {
  position: relative;
  margin-left: 18px;
  padding-left: 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-left: 2px solid rgba(155, 138, 239, 0.25);
}

.tree-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: var(--radius-notch-sm);
  background: #1b1f25;
}

.tree-item::before {
  content: '';
  position: absolute;
  left: -20px;
  top: 50%;
  width: 14px;
  height: 2px;
  background: rgba(155, 138, 239, 0.25);
}

.tree-item__body {
  flex: 1;
  min-width: 0;
  text-decoration: none;
}

.tree-item__name {
  font: 600 13px system-ui;
  color: #fff;
}

.tree-item__meta {
  font: 400 11.5px system-ui;
  color: rgba(255, 255, 255, 0.5);
}

.badge {
  font: 700 10px system-ui;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 2px 8px;
  border-radius: 0 6px 0 6px;
  flex: none;
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
  background: #1b1f25;
}

.row__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
}

.row__body {
  flex: 1;
  min-width: 0;
}

.row__title {
  font: 600 13px system-ui;
  color: #fff;
}

.row__link {
  font: 400 11.5px system-ui;
  color: #a5b4fc;
  text-decoration: none;
}

.row__conflict {
  font: 700 10px system-ui;
  color: oklch(0.85 0.13 35);
  background: oklch(0.7 0.16 35 / 0.18);
  padding: 2px 8px;
  border-radius: 0 10px 0 10px;
}

.row-empty {
  font: 500 12.5px system-ui;
  color: rgba(255, 255, 255, 0.4);
  padding: 10px 12px;
}
</style>

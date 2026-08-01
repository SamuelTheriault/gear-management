<script setup>
import { ref, computed, watch } from 'vue'
import AppShell from '../components/AppShell.vue'
import { api } from '../api/client'
import { useActiveProject } from '../composables/useActiveProject'

/**
 * Liste du matériel — port de Materiel.dc.html, branché sur l'API réelle
 * (/api/materials/, /api/venues/) plutôt que sur les données de démonstration
 * du prototype. Voir schema.md section 4 pour les champs de `Material`
 * (hiérarchie parent/enfant via `parent_material`, `ownership_status` =
 * owned/rental) et section 13 pour `MaterialCategory` — `category` est une FK
 * vers une catégorie éditable depuis le 2026-07-30, plus une liste de choix
 * figée.
 *
 * Le champ `department` (et l'écran Départements) a été retiré le 2026-07-29
 * à la demande de Samuel — `category` suffit à classer le matériel, sans le
 * doublon contact/couleur d'un référentiel séparé.
 *
 * Le mode "Réorganiser" du prototype (drag & drop) n'a pas d'équivalent
 * persisté côté backend (aucun champ d'ordre sur `Material`) — omis ici plutôt
 * que de simuler un réordonnancement qui se perdrait au rechargement. À
 * confirmer avec Samuel si un vrai champ d'ordre est souhaité plus tard.
 */

const { activeProjectId } = useActiveProject()

const materials = ref([])
const venues = ref([])
const loading = ref(false)
const loadError = ref(null)

// Les catégories viennent de l'API depuis le 2026-07-30 (table
// MaterialCategory, une liste par projet) — elles étaient codées en dur ici,
// libellés ET couleurs, tant qu'elles étaient une liste de choix figée côté
// modèle Django. Gérées dans /materiel/categories.
const categories = ref([])

const NO_CATEGORY = { label: 'Sans catégorie', color: 'rgba(255,255,255,.3)' }

const ownershipMeta = {
  owned: { label: 'Propriété', color: 'oklch(0.72 0.13 165)', bg: 'oklch(0.72 0.13 165 / .16)' },
  rental: { label: 'Location', color: 'oklch(0.8 0.13 85)', bg: 'oklch(0.8 0.13 85 / .16)' },
}

async function loadMaterials() {
  if (!activeProjectId.value) return
  loading.value = true
  loadError.value = null
  try {
    const [materialsData, venuesData, categoriesData] = await Promise.all([
      api.get('/materials/', { project: activeProjectId.value }),
      api.get('/venues/', { project: activeProjectId.value }),
      api.get('/material-categories/', { project: activeProjectId.value }),
    ])
    materials.value = Array.isArray(materialsData) ? materialsData : (materialsData.results ?? [])
    venues.value = Array.isArray(venuesData) ? venuesData : (venuesData.results ?? [])
    categories.value = Array.isArray(categoriesData) ? categoriesData : (categoriesData.results ?? [])
  } catch (e) {
    loadError.value = e
  } finally {
    loading.value = false
  }
}

watch(activeProjectId, loadMaterials, { immediate: true })

// --- Hiérarchie parent/enfant ---

const topLevel = computed(() => materials.value.filter((m) => !m.parent_material))
const childrenByParent = computed(() => {
  const map = new Map()
  materials.value.forEach((m) => {
    if (m.parent_material) {
      if (!map.has(m.parent_material)) map.set(m.parent_material, [])
      map.get(m.parent_material).push(m)
    }
  })
  return map
})

const expanded = ref({})
function toggle(id) {
  expanded.value = { ...expanded.value, [id]: !expanded.value[id] }
}

const decorated = computed(() =>
  topLevel.value.map((m) => {
    // `category_name`/`category_color` sont dupliqués en lecture seule par
    // MaterialSerializer : pas besoin de croiser avec la liste des catégories.
    const meta = m.category
      ? { label: m.category_name, color: m.category_color }
      : NO_CATEGORY
    const own = ownershipMeta[m.ownership_status] ?? ownershipMeta.owned
    const children = childrenByParent.value.get(m.id) ?? []
    return {
      ...m,
      catLabel: meta.label,
      catColor: meta.color,
      ownLabel: own.label,
      ownColor: own.color,
      ownBg: own.bg,
      childCount: children.length,
      children,
      hasChildren: children.length > 0,
      isExpanded: !!expanded.value[m.id],
    }
  }),
)

const selectedCategory = ref('Tous')

const categoryFilters = computed(() => {
  // Seules les catégories réellement présentes dans l'inventaire deviennent
  // des filtres. Testé dans les deux sens le 2026-07-30 : tout afficher
  // remplissait la barre de puces qui ne mènent nulle part. Le référentiel
  // complet se consulte dans /materiel/categories.
  const present = new Set(topLevel.value.map((m) => m.category).filter(Boolean))
  const chips = ['Tous', ...categories.value.filter((c) => present.has(c.id)).map((c) => c.name)]
  return chips.map((label) => ({
    label,
    active: selectedCategory.value === label,
    select: () => (selectedCategory.value = label),
  }))
})

const filtered = computed(() =>
  decorated.value.filter(
    (m) => selectedCategory.value === 'Tous' || m.catLabel === selectedCategory.value,
  ),
)

// --- Ajout rapide de matériel ---

const form = ref({
  name: '',
  category: '',
  venue: '',
  ownership_status: 'owned',
  quantity: 1,
})
const formError = ref(null)
const nameError = ref(false)
// Le lieu d'origine est obligatoire depuis le 2026-07-30 : sans point de
// départ, la timeline de position ne peut ni vérifier la disponibilité au
// départ d'un transport, ni le retour en fin de projet.
const venueError = ref(false)
const submitting = ref(false)

const canSubmit = computed(
  () => form.value.name.trim().length > 0 && !!form.value.venue && !submitting.value,
)

async function addMaterial() {
  formError.value = null
  const name = form.value.name.trim()
  if (!name) {
    nameError.value = true
    return
  }
  if (!form.value.venue) {
    venueError.value = true
    return
  }
  submitting.value = true
  try {
    await api.post('/materials/', {
      project: activeProjectId.value,
      name,
      category: form.value.category || null,
      venue: form.value.venue,
      ownership_status: form.value.ownership_status,
      quantity: form.value.quantity,
    })
    form.value = { name: '', category: '', venue: '', ownership_status: 'owned', quantity: 1 }
    nameError.value = false
    await loadMaterials()
  } catch (e) {
    formError.value = e.data?.detail ?? "Impossible d'enregistrer le matériel."
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <AppShell>
    <div class="page">
      <div class="page-header">
        <h1 class="page-title">Matériel</h1>
        <div class="page-count">{{ filtered.length }} item(s)</div>
      </div>

      <div class="filters">
        <div
          v-for="f in categoryFilters"
          :key="f.label"
          class="chip"
          :class="{ 'chip--active': f.active }"
          @click="f.select"
        >
          {{ f.label }}
        </div>
      </div>

      <div v-if="loading" class="hint">Chargement…</div>
      <div v-else-if="loadError" class="hint hint--error">
        Impossible de charger le matériel. Es-tu connecté (session Django) ?
      </div>

      <template v-else>
        <div v-if="filtered.length > 0" class="kit-list">
          <div v-for="kit in filtered" :key="kit.id" class="kit">
            <div class="kit-row" @click="kit.hasChildren && toggle(kit.id)">
              <span
                v-if="kit.hasChildren"
                class="kit-chevron"
                :class="{ 'kit-chevron--open': kit.isExpanded }"
                :style="{ '--chevron-color': kit.isExpanded ? 'rgba(255,255,255,.4)' : kit.catColor }"
              />
              <span v-else class="kit-chevron-spacer" />
              <span class="kit-dot" :style="{ background: kit.catColor }" />
              <div class="kit-body">
                <div class="kit-name">{{ kit.name }}</div>
                <div class="kit-meta">
                  {{ kit.catLabel }} ·
                  {{ kit.venue_name ?? '—' }} ·
                  {{ kit.childCount }} composant(s)
                </div>
              </div>
              <div class="kit-badge" :style="{ color: kit.ownColor, background: kit.ownBg }">
                {{ kit.ownLabel }}
              </div>
              <RouterLink :to="`/materiel/${kit.id}`" class="kit-link" @click.stop>Voir la fiche →</RouterLink>
            </div>
            <div v-if="kit.isExpanded" class="kit-children">
              <div v-for="c in kit.children" :key="c.id" class="kit-child">
                <div class="kit-child-body">
                  <div class="kit-child-name">{{ c.name }}</div>
                  <div class="kit-child-meta">{{ c.venue_name ?? 'Sans lieu' }}</div>
                </div>
                <div
                  class="kit-badge kit-badge--small"
                  :style="{ color: ownershipMeta[c.ownership_status]?.color ?? ownershipMeta.owned.color, background: ownershipMeta[c.ownership_status]?.bg ?? ownershipMeta.owned.bg }"
                >
                  {{ ownershipMeta[c.ownership_status]?.label ?? ownershipMeta.owned.label }}
                </div>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="empty">
          <div class="empty__icon" />
          <div class="empty__title">Aucun matériel dans cette catégorie</div>
        </div>
      </template>

      <div class="add-form">
        <div class="add-form__title">Ajouter du matériel</div>
        <div class="add-form__row">
          <label class="add-form__field add-form__field--wide">
            <span class="add-form__label">Nom du matériel</span>
            <input
              v-model="form.name"
              placeholder="ex. Console Yamaha CL5"
              class="add-form__input"
              :class="{ 'add-form__input--error': nameError }"
              @input="nameError = false"
            />
          </label>
          <label class="add-form__field">
            <span class="add-form__label">Catégorie</span>
            <select v-model="form.category" class="add-form__input">
              <option value="">Sans catégorie</option>
              <option v-for="c in categories" :key="c.id" :value="c.id">{{ c.name }}</option>
            </select>
          </label>
          <label class="add-form__field">
            <span class="add-form__label">Lieu d'origine *</span>
            <select
              v-model="form.venue"
              class="add-form__input"
              :class="{ 'add-form__input--error': venueError }"
              @change="venueError = false"
            >
              <option value="" disabled>Choisir un lieu…</option>
              <option v-for="v in venues" :key="v.id" :value="v.id">{{ v.name }}</option>
            </select>
          </label>
          <label class="add-form__field">
            <span class="add-form__label">Propriété</span>
            <select v-model="form.ownership_status" class="add-form__input">
              <option value="owned">Propriété</option>
              <option value="rental">Location</option>
            </select>
          </label>
          <label class="add-form__field add-form__field--narrow">
            <span class="add-form__label">Quantité</span>
            <input
              v-model.number="form.quantity"
              type="number"
              min="1"
              class="add-form__input"
            />
          </label>
          <div
            class="add-form__submit"
            :class="{ 'add-form__submit--disabled': !canSubmit }"
            @click="canSubmit && addMaterial()"
          >
            + Ajouter
          </div>
        </div>
        <div v-if="nameError" class="add-form__error">Le nom du matériel est requis.</div>
        <div v-if="venueError" class="add-form__error">
          Le lieu d'origine est requis — c'est là que le matériel doit revenir en fin de projet.
        </div>
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
  color: rgba(255, 255, 255, 0.4);
}

.filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.hint {
  font: 500 13px system-ui;
  color: rgba(255, 255, 255, 0.5);
}

.hint--error {
  color: oklch(0.78 0.16 35);
}

.kit-list {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-notch-lg);
  padding: 8px;
  display: flex;
  flex-direction: column;
}

.kit-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  cursor: pointer;
  border-radius: var(--radius-notch-sm);
}

.kit-chevron {
  width: 20px;
  height: 20px;
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.15s;
}

.kit-chevron::before {
  content: '';
  width: 0;
  height: 0;
  border-style: solid;
  border-width: 5px 0 5px 7px;
  border-color: transparent transparent transparent var(--chevron-color, rgba(255, 255, 255, 0.4));
}

.kit-chevron--open {
  transform: rotate(90deg);
}

.kit-chevron-spacer {
  width: 20px;
  flex: none;
}

.kit-dot {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  flex: none;
}

.kit-body {
  flex: 1;
  min-width: 0;
}

.kit-name {
  font: 600 14px var(--font-mono);
  color: #fff;
}

.kit-meta {
  font: 400 11.5px system-ui;
  color: rgba(255, 255, 255, 0.5);
}

.kit-badge {
  font: 700 10px system-ui;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 3px 9px;
  border-radius: 0 6px 0 6px;
  white-space: nowrap;
}

.kit-badge--small {
  font-size: 9.5px;
  padding: 2px 8px;
}

.kit-link {
  font: 600 11px system-ui;
  color: #a5b4fc;
  cursor: pointer;
  white-space: nowrap;
  flex: none;
  text-decoration: none;
}

.kit-children {
  position: relative;
  margin-left: 18px;
  padding-left: 20px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 4px;
  padding-top: 2px;
  padding-bottom: 4px;
}

.kit-child {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 0 6px 0 6px;
  background: #1b1f25;
}

.kit-child::before {
  content: '';
  position: absolute;
  left: -20px;
  top: 50%;
  width: 14px;
  height: 2px;
  background: rgba(155, 138, 239, 0.25);
}

.kit-child::after {
  /* Trait vertical de raccordement : couvre la moitié du gap au-dessus et
     en dessous pour rester continu d'un enfant à l'autre. Le dernier enfant
     s'arrête à sa propre branche horizontale (top:50%) plutôt que de
     continuer dans le padding-bottom du conteneur. */
  content: '';
  position: absolute;
  left: -20px;
  top: -2px;
  bottom: -2px;
  width: 2px;
  background: rgba(155, 138, 239, 0.25);
}

.kit-child:first-child::after {
  top: 0;
}

.kit-child:last-child::after {
  bottom: 50%;
}

.kit-child-body {
  flex: 1;
  min-width: 0;
}

.kit-child-name {
  font: 500 12.5px system-ui;
  color: rgba(255, 255, 255, 0.85);
}

.kit-child-meta {
  font: 400 11px system-ui;
  color: rgba(255, 255, 255, 0.4);
}

.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 64px 20px;
  background: var(--bg-card);
  border: 1px dashed rgba(255, 255, 255, 0.15);
  border-radius: var(--radius-notch-lg);
}

.empty__icon {
  width: 40px;
  height: 40px;
  border-radius: 0 10px 0 10px;
  background: rgba(255, 255, 255, 0.06);
}

.empty__title {
  font: 600 13px system-ui;
  color: rgba(255, 255, 255, 0.6);
}

/* Chaque champ est maintenant un <label> qui porte le dimensionnement flex,
   l'input en dessous prenant toute la largeur disponible. */

</style>

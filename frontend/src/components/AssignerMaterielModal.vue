<script setup>
import { ref, computed, reactive, onMounted } from 'vue'
import { api } from '../api/client'

/**
 * Modale « Assigner du matériel » — port de AssignationMateriel.dc.html.
 *
 * Réécrite le 2026-07-30 (à la demande de Samuel, pour unifier l'affichage
 * avec la modale « Ajouter du matériel » de TransportDetailView.vue) : liste
 * à cocher de tout le catalogue disponible, avec une quantité modifiable à
 * droite de chaque ligne, plutôt qu'un unique <select> + un item à la fois.
 * Fenêtre agrandie pour voir le plus d'éléments possible sans défiler.
 *
 * Différence structurelle avec Transport : `Transport` a un champ imbriqué
 * `materials` (écrit en un seul PATCH), donc sa modale ne fait que du
 * staging local. `ShowMaterial` n'a pas d'équivalent bulk côté API — chaque
 * ligne cochée devient un POST /api/show-materials/ séparé au clic sur
 * « Assigner ». Les lignes qui réussissent disparaissent de la liste
 * (`submittedIds`) ; celles qui échouent par conflit (bloquant + `force`,
 * voir ShowMaterialSerializer.validate()) restent affichées avec le détail
 * du conflit et un bouton « Forcer » groupé au pied de la modale ; celles qui
 * échouent pour une autre raison (quantité > stock, projet différent — pas
 * overridable) affichent l'erreur sous la ligne, à corriger avant de
 * ressoumettre.
 *
 * La « location ponctuelle » (is_rental/rental_vendor, propre à
 * ShowMaterial — n'existe pas sur Transport) reste disponible, révélée sous
 * forme de toggle + champ fournisseur uniquement pour les lignes cochées.
 *
 * Matériel déjà assigné (2026-07-30, suite, demande de Samuel) : au lieu
 * d'être masqué, il reste visible dans la liste — verrouillé (case cochée
 * grisée, quantité affichée en lecture seule, pas de toggle location) — pour
 * voir tout le catalogue d'un coup d'œil sans changer d'écran. Le prop
 * `assignedMaterialIds` (juste des ids) est remplacé par `assignedMaterials`
 * (objets `{material, quantity}` du `ShowMaterial` réel, pour afficher la
 * quantité déjà assignée). Une ligne qu'on vient d'assigner dans CETTE
 * session (`submittedQty`) passe au même état assigné immédiatement,
 * plutôt que de disparaître — cohérent avec l'idée de tout voir d'un coup.
 *
 * Sélection en cascade (2026-07-30, suite) : cocher un kit (matériel parent)
 * coche automatiquement ses composants — on emporte rarement un kit sans son
 * contenu. Décocher le kit les décoche à son tour ; entre les deux, chaque
 * composant se décoche individuellement. Les composants déjà assignés au
 * spectacle ne sont jamais touchés par la cascade. Assigner le kit ET ses
 * composants au même spectacle n'est PAS un conflit de hiérarchie :
 * `get_material_conflicts` exclut explicitement le spectacle courant de ses
 * candidats (conflicts.py).
 *
 * Décochage = retrait (2026-07-30, suite) : décocher une ligne déjà assignée
 * la marque à retirer (barrée), et « Appliquer » exécute les retraits
 * (`DELETE /api/show-materials/{id}/`) AVANT les ajouts — libérer du matériel
 * peut lever le conflit de capacité qui bloquerait un ajout dans la même
 * fournée. Rien ne part avant la validation : décocher par erreur se rattrape
 * en recochant. C'est aussi pour ça que le prop porte les objets
 * `ShowMaterial` complets et pas juste des ids — le DELETE a besoin de leur
 * `id`.
 */

const props = defineProps({
  showId: { type: [Number, String], required: true },
  projectId: { type: [Number, String], required: true },
  showLabel: { type: String, default: '' },
  assignedMaterials: { type: Array, default: () => [] },
})

const emit = defineEmits(['close', 'assigned'])

// Nom et couleur de catégorie viennent de l'API depuis le 2026-07-30
// (`category_name`/`category_color` sur MaterialSerializer — voir
// MaterialCategory) : plus de table de correspondance codée en dur ici.
const NO_CATEGORY = { label: 'Sans catégorie', color: 'rgba(255,255,255,.3)' }

function categoryOf(material) {
  return material?.category
    ? { label: material.category_name, color: material.category_color }
    : NO_CATEGORY
}

const loading = ref(true)
const materials = ref([])
const saving = ref(false)
const formError = ref(null)

const catalogQty = ref({})
const rentalOn = ref({})
const rentalVendor = ref({})
const rowErrors = reactive({})
const pendingConflicts = ref([]) // [{ materialId, name, quantity, isRental, rentalVendor, detail }]
const submittedQty = ref({}) // matériel assigné avec succès pendant cette session de la modale
// Matériel déjà assigné qu'on vient de décocher : marqué à retirer, appliqué
// seulement à la validation (2026-07-30, demande de Samuel).
const removedIds = ref([])

const assignedByMaterial = computed(() => new Map(props.assignedMaterials.map((sm) => [sm.material, sm])))

const assignedQtyByMaterial = computed(
  () => new Map(props.assignedMaterials.map((sm) => [sm.material, sm.quantity])),
)

function lockedQty(materialId) {
  // Une ligne marquée à retirer n'est plus « verrouillée » : elle s'affiche
  // décochée et barrée jusqu'à ce qu'on applique.
  if (removedIds.value.includes(materialId)) return null
  return assignedQtyByMaterial.value.get(materialId) ?? submittedQty.value[materialId] ?? null
}

function isAssigned(materialId) {
  return assignedByMaterial.value.has(materialId) || submittedQty.value[materialId] != null
}

// Filtre par catégorie (2026-07-30, suite) : puces générées à partir des
// catégories réellement présentes dans le catalogue du projet — même esprit
// que MaterielView.vue (« Tous » + seulement les catégories utilisées).
const selectedCategory = ref('all')

const categoryChips = computed(() => {
  const seen = new Map()
  materials.value.forEach((m) => {
    const key = m.category ?? 'none'
    if (!seen.has(key)) seen.set(key, categoryOf(m))
  })
  const sorted = [...seen.entries()].sort((a, b) => a[1].label.localeCompare(b[1].label, 'fr'))
  return [
    { key: 'all', label: 'Tous', active: selectedCategory.value === 'all', select: () => (selectedCategory.value = 'all') },
    ...sorted.map(([key, meta]) => ({
      key,
      label: meta.label,
      active: selectedCategory.value === key,
      select: () => (selectedCategory.value = key),
    })),
  ]
})

// --- Sélection en cascade des kits (2026-07-30, demande de Samuel) ---
// Cocher un kit coche aussi ses composants : dans la pratique, on emporte le
// kit complet. Chaque composant reste décochable individuellement ensuite —
// c'est tout l'intérêt de les cocher plutôt que de les assigner en bloc
// silencieusement.

const childrenByParent = computed(() => {
  const map = new Map()
  materials.value.forEach((m) => {
    if (!m.parent_material) return
    if (!map.has(m.parent_material)) map.set(m.parent_material, [])
    map.get(m.parent_material).push(m)
  })
  return map
})

function toggleSelect(m) {
  const current = catalogQty.value[m.id] || 0
  const next = current > 0 ? 0 : 1
  const updates = { [m.id]: next }

  // Composants du kit : on suit le parent, sans jamais toucher à ceux qui
  // sont déjà assignés au spectacle (ils ne sont pas pilotés par cette case).
  ;(childrenByParent.value.get(m.id) ?? []).forEach((child) => {
    if (isAssigned(child.id)) return
    updates[child.id] = next
  })

  catalogQty.value = { ...catalogQty.value, ...updates }
}

function toggleRow(m) {
  // Ligne déjà assignée : le clic bascule entre « garder » et « retirer ».
  if (isAssigned(m.id)) {
    removedIds.value = removedIds.value.includes(m.id)
      ? removedIds.value.filter((id) => id !== m.id)
      : [...removedIds.value, m.id]
    return
  }
  toggleSelect(m)
}

function setQty(m, v) {
  catalogQty.value = { ...catalogQty.value, [m.id]: Math.max(0, Math.min(Number(v) || 0, m.quantity)) }
}

function incQty(m) {
  const current = catalogQty.value[m.id] || 0
  catalogQty.value = { ...catalogQty.value, [m.id]: Math.min(current + 1, m.quantity) }
}

function decQty(m) {
  const current = catalogQty.value[m.id] || 0
  catalogQty.value = { ...catalogQty.value, [m.id]: Math.max(current - 1, 0) }
}

// Ordonne la liste comme l'inventaire général (MaterielView) : chaque
// composant suit immédiatement son kit, et non l'ordre alphabétique brut.
// Un composant dont le parent est masqué par le filtre de catégorie reste
// affiché, au premier niveau — mieux vaut le montrer orphelin que le perdre.
function orderByKit(list) {
  const visibleIds = new Set(list.map((m) => m.id))
  const enfants = new Map()
  list.forEach((m) => {
    if (m.parent_material == null || !visibleIds.has(m.parent_material)) return
    if (!enfants.has(m.parent_material)) enfants.set(m.parent_material, [])
    enfants.get(m.parent_material).push(m)
  })

  const ordonne = []
  list.forEach((m) => {
    if (m.parent_material != null && visibleIds.has(m.parent_material)) return
    ordonne.push(m)
    ;(enfants.get(m.id) ?? []).forEach((child) => ordonne.push(child))
  })
  return ordonne
}

const catalogRows = computed(() =>
  orderByKit(
    materials.value
      .filter((m) => selectedCategory.value === 'all' || (m.category ?? 'none') === selectedCategory.value),
  )
    .map((m) => {
    const locked = lockedQty(m.id)
    const qty = catalogQty.value[m.id] || 0
    return {
      id: m.id,
      name: m.name,
      meta: categoryOf(m),
      stock: m.quantity,
      qty,
      lockedQty: locked,
      selected: locked == null && qty > 0,
      rentalOn: !!rentalOn.value[m.id],
      rentalVendor: rentalVendor.value[m.id] || '',
      error: rowErrors[m.id] || null,
      pending: pendingConflicts.value.find((c) => c.materialId === m.id) || null,
      setQty: (v) => setQty(m, v),
      inc: () => incQty(m),
      dec: () => decQty(m),
      removed: removedIds.value.includes(m.id),
      // Nombre de composants, pour annoncer la cascade dans la liste.
      childCount: (childrenByParent.value.get(m.id) ?? []).length,
      // `nested` : affiché en retrait sous son kit (le parent est visible dans
      // la liste courante). Un composant orphelin — parent masqué par le
      // filtre — reste au premier niveau.
      isChild: m.parent_material != null,
      nested: m.parent_material != null && visibleIds.value.has(m.parent_material),
      toggle: () => toggleRow(m),
      toggleRental: () => {
        rentalOn.value = { ...rentalOn.value, [m.id]: !rentalOn.value[m.id] }
      },
      setVendor: (v) => {
        rentalVendor.value = { ...rentalVendor.value, [m.id]: v }
      },
    }
  }),
)

const visibleIds = computed(
  () => new Set(
    materials.value
      .filter((m) => selectedCategory.value === 'all' || (m.category ?? 'none') === selectedCategory.value)
      .map((m) => m.id),
  ),
)

const selectedCount = computed(() => catalogRows.value.filter((r) => r.selected).length)
const removeCount = computed(() => removedIds.value.length)
const hasChanges = computed(() => selectedCount.value + removeCount.value > 0)

onMounted(async () => {
  loading.value = true
  try {
    const data = await api.get('/materials/', { project: props.projectId })
    materials.value = Array.isArray(data) ? data : (data.results ?? [])
  } finally {
    loading.value = false
  }
})

function buildPayload(materialId, quantity, isRental, vendor, force) {
  return {
    show: props.showId,
    material: materialId,
    quantity,
    is_rental: isRental,
    rental_vendor: isRental ? (vendor?.trim() || null) : null,
    force,
  }
}

// Vrai dès qu'un retrait a réellement été appliqué : le parent doit recharger
// même si aucun ajout n'a été fait.
const removedApplied = ref(false)

function maybeFinish() {
  const stillBlocked = pendingConflicts.value.length > 0 || Object.values(rowErrors).some(Boolean)
  const didSomething = Object.keys(submittedQty.value).length > 0 || removedApplied.value
  if (!stillBlocked && didSomething) emit('assigned')
}

async function submitAll() {
  formError.value = null
  // Les lignes déjà assignées (verrouillées) ou déjà en conflit en attente
  // ne sont pas ressoumises ici — le conflit se règle via « Forcer ».
  const targets = materials.value.filter(
    (m) =>
      lockedQty(m.id) == null &&
      !removedIds.value.includes(m.id) &&
      (catalogQty.value[m.id] || 0) > 0 &&
      !pendingConflicts.value.some((c) => c.materialId === m.id),
  )
  if (targets.length === 0 && removedIds.value.length === 0) {
    formError.value = 'Sélectionne au moins un matériel.'
    return
  }
  saving.value = true

  // Retraits d'abord : libérer du matériel peut lever le conflit de capacité
  // qui bloquerait un ajout dans la même fournée.
  for (const materialId of [...removedIds.value]) {
    const assignment = assignedByMaterial.value.get(materialId)
    rowErrors[materialId] = null
    if (!assignment) {
      // Assigné pendant cette session : on ne connaît pas l'id du
      // ShowMaterial, le rechargement du parent fera foi.
      removedIds.value = removedIds.value.filter((id) => id !== materialId)
      continue
    }
    try {
      await api.delete(`/show-materials/${assignment.id}/`)
      removedIds.value = removedIds.value.filter((id) => id !== materialId)
      removedApplied.value = true
    } catch (e) {
      rowErrors[materialId] = e.data?.detail ?? 'Impossible de retirer ce matériel.'
    }
  }
  const newConflicts = []
  for (const m of targets) {
    const quantity = catalogQty.value[m.id]
    const isRental = !!rentalOn.value[m.id]
    const vendor = rentalVendor.value[m.id] || ''
    rowErrors[m.id] = null
    try {
      await api.post('/show-materials/', buildPayload(m.id, quantity, isRental, vendor, false))
      submittedQty.value = { ...submittedQty.value, [m.id]: quantity }
    } catch (e) {
      if (e.data?.conflicts) {
        newConflicts.push({ materialId: m.id, name: m.name, quantity, isRental, rentalVendor: vendor, detail: e.data.detail })
      } else {
        rowErrors[m.id] =
          e.data?.quantity?.[0] ?? e.data?.material?.[0] ?? e.data?.detail ?? "Impossible d'assigner ce matériel."
      }
    }
  }
  if (newConflicts.length) pendingConflicts.value = [...pendingConflicts.value, ...newConflicts]
  saving.value = false
  maybeFinish()
}

async function forcePendingConflicts() {
  saving.value = true
  const remaining = []
  for (const c of pendingConflicts.value) {
    try {
      await api.post('/show-materials/', buildPayload(c.materialId, c.quantity, c.isRental, c.rentalVendor, true))
      submittedQty.value = { ...submittedQty.value, [c.materialId]: c.quantity }
    } catch (e) {
      remaining.push(c)
    }
  }
  pendingConflicts.value = remaining
  saving.value = false
  maybeFinish()
}
</script>

<template>
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="modal">
      <div class="modal__header">
        <div class="modal__title">Assigner du matériel</div>
        <div class="modal__close" @click="emit('close')">×</div>
      </div>
      <div class="modal__context">{{ showLabel }}</div>
      <div class="modal__hint">
        Coche pour assigner, décoche pour retirer. Rien n'est appliqué avant la validation.
      </div>

      <div v-if="loading" class="hint">Chargement du catalogue…</div>
      <template v-else>
        <div v-if="materials.length === 0" class="hint">
          Aucun matériel dans le catalogue de ce projet.
        </div>
        <template v-else>
          <div class="filters">
            <div
              v-for="f in categoryChips"
              :key="f.key"
              class="chip"
              :class="{ 'chip--active': f.active }"
              @click="f.select"
            >
              {{ f.label }}
            </div>
          </div>
          <div class="modal__body">
            <div
              v-for="r in catalogRows"
              :key="r.id"
              class="catalog-row"
              :class="{
                'catalog-row--selected': r.selected,
                'catalog-row--locked': r.lockedQty != null,
                'catalog-row--removed': r.removed,
                'catalog-row--nested': r.nested,
              }"
            >
              <div
                class="catalog-row__check"
                :class="{ 'catalog-row__check--on': r.selected || r.lockedQty != null }"
                @click="r.toggle"
              >
                <span v-if="r.selected || r.lockedQty != null">✓</span>
              </div>
              <span class="catalog-row__dot" :style="{ background: r.meta.color }" />
              <div class="catalog-row__info">
                <div class="catalog-row__name">{{ r.name }}</div>
                <div class="catalog-row__stock">
                  <span v-if="r.isChild" class="catalog-row__child">Composant</span>
                  <span v-if="r.childCount > 0" class="catalog-row__kit">
                    Kit · {{ r.childCount }} composant(s)
                  </span>
                  <span v-if="r.removed" class="catalog-row__removed">À retirer</span>
                  <span v-else-if="r.lockedQty != null">Déjà assigné · ×{{ r.lockedQty }}</span>
                  <span v-else>{{ r.meta.label }} · {{ r.stock }} disponible(s)</span>
                </div>
                <div v-if="r.selected" class="catalog-row__rental">
                  <label class="catalog-row__rental-toggle">
                    <input type="checkbox" :checked="r.rentalOn" @change="r.toggleRental" />
                    Location ponctuelle
                  </label>
                  <input
                    v-if="r.rentalOn"
                    type="text"
                    class="catalog-row__vendor"
                    placeholder="Fournisseur"
                    :value="r.rentalVendor"
                    @input="r.setVendor($event.target.value)"
                  />
                </div>
                <div v-if="r.error" class="catalog-row__error">{{ r.error }}</div>
                <div v-if="r.pending" class="catalog-row__conflict">{{ r.pending.detail }}</div>
              </div>
              <div v-if="r.lockedQty == null" class="catalog-row__qty">
                <div class="qty-btn" @click="r.dec">−</div>
                <input type="number" class="qty-input" :value="r.qty" @input="r.setQty($event.target.value)" />
                <div class="qty-btn" @click="r.inc">+</div>
              </div>
            </div>
          </div>

          <div v-if="formError" class="error">{{ formError }}</div>
        </template>
      </template>

      <div class="modal__footer">
        <div class="modal__count">
          {{ selectedCount }} à assigner<template v-if="removeCount > 0"> · {{ removeCount }} à retirer</template>
        </div>
        <div class="btn btn--ghost" @click="emit('close')">Annuler</div>
        <div
          v-if="pendingConflicts.length"
          class="btn btn--force"
          :class="{ 'btn--disabled': saving }"
          @click="!saving && forcePendingConflicts()"
        >
          Forcer {{ pendingConflicts.length }} conflit{{ pendingConflicts.length > 1 ? 's' : '' }}
        </div>
        <div
          class="btn btn--primary"
          :class="{ 'btn--disabled': saving || !hasChanges }"
          @click="!saving && hasChanges && submitAll()"
        >
          Appliquer
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>

.modal {
  width: min(640px, 94vw);
  /* Hauteur FIXE et non `max-height` (2026-07-30, demande de Samuel) : la
     modale garde la même taille et la même position quel que soit le nombre
     de lignes. Avec `max-height` seul, une liste courte faisait remonter le
     pied de page et « sauter » la modale d'une ouverture à l'autre. */
  height: 85vh;
  max-height: 85vh;
  background: var(--bg-card);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 0 14px 0 14px;
  padding: 22px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.modal__title {
  font: 700 15px var(--font-mono);
  letter-spacing: 0.03em;
  color: #fff;
}

.modal__close {
  font: 400 20px system-ui;
  color: rgba(255, 255, 255, 0.5);
  cursor: pointer;
  line-height: 1;
}

.modal__context {
  font: 500 12px system-ui;
  color: rgba(255, 255, 255, 0.5);
  margin-top: -8px;
}

.filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.modal__body {
  /* `flex: 1` + `min-height: 0` : le corps absorbe toute la hauteur restante
     et défile, l'entête et le pied restent à leur place. */
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.hint {
  font: 500 12.5px system-ui;
  color: rgba(255, 255, 255, 0.5);
  padding: 8px 0;
}

.catalog-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 6px 12px;
  border-radius: var(--radius-notch-sm);
  background: #1b1f25;
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.catalog-row--selected {
  border-color: rgba(155, 138, 239, 0.35);
}

/* Composant affiché en retrait sous son kit, avec le trait de raccordement —
   même lecture que l'arborescence de l'inventaire général (MaterielView). */
.catalog-row--nested {
  position: relative;
  margin-left: 26px;
  border-left: 2px solid rgba(155, 138, 239, 0.25);
}

.catalog-row--nested::before {
  content: '';
  position: absolute;
  left: -14px;
  top: 50%;
  width: 14px;
  height: 2px;
  background: rgba(155, 138, 239, 0.25);
}

.catalog-row--removed {
  opacity: 0.5;
  border-color: oklch(0.5 0.15 35);
}

.catalog-row--removed .catalog-row__name {
  text-decoration: line-through;
}

.catalog-row__removed {
  color: oklch(0.78 0.16 35);
}

.catalog-row__kit {
  color: rgba(255, 255, 255, 0.5);
}

.catalog-row__child {
  color: rgba(255, 255, 255, 0.3);
}

.modal__hint {
  font: 400 11.5px system-ui;
  color: rgba(255, 255, 255, 0.35);
  padding: 0 20px 4px;
}

.catalog-row--locked {
  opacity: 0.6;
}

.catalog-row__check {
  margin-top: 2px;
  width: 18px;
  height: 18px;
  border-radius: 0 4px 0 4px;
  border: 1.5px solid rgba(255, 255, 255, 0.3);
  flex: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font: 700 11px system-ui;
  color: #0b0d10;
}

.catalog-row__check--on {
  background: var(--accent);
  border-color: var(--accent);
}

.catalog-row__dot {
  margin-top: 6px;
  width: 8px;
  height: 8px;
  border-radius: 2px;
  flex: none;
}

.catalog-row__info {
  flex: 1;
  min-width: 0;
}

.catalog-row__name {
  font: 600 13px system-ui;
  color: #fff;
}

.catalog-row__stock {
  font: 400 11px system-ui;
  color: rgba(255, 255, 255, 0.4);
}

.catalog-row__rental {
  margin-top: 6px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.catalog-row__rental-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  font: 600 11px system-ui;
  color: rgba(255, 255, 255, 0.6);
  cursor: pointer;
}

.catalog-row__vendor {
  box-sizing: border-box;
  padding: 5px 8px;
  border-radius: 0 6px 0 6px;
  background: #0e1013;
  border: 1px solid rgba(255, 255, 255, 0.12);
  font: 500 11.5px system-ui;
  color: #fff;
  min-width: 140px;
}

.catalog-row__error {
  margin-top: 6px;
  font: 500 11px system-ui;
  color: oklch(0.78 0.16 35);
}

.catalog-row__conflict {
  margin-top: 6px;
  padding: 6px 8px;
  border-radius: 0 6px 0 6px;
  background: oklch(0.27 0.07 35);
  border: 1px solid oklch(0.5 0.15 35);
  font: 400 11px system-ui;
  color: rgba(255, 217, 207, 0.9);
}

.catalog-row__qty {
  flex: none;
  display: flex;
  align-items: center;
  gap: 6px;
}

.qty-btn {
  width: 24px;
  height: 24px;
  border-radius: 0 6px 0 6px;
  background: #0e1013;
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font: 700 13px system-ui;
}

.qty-input {
  width: 42px;
  box-sizing: border-box;
  padding: 4px;
  border-radius: 0 6px 0 6px;
  background: #0e1013;
  border: 1px solid rgba(255, 255, 255, 0.12);
  font: 600 12px system-ui;
  color: #fff;
  text-align: center;
}

.error {
  font: 500 11.5px system-ui;
  color: oklch(0.78 0.16 35);
}

.modal__footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 4px;
}

.modal__count {
  font: 500 12px system-ui;
  color: rgba(255, 255, 255, 0.4);
  margin-right: auto;
}

.btn {
  font: 600 12px system-ui;
  padding: 9px 16px;
  border-radius: var(--radius-notch-sm);
  cursor: pointer;
  white-space: nowrap;
}

.btn--ghost {
  color: rgba(255, 255, 255, 0.6);
  background: rgba(255, 255, 255, 0.06);
}

.btn--primary {
  color: #0b0d10;
  background: var(--accent);
}

.btn--disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn--force {
  background: oklch(0.7 0.16 35);
  color: #2a1400;
}
</style>

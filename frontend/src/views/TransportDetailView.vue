<script setup>
import { ref, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppShell from '../components/AppShell.vue'
import { api } from '../api/client'
import { useSuppressionFiche } from '../composables/useSuppressionFiche'

/**
 * Fiche transport — port de TransportDetail.dc.html, branché sur l'API réelle
 * (/api/transports/{id}/). Contrairement au prototype, les lieux utilisent
 * des `<select>` natifs plutôt qu'un dropdown personnalisé — plus simple et
 * suffisant, même pattern que les autres fiches déjà portées.
 *
 * Techniciens (2026-07-30) : un déplacement peut en mobiliser PLUSIEURS (table
 * `TransportTechnician`, écriture imbriquée sur `TransportSerializer.technicians`
 * — même pattern que `materials`). D'où la liste à cocher plutôt qu'un select
 * unique. Le PATCH remplace toute la liste.
 *
 * Sélection en cascade (2026-07-30) : cocher un kit dans la modale coche
 * aussi ses composants, en sautant ceux qui ne sont pas au lieu de départ.
 * Décocher le kit les décoche.
 *
 * `materials` (écriture imbriquée sur TransportSerializer) : édité localement
 * dans `form.materials`, envoyé en bloc à l'enregistrement (PATCH remplace
 * toute la liste — voir TransportSerializer.update()).
 *
 * Conflit de technicien : détecté côté serveur à l'enregistrement (400 avec
 * `conflicts`), même pattern que Spectacles/SpectacleDetail — pas de
 * précalcul côté client comme dans le prototype.
 *
 * Fenêtre départ/arrivée (2026-07-30, décision Samuel) : `transport.departure_show`/
 * `arrival_show` (déduits côté serveur — voir `get_transport_reference_shows`,
 * conflicts.py) sont affichés pour référence, et servent à proposer une heure
 * par défaut (fin effective du départ) quand `scheduled_datetime` est encore
 * vide — uniquement à l'ouverture de la fiche, pas recalculé en direct si
 * l'utilisateur change le lieu/type sans enregistrer. La validation
 * elle-même (transport hors de cette fenêtre) est bloquante côté serveur,
 * avec le même bouton « Forcer » que les conflits de technicien.
 *
 * `estimated_duration_minutes` (2026-07-30, suite) : était affiché en lecture
 * seule alors que le champ est déjà modifiable côté API (Meta.fields du
 * serializer) — Samuel en avait besoin pour corriger la valeur pré-remplie
 * (Google Routes ou défaut de Settings). Simple input number, envoyé dans le
 * PATCH comme les autres champs.
 */

const route = useRoute()

const transport = ref(null)
const venues = ref([])
const technicians = ref([])
const materialsCatalog = ref([])
const loading = ref(false)
const loadError = ref(null)

const typeOptions = [
  { value: 'delivery', label: 'Livraison' },
  { value: 'pickup', label: 'Ramassage' },
]

const timeFmt = new Intl.DateTimeFormat('fr-CA', { hour: '2-digit', minute: '2-digit', hour12: false })
const dateTimeFmt = new Intl.DateTimeFormat('fr-CA', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })

function fmtReference(iso) {
  return dateTimeFmt.format(new Date(iso))
}

const form = ref(null)
const saving = ref(false)
const saveError = ref(null)
const conflictDetail = ref(null)

const showAddModal = ref(false)
const catalogQty = ref({})

// Catégorie du matériel (voir MaterialCategory, models.py) — même helper que
// AssignerMaterielModal.vue / MaterielView.vue, dupliqué ici faute de composant
// partagé. Sert au filtre par puces dans la modale d'ajout (2026-07-30, suite).
const NO_CATEGORY = { label: 'Sans catégorie', color: 'rgba(255,255,255,.3)' }

function categoryOf(material) {
  return material?.category
    ? { label: material.category_name, color: material.category_color }
    : NO_CATEGORY
}

const selectedCategory = ref('all')

const categoryChips = computed(() => {
  const seen = new Map()
  materialsCatalog.value.forEach((m) => {
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

async function loadTransport() {
  const id = route.params.id
  loading.value = true
  loadError.value = null
  try {
    transport.value = await api.get(`/transports/${id}/`)
    const show = await api.get(`/shows/${transport.value.show}/`)
    const [venuesData, techniciansData, materialsData] = await Promise.all([
      api.get('/venues/', { project: show.project }),
      api.get('/technicians/', { project: show.project }),
      api.get('/materials/', { project: show.project }),
    ])
    venues.value = Array.isArray(venuesData) ? venuesData : (venuesData.results ?? [])
    technicians.value = Array.isArray(techniciansData) ? techniciansData : (techniciansData.results ?? [])
    materialsCatalog.value = Array.isArray(materialsData) ? materialsData : (materialsData.results ?? [])

    // Propose l'heure de départ effective (avec buffer) comme valeur par
    // défaut si aucune heure n'est encore saisie — seulement à l'ouverture
    // de la fiche (voir note du module en tête de fichier).
    let scheduledDefault = transport.value.scheduled_datetime ? transport.value.scheduled_datetime.slice(0, 16) : ''
    if (!scheduledDefault && transport.value.departure_show) {
      scheduledDefault = transport.value.departure_show.effective_end.slice(0, 16)
    }

    form.value = {
      transport_type: transport.value.transport_type,
      origin_venue: transport.value.origin_venue,
      destination_venue: transport.value.destination_venue,
      scheduled_datetime: scheduledDefault,
      estimated_duration_minutes: transport.value.estimated_duration_minutes,
      technicians: (transport.value.technicians ?? []).map((tt) => tt.technician),
      notes: transport.value.notes ?? '',
      materials: (transport.value.materials ?? []).map((m) => ({
        material: m.material,
        material_name: m.material_name,
        quantity: m.quantity,
      })),
    }
    saveError.value = null
    conflictDetail.value = null
  } catch (e) {
    loadError.value = e
  } finally {
    loading.value = false
  }
}

watch(() => route.params.id, loadTransport, { immediate: true })

const isConfirmed = computed(() => transport.value?.status === 'confirmed')
const isToApprove = computed(() => transport.value?.status === 'to_approve')

// --- Techniciens affectés (plusieurs depuis le 2026-07-30) ---

const technicianRows = computed(() =>
  technicians.value.map((t) => {
    const selected = form.value?.technicians.includes(t.id) ?? false
    return {
      id: t.id,
      name: t.name,
      specialty: t.specialty || '',
      selected,
      toggle: () => {
        form.value.technicians = selected
          ? form.value.technicians.filter((id) => id !== t.id)
          : [...form.value.technicians, t.id]
      },
    }
  }),
)

const selectedTechnicianNames = computed(() =>
  technicianRows.value.filter((t) => t.selected).map((t) => t.name),
)

const materialStockById = computed(() => new Map(materialsCatalog.value.map((m) => [m.id, m.quantity])))

function updateMaterialQty(index, value) {
  const stock = materialStockById.value.get(form.value.materials[index].material) ?? 999
  const qty = Math.max(0, Math.min(Number(value) || 0, stock))
  form.value.materials[index].quantity = qty
}

function removeMaterialLine(index) {
  form.value.materials.splice(index, 1)
}

// --- Disponibilité au lieu de départ (2026-07-30) ---
// On ne charge dans un camion que ce qui se trouve réellement au point de
// départ à l'heure du départ. La position vient du backend
// (GET /transports/{id}/material-availability/, qui réutilise le grand livre
// de transport_coherence.py) : `Material.venue` seul serait faux dès qu'un
// transport antérieur a déjà déplacé le matériel.

const availability = ref(null)
const availabilityLoading = ref(false)

// L'heure de référence est celle enregistrée en base, pas celle en cours de
// saisie dans le formulaire : tant que le transport n'est pas enregistré, le
// backend calcule sur l'ancienne valeur. Ce booléen sert à le dire.
const availabilityStale = computed(() => {
  if (!availability.value || !transport.value) return false
  const saved = transport.value.scheduled_datetime
    ? new Date(transport.value.scheduled_datetime).toISOString()
    : null
  const typed = form.value?.scheduled_datetime
    ? new Date(form.value.scheduled_datetime).toISOString()
    : null
  return saved !== typed
})

// --- Sélection en cascade des kits (2026-07-30) ---
// Même règle que la modale d'assignation du spectacle : cocher un kit coche
// ses composants. Nuance propre au transport : seuls les composants réellement
// présents au lieu de départ sont cochés — les autres restent grisés et
// désactivés (voir la disponibilité ci-dessus).

const childrenByParent = computed(() => {
  const map = new Map()
  materialsCatalog.value.forEach((m) => {
    if (!m.parent_material) return
    if (!map.has(m.parent_material)) map.set(m.parent_material, [])
    map.get(m.parent_material).push(m)
  })
  return map
})

const availableById = computed(() => {
  const map = new Map()
  ;(availability.value?.materials ?? []).forEach((m) => map.set(m.id, m.available))
  return map
})

async function openAddModal() {
  showAddModal.value = true
  selectedCategory.value = 'all'
  availabilityLoading.value = true
  try {
    availability.value = await api.get(`/transports/${transport.value.id}/material-availability/`)
  } catch {
    // En cas d'échec on ne bloque rien : mieux vaut une modale sans grisé
    // qu'une modale inutilisable.
    availability.value = null
  } finally {
    availabilityLoading.value = false
  }

  const seed = {}
  materialsCatalog.value.forEach((m) => {
    const existing = form.value.materials.find((line) => line.material === m.id)
    seed[m.id] = existing ? existing.quantity : 0
  })
  catalogQty.value = seed
}

function closeAddModal() {
  showAddModal.value = false
}

// Même arborescence que l'inventaire général et que la modale d'assignation
// du spectacle : chaque composant suit son kit, en retrait.
const visibleCatalog = computed(() =>
  materialsCatalog.value.filter(
    (m) => selectedCategory.value === 'all' || (m.category ?? 'none') === selectedCategory.value,
  ),
)

const visibleIds = computed(() => new Set(visibleCatalog.value.map((m) => m.id)))

function orderByKit(list) {
  const enfants = new Map()
  list.forEach((m) => {
    if (m.parent_material == null || !visibleIds.value.has(m.parent_material)) return
    if (!enfants.has(m.parent_material)) enfants.set(m.parent_material, [])
    enfants.get(m.parent_material).push(m)
  })
  const ordonne = []
  list.forEach((m) => {
    // Un composant dont le parent est masqué par le filtre reste affiché, au
    // premier niveau — mieux vaut orphelin que perdu.
    if (m.parent_material != null && visibleIds.value.has(m.parent_material)) return
    ordonne.push(m)
    ;(enfants.get(m.id) ?? []).forEach((child) => ordonne.push(child))
  })
  return ordonne
}

const catalogRows = computed(() =>
  orderByKit(visibleCatalog.value)
    .map((m) => {
    const qty = catalogQty.value[m.id] || 0
    // Sans rapport de disponibilité (échec de l'appel, ou transport pas encore
    // horodaté), on retombe sur le stock total : on n'invente pas de blocage.
    const available = availability.value ? (availableById.value.get(m.id) ?? 0) : m.quantity
    const disabled = available <= 0
    const clamp = (v) => Math.max(0, Math.min(Number(v) || 0, available))
    return {
      id: m.id,
      name: m.name,
      meta: categoryOf(m),
      stock: m.quantity,
      available,
      disabled,
      // Déjà dans le camion mais plus disponible : la ligne reste visible et
      // cochée, sinon on masquerait un chargement existant devenu incohérent.
      qty,
      selected: qty > 0,
      homeLabel: m.venue_name ?? 'Sans lieu',
      setQty: (v) => {
        if (disabled) return
        catalogQty.value = { ...catalogQty.value, [m.id]: clamp(v) }
      },
      inc: () => {
        if (disabled) return
        catalogQty.value = { ...catalogQty.value, [m.id]: Math.min(qty + 1, available) }
      },
      dec: () => {
        if (disabled) return
        catalogQty.value = { ...catalogQty.value, [m.id]: Math.max(qty - 1, 0) }
      },
      childCount: (childrenByParent.value.get(m.id) ?? []).length,
      isChild: m.parent_material != null,
      nested: m.parent_material != null && visibleIds.value.has(m.parent_material),
      toggle: () => {
        if (disabled) return
        const next = qty > 0 ? 0 : 1
        const updates = { [m.id]: next }
        ;(childrenByParent.value.get(m.id) ?? []).forEach((child) => {
          // Un composant absent du lieu de départ ne peut pas monter dans le
          // camion : la cascade le saute plutôt que de le forcer.
          const childAvailable = availability.value
            ? (availableById.value.get(child.id) ?? 0)
            : child.quantity
          if (childAvailable <= 0) return
          updates[child.id] = next > 0 ? Math.min(next, childAvailable) : 0
        })
        catalogQty.value = { ...catalogQty.value, ...updates }
      },
    }
  }),
)

const unavailableCount = computed(() => catalogRows.value.filter((c) => c.disabled).length)

const selectedCatalogCount = computed(() => Object.values(catalogQty.value).filter((q) => q > 0).length)

function confirmAddMaterial() {
  // La modale reflète l'état complet du chargement : une ligne à 0 (décochée)
  // doit donc être RETIRÉE du camion, pas seulement ignorée — sinon décocher
  // n'aurait aucun effet (demande de Samuel, 2026-07-30). Contrairement aux
  // modales du spectacle, tout reste local ici : c'est le PATCH du transport
  // qui applique la liste (`TransportSerializer.materials`).
  const merged = []
  materialsCatalog.value.forEach((m) => {
    const qty = catalogQty.value[m.id] || 0
    if (qty <= 0) return
    const existing = form.value.materials.find((line) => line.material === m.id)
    merged.push({
      material: m.id,
      material_name: existing?.material_name ?? m.name,
      quantity: qty,
    })
  })
  // Le matériel absent du catalogue affiché (inactif, ou filtré hors du
  // projet) n'est pas piloté par la modale : on le conserve tel quel plutôt
  // que de le perdre silencieusement.
  const catalogIds = new Set(materialsCatalog.value.map((m) => m.id))
  form.value.materials.forEach((line) => {
    if (!catalogIds.has(line.material)) merged.push(line)
  })
  form.value.materials = merged
  showAddModal.value = false
}

async function save({ confirm = false, force = false } = {}) {
  saveError.value = null
  conflictDetail.value = null
  saving.value = true
  try {
    const payload = {
      transport_type: form.value.transport_type,
      origin_venue: form.value.origin_venue,
      destination_venue: form.value.destination_venue,
      scheduled_datetime: form.value.scheduled_datetime ? new Date(form.value.scheduled_datetime).toISOString() : null,
      estimated_duration_minutes: Number(form.value.estimated_duration_minutes) || 1,
      technicians: form.value.technicians.map((id) => ({ technician: id })),
      notes: form.value.notes,
      materials: form.value.materials.map((m) => ({ material: m.material, quantity: m.quantity })),
      force,
    }
    if (confirm) payload.status = 'confirmed'
    transport.value = await api.patch(`/transports/${transport.value.id}/`, payload)
    form.value.materials = (transport.value.materials ?? []).map((m) => ({
      material: m.material,
      material_name: m.material_name,
      quantity: m.quantity,
    }))
  } catch (e) {
    // `conflicts` (technicien) et `departure_show`/`arrival_show` (fenêtre
    // départ/arrivée, 2026-07-30) partagent le même bandeau « Forcer » — les
    // deux sont bloquants + `force` côté serveur (voir TransportSerializer.validate()).
    if (e.data?.conflicts || e.data?.departure_show || e.data?.arrival_show) {
      conflictDetail.value = e.data
    } else {
      saveError.value =
        e.data?.detail ??
        e.data?.scheduled_datetime?.[0] ??
        e.data?.destination_venue?.[0] ??
        "Impossible d'enregistrer les changements."
    }
  } finally {
    saving.value = false
  }
}

const canConfirm = computed(() => isToApprove.value && !!form.value?.scheduled_datetime)

// --- Suppression (2026-07-30) ---
// La fiche transport est un formulaire toujours ouvert (pas de mode lecture,
// voir la note du 2026-07-30 sur l'édition des fiches) : le bouton vit donc
// simplement en bas, sous les actions. Supprimer un déplacement emporte ses
// lignes de matériel et de techniciens (tables de liaison en CASCADE) ; rien
// d'autre n'en dépend.
const {
  confirming, deleting, deleteError, askDelete, cancelDelete, confirmDelete,
} = useSuppressionFiche({ endpoint: '/transports', redirectTo: '/transports' })
</script>

<template>
  <AppShell>
    <div v-if="loading" class="hint">Chargement…</div>
    <div v-else-if="loadError" class="hint hint--error">
      Impossible de charger ce transport. Es-tu connecté (session Django) ?
    </div>

    <div v-else-if="transport && form" class="page">
      <div class="breadcrumb"><RouterLink to="/transports">Transports</RouterLink> / {{ transport.show_title }}</div>

      <div class="header">
        <h1 class="header__title">
          {{ form.transport_type === 'delivery' ? 'Livraison' : 'Ramassage' }} —
          {{ transport.origin_venue_code || transport.origin_venue_name }}
          →
          {{ transport.destination_venue_code || transport.destination_venue_name }}
        </h1>
        <div
          class="header__status"
          :style="isConfirmed
            ? { color: 'oklch(0.72 0.13 165)', background: 'oklch(0.72 0.13 165 / .16)' }
            : { color: 'oklch(0.78 0.13 85)', background: 'oklch(0.78 0.13 85 / .16)' }"
        >
          {{ isConfirmed ? 'Confirmé' : 'À approuver' }}
        </div>
      </div>

      <div class="card">
        <div class="field">
          <div class="field__label">Type</div>
          <div class="type-toggle">
            <div
              v-for="t in typeOptions"
              :key="t.value"
              class="type-toggle__item"
              :class="{ 'type-toggle__item--active': form.transport_type === t.value }"
              @click="form.transport_type = t.value"
            >
              {{ t.label }}
            </div>
          </div>
        </div>

        <div class="field">
          <div class="field__label">Spectacle</div>
          <div class="field__static">{{ transport.show_title }}</div>
        </div>

        <div class="field-grid">
          <div class="field">
            <div class="field__label">Lieu de départ</div>
            <select v-model="form.origin_venue" class="field__input">
              <option v-for="v in venues" :key="v.id" :value="v.id">{{ v.name }}</option>
            </select>
          </div>
          <div class="field">
            <div class="field__label">Lieu d'arrivée</div>
            <select v-model="form.destination_venue" class="field__input">
              <option v-for="v in venues" :key="v.id" :value="v.id">{{ v.name }}</option>
            </select>
          </div>
        </div>

        <div v-if="transport.departure_show || transport.arrival_show" class="reference-times">
          <div v-if="transport.departure_show" class="reference-times__item">
            <span class="reference-times__label">Fin du départ</span>
            <span class="reference-times__value">{{ transport.departure_show.title }} · {{ fmtReference(transport.departure_show.effective_end) }}</span>
          </div>
          <div v-if="transport.arrival_show" class="reference-times__item">
            <span class="reference-times__label">Début de l'arrivée</span>
            <span class="reference-times__value">{{ transport.arrival_show.title }} · {{ fmtReference(transport.arrival_show.effective_start) }}</span>
          </div>
        </div>

        <div class="field-grid">
          <div class="field">
            <div class="field__label">Heure prévue</div>
            <!-- step en secondes : 300 = minutes par pas de 5 -->
            <input
              v-model="form.scheduled_datetime"
              type="datetime-local"
              step="300"
              class="field__input"
            />
          </div>
          <div class="field">
            <div class="field__label">Durée estimée (min)</div>
            <input
              v-model.number="form.estimated_duration_minutes"
              type="number"
              min="1"
              step="5"
              class="field__input"
            />
          </div>
        </div>

        <div class="field">
          <div class="field__label">Techniciens affectés</div>
          <!-- Plusieurs personnes possibles depuis le 2026-07-30 (voir
               TransportTechnician) : liste à cocher plutôt qu'un select. -->
          <div class="tech-picker">
            <button
              v-for="t in technicianRows"
              :key="t.id"
              type="button"
              class="tech-chip"
              :class="{ 'tech-chip--on': t.selected }"
              @click="t.toggle"
            >
              <span class="tech-chip__check">{{ t.selected ? '✓' : '+' }}</span>
              <span>{{ t.name }}</span>
              <span v-if="t.specialty" class="tech-chip__role">{{ t.specialty }}</span>
            </button>
            <div v-if="technicianRows.length === 0" class="tech-empty">
              Aucun technicien dans ce projet.
            </div>
          </div>
          <div v-if="selectedTechnicianNames.length === 0" class="tech-hint">
            Aucun technicien affecté.
          </div>
          <div v-if="transport.has_technician_conflict" class="conflict-note">
            Au moins un des techniciens affectés est peut-être déjà engagé sur un autre
            spectacle ou déplacement durant cette fenêtre.
          </div>
        </div>

        <div class="field">
          <div class="field__label-row">
            <div class="field__label">Matériel transporté</div>
          </div>
          <div class="material-list">
            <div v-for="(m, i) in form.materials" :key="m.material" class="material-row">
              <div class="material-row__name">{{ m.material_name }}</div>
              <input
                type="number"
                min="0"
                class="material-row__qty"
                :value="m.quantity"
                @input="updateMaterialQty(i, $event.target.value)"
              />
              <div class="material-row__stock">/ {{ materialStockById.get(m.material) ?? '?' }} dispo.</div>
              <div class="material-row__remove" @click="removeMaterialLine(i)">✕</div>
            </div>
            <div v-if="form.materials.length === 0" class="row-empty">Aucun matériel — camion vide.</div>
          </div>
          <div class="material-add" @click="openAddModal">+ Ajouter du matériel</div>
        </div>

        <div class="field">
          <div class="field__label">Notes</div>
          <textarea
            v-model="form.notes"
            class="field__input field__textarea"
            placeholder="Consignes particulières, accès, code de porte…"
            rows="3"
          />
        </div>
      </div>

      <div class="actions">
        <div v-if="isToApprove && !form.scheduled_datetime" class="actions__warning">
          Ajoutez une heure prévue avant de confirmer.
        </div>
        <div v-if="saveError" class="actions__error">{{ saveError }}</div>
        <div v-if="isToApprove" class="save-btn" :class="{ 'save-btn--disabled': saving || !canConfirm }" @click="!saving && canConfirm && save({ confirm: true })">
          Confirmer le transport
        </div>
        <div v-else class="save-btn" :class="{ 'save-btn--disabled': saving }" @click="!saving && save()">
          Enregistrer
        </div>
      </div>

      <div v-if="conflictDetail" class="conflict-banner">
        <div class="conflict-banner__text">{{ conflictDetail.detail }}</div>
        <div class="save-btn save-btn--force" @click="save({ confirm: isToApprove, force: true })">
          Forcer malgré le conflit
        </div>
      </div>

      <div class="fiche-danger">
        <div class="fiche-danger__hint">
          Supprimer ce déplacement retire aussi son chargement et ses affectations.
        </div>
        <button type="button" class="fiche-btn fiche-btn--danger" @click="askDelete">
          Supprimer ce déplacement
        </button>
      </div>

      <div v-if="confirming" class="fiche-confirm-backdrop" @click.self="cancelDelete">
        <div class="fiche-confirm">
          <div class="fiche-confirm__title">Supprimer ce déplacement ?</div>
          <p class="fiche-confirm__text">Cette action est définitive.</p>
          <template v-if="form.materials.length > 0 || form.technicians.length > 0">
            <p class="fiche-confirm__text">Seront supprimés en même temps :</p>
            <ul class="fiche-confirm__list">
              <li v-if="form.materials.length > 0">
                {{ form.materials.length }} ligne(s) de matériel transporté
              </li>
              <li v-if="form.technicians.length > 0">
                {{ form.technicians.length }} affectation(s) de technicien
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
              @click="confirmDelete(transport.id)"
            >
              {{ deleting ? 'Suppression…' : 'Supprimer' }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <div v-if="showAddModal" class="modal-overlay" @click.self="closeAddModal">
      <div class="modal">
        <div class="modal__header">
          <div class="modal__title">Ajouter du matériel</div>
          <div class="modal__close" @click="closeAddModal">×</div>
        </div>
        <div v-if="availabilityLoading" class="modal__note">Vérification des emplacements…</div>
        <div v-else-if="availability && availability.at === null" class="modal__note">
          Ce déplacement n'a pas encore d'heure prévue : impossible de savoir ce
          qui se trouvera à {{ availability.origin_venue_name }}. Tout l'inventaire
          est proposé — saisis l'heure et enregistre pour filtrer sur le réel.
        </div>
        <div v-else-if="availability" class="modal__note">
          Seul le matériel présent à <strong>{{ availability.origin_venue_name }}</strong>
          au moment du départ est sélectionnable.
          <template v-if="unavailableCount > 0">
            {{ unavailableCount }} item(s) grisé(s) sont ailleurs.
          </template>
          <template v-if="availabilityStale">
            <br />L'heure saisie n'est pas encore enregistrée — la liste reflète
            l'heure actuellement en base.
          </template>
        </div>

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
            v-for="c in catalogRows"
            :key="c.id"
            class="catalog-row"
            :class="{
              'catalog-row--selected': c.selected,
              'catalog-row--disabled': c.disabled,
              'catalog-row--nested': c.nested,
            }"
          >
            <div
              class="catalog-row__check"
              :class="{ 'catalog-row__check--on': c.selected }"
              @click="c.toggle"
            >
              <span v-if="c.selected">✓</span>
            </div>
            <span class="catalog-row__dot" :style="{ background: c.meta.color }" />
            <div class="catalog-row__info">
              <div class="catalog-row__name">{{ c.name }}</div>
              <div class="catalog-row__stock">
                <template v-if="c.disabled">Pas sur place — entreposé à {{ c.homeLabel }}</template>
                <template v-else>{{ c.meta.label }} · {{ c.available }} sur place sur {{ c.stock }}</template>
              </div>
            </div>
            <div class="catalog-row__qty">
              <div class="qty-btn" @click="c.dec">−</div>
              <input
                type="number"
                class="qty-input"
                :value="c.qty"
                :disabled="c.disabled"
                @input="c.setQty($event.target.value)"
              />
              <div class="qty-btn" @click="c.inc">+</div>
            </div>
          </div>
        </div>
        <div class="modal__footer">
          <div class="modal__count">
            {{ selectedCatalogCount }} item(s) dans le camion — décoche pour retirer
          </div>
          <div class="modal__cancel" @click="closeAddModal">Annuler</div>
          <div class="modal__confirm" @click="confirmAddMaterial">Appliquer</div>
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
  max-width: 640px;
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
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.header__status {
  font: 700 10.5px system-ui;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 5px 12px;
  border-radius: 0 7px 0 7px;
  white-space: nowrap;
}

.card {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-notch-lg);
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.field__label {
  font: 700 11px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: rgba(255, 255, 255, 0.45);
  margin-bottom: 8px;
}

.field__label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.field__label-row .field__label {
  margin-bottom: 0;
}

.field__static {
  padding: 11px 12px;
  border-radius: var(--radius-notch-sm);
  background: #1b1f25;
  border: 1px solid rgba(255, 255, 255, 0.1);
  font: 500 13.5px system-ui;
  color: #fff;
}

.field__input {
  width: 100%;
  box-sizing: border-box;
  padding: 11px 12px;
  border-radius: var(--radius-notch-sm);
  background: #1b1f25;
  border: 1px solid rgba(255, 255, 255, 0.1);
  font: 500 13.5px system-ui;
  color: #fff;
}

.tech-picker {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tech-chip {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 12px;
  border-radius: var(--radius-notch-sm);
  background: #1b1f25;
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.6);
  font: 500 12.5px system-ui;
  cursor: pointer;
}

.tech-chip--on {
  border-color: rgba(155, 138, 239, 0.45);
  background: rgba(155, 138, 239, 0.14);
  color: #fff;
}

.tech-chip__check {
  font: 700 11px system-ui;
  opacity: 0.6;
}

.tech-chip--on .tech-chip__check {
  opacity: 1;
  color: var(--accent);
}

.tech-chip__role {
  font: 400 11px system-ui;
  color: rgba(255, 255, 255, 0.35);
}

.tech-empty,
.tech-hint {
  font: 400 11.5px system-ui;
  color: rgba(255, 255, 255, 0.35);
  margin-top: 6px;
}

.field__textarea {
  resize: vertical;
  font-family: system-ui;
}

.field-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.reference-times {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 24px;
  padding: 10px 12px;
  border-radius: var(--radius-notch-sm);
  background: #1b1f25;
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
  color: rgba(255, 255, 255, 0.4);
}

.reference-times__value {
  font: 500 12.5px system-ui;
  color: rgba(255, 255, 255, 0.8);
}

.type-toggle {
  display: flex;
  gap: 8px;
}

.type-toggle__item {
  flex: 1;
  text-align: center;
  padding: 10px;
  border-radius: var(--radius-notch-sm);
  font: 600 13px system-ui;
  cursor: pointer;
  background: transparent;
  color: rgba(255, 255, 255, 0.55);
  border: 1px solid rgba(255, 255, 255, 0.12);
}

.type-toggle__item--active {
  background: rgba(155, 138, 239, 0.18);
  color: var(--accent);
  border-color: rgba(155, 138, 239, 0.4);
}

.conflict-note {
  margin-top: 8px;
  font: 500 11.5px system-ui;
  color: rgba(255, 217, 207, 0.75);
}

.material-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.material-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border-radius: 0 6px 0 6px;
  background: #1b1f25;
}

.material-row__name {
  flex: 1;
  font: 500 12.5px system-ui;
  color: #fff;
}

.material-row__qty {
  width: 56px;
  box-sizing: border-box;
  padding: 6px 8px;
  border-radius: 0 6px 0 6px;
  background: #0e1013;
  border: 1px solid rgba(255, 255, 255, 0.12);
  font: 600 12px system-ui;
  color: #fff;
  text-align: center;
}

.material-row__stock {
  font: 400 11px system-ui;
  color: rgba(255, 255, 255, 0.35);
  min-width: 64px;
}

.material-row__remove {
  font: 700 12px system-ui;
  color: rgba(255, 255, 255, 0.35);
  cursor: pointer;
  padding: 2px 6px;
}

.material-add {
  margin-top: 8px;
  padding: 9px 12px;
  border-radius: var(--radius-notch-sm);
  border: 1px dashed rgba(255, 255, 255, 0.18);
  font: 600 12px system-ui;
  color: rgba(255, 255, 255, 0.5);
  cursor: pointer;
  text-align: center;
}

.row-empty {
  font: 500 12.5px system-ui;
  color: rgba(255, 255, 255, 0.4);
  padding: 10px 12px;
}

.actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
  align-items: center;
  flex-wrap: wrap;
}

.actions__warning {
  font: 500 11.5px system-ui;
  color: rgba(255, 217, 207, 0.75);
  margin-right: auto;
}

.actions__error {
  font: 500 11.5px system-ui;
  color: oklch(0.78 0.16 35);
  margin-right: auto;
}

.save-btn {
  padding: 10px 20px;
  border-radius: var(--radius-notch-sm);
  font: 600 13px system-ui;
  color: #0b0d10;
  background: var(--accent);
  cursor: pointer;
  white-space: nowrap;
}

.save-btn--disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.save-btn--force {
  background: oklch(0.7 0.16 35);
  color: #2a1400;
}

.conflict-banner {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px 16px;
  border-radius: 0 10px 0 10px;
  background: oklch(0.27 0.07 35);
  border: 1px solid oklch(0.5 0.15 35);
}

.conflict-banner__text {
  font: 400 12px system-ui;
  color: rgba(255, 217, 207, 0.9);
}

.modal {
  width: min(640px, 94vw);
  max-width: 100%;
  /* Hauteur FIXE (2026-07-30) — même règle que les modales d'assignation du
     spectacle : taille et position constantes quel que soit le contenu. */
  height: 85vh;
  max-height: 85vh;
  background: var(--bg-card);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 0 16px 0 16px;
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.5);
  display: flex;
  flex-direction: column;
}

.modal__header {
  padding: 18px 20px;
  border-bottom: 1px solid var(--border-card);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.modal__title {
  font: 700 15px var(--font-mono);
  letter-spacing: 0.02em;
  color: #fff;
}

.modal__close {
  font: 400 18px system-ui;
  color: rgba(255, 255, 255, 0.4);
  cursor: pointer;
}

.filters {
  padding: 12px 20px 0;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.modal__body {
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 5px;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.catalog-row {
  display: flex;
  align-items: center;
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

/* Matériel absent du lieu de départ : gris moyen (contre le blanc du
   disponible) et non sélectionnable — voir la note de la modale. */
.catalog-row--disabled {
  opacity: 0.55;
}

.catalog-row--disabled .catalog-row__name {
  color: rgba(255, 255, 255, 0.45);
}

.catalog-row--disabled .catalog-row__check,
.catalog-row--disabled .qty-btn {
  cursor: not-allowed;
  opacity: 0.5;
}

.modal__note {
  padding: 12px 20px;
  border-bottom: 1px solid var(--border-card);
  font: 400 11.5px/1.5 system-ui;
  color: rgba(255, 255, 255, 0.5);
}

.modal__note strong {
  color: rgba(255, 255, 255, 0.8);
}

.catalog-row__check {
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

.catalog-row__qty {
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
  width: 38px;
  box-sizing: border-box;
  padding: 4px;
  border-radius: 0 6px 0 6px;
  background: #0e1013;
  border: 1px solid rgba(255, 255, 255, 0.12);
  font: 600 12px system-ui;
  color: #fff;
  text-align: center;
}

.modal__footer {
  padding: 14px 20px;
  border-top: 1px solid var(--border-card);
  display: flex;
  gap: 10px;
  justify-content: flex-end;
  align-items: center;
}

.modal__count {
  font: 500 12px system-ui;
  color: rgba(255, 255, 255, 0.4);
  margin-right: auto;
}

.modal__cancel {
  padding: 9px 16px;
  border-radius: var(--radius-notch-sm);
  font: 600 13px system-ui;
  color: rgba(255, 255, 255, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.15);
  cursor: pointer;
}

.modal__confirm {
  padding: 9px 18px;
  border-radius: var(--radius-notch-sm);
  font: 600 13px system-ui;
  color: #0b0d10;
  background: var(--accent);
  cursor: pointer;
}
</style>

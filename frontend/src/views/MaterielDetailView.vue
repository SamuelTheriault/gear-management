<script setup>
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppShell from '../components/AppShell.vue'
import { api } from '../api/client'
import { useFicheEdition } from '../composables/useFicheEdition'
import { useSuppressionFiche } from '../composables/useSuppressionFiche'
import { EVENT_TYPE_META, TRANSPORT_META } from '../constants/eventTypeMeta'

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
 * Chronologie (2026-08-01, demande de Samuel) : `GET /api/materials/{id}/
 * schedule/` remplace l'ancienne liste « Assignations actuelles », qui ne
 * montrait que les spectacles et sans horaire. On y voit maintenant les
 * spectacles, les blocs (montage, répétition, démontage) et les déplacements
 * sur une seule ligne de temps, avec les mêmes lignes cliquables que la
 * chronologie de la fiche spectacle.
 *
 * Le tri et la règle d'héritage (un montage mobilise le matériel de son
 * événement sans porter d'assignation) sont calculés côté backend — voir
 * `get_material_schedule`. Le drapeau `conflict` vient de là aussi, ce qui
 * remplace l'ancienne rafale d'appels à `GET /shows/{id}/conflicts/`, un par
 * assignation.
 *
 * Kit parent (2026-08-02, demande de Samuel) : `Material.is_kit_parent`
 * (case à cocher du formulaire d'édition) doit être activé avant qu'un autre
 * matériel puisse le choisir comme parent — `parentOptions` filtre déjà sur
 * ce champ, `MaterialSerializer.validate_parent_material` le refait côté API
 * pour ne pas dépendre uniquement du frontend. Décision actée avec Samuel :
 * pas de bascule automatique sur les kits déjà existants, à réactiver
 * manuellement au cas par cas. Le flag fait aussi apparaître la section
 * « Ajouter un composant à ce kit » plus bas, qui réutilise le formulaire
 * `.add-form` de MaterielView.vue en fixant `parent_material`/`quantity`.
 *
 * Héritage des assignations (2026-08-02, demande de Samuel) : si le kit est
 * déjà assigné à un ou plusieurs spectacles au moment où on lui rattache un
 * composant (création ici, ou rattachement a posteriori via « Fait partie du
 * kit »), le composant reçoit automatiquement les mêmes assignations
 * (`ShowMaterial`, quantity=1) — géré entièrement côté backend
 * (`MaterialSerializer.create`/`update`, voir
 * `_mirror_parent_show_material_assignments`), rien à faire ici pour que la
 * Chronologie du composant les affiche : elle lit déjà `/materials/{id}/
 * schedule/`, qui source directement `ShowMaterial`.
 */

const route = useRoute()
const router = useRouter()

const material = ref(null)
const components = ref([])
const schedule = ref([])
const scheduleWindow = ref(null)
const scheduleOutside = ref(0)
const distribution = ref(null)
const loading = ref(false)
const loadError = ref(null)

// Options des listes déroulantes du mode édition (chargées avec la fiche).
const projectMaterials = ref([])
const projectVenues = ref([])
const projectCategories = ref([])

const NO_CATEGORY = { label: 'Sans catégorie', color: 'rgba(var(--fg-rgb),.3)' }

const ownershipMeta = {
  owned: { label: 'Propriété', color: 'oklch(0.72 0.13 165)', bg: 'oklch(0.72 0.13 165 / .16)' },
  rental: { label: 'Location', color: 'oklch(0.8 0.13 85)', bg: 'oklch(0.8 0.13 85 / .16)' },
}

// Mêmes libellés et couleurs que la chronologie de la fiche spectacle
// (constants/eventTypeMeta.js, 2026-08-02), plus une entrée pour les
// déplacements — les deux écrans doivent se lire pareil. `transport`
// reprenait par erreur la teinte de « Démontage » avant ce passage en
// source unique ; utilise maintenant la vraie couleur de transport
// (`--transport`, fuchsia), la même que Dashboard/Parcours Matériel.
const typeMeta = { ...EVENT_TYPE_META, transport: TRANSPORT_META }

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

/**
 * Répartition entre les lieux, sur toute la durée du projet.
 *
 * Même source que l'écran « Parcours Matériel » (`get_material_journey`) : les
 * deux ne peuvent donc pas raconter autre chose. La différence est le
 * regroupement — le Parcours empile une ligne par *lane* pour tracer les
 * bifurcations, cette carte-ci regroupe par LIEU, ce qui répond à « où est mon
 * stock, et depuis quand ».
 */
async function loadDistribution() {
  const id = route.params.id
  try {
    distribution.value = await api.get(`/materials/${id}/distribution/`)
  } catch {
    // Un aller-retour raté ne doit pas vider la fiche entière : la carte
    // disparaît, le reste continue de s'afficher.
    distribution.value = null
  }
}

async function loadMaterial() {
  const id = route.params.id
  loading.value = true
  loadError.value = null
  try {
    material.value = await api.get(`/materials/${id}/`)

    const [materialsData, scheduleData, venuesData, categoriesData] = await Promise.all([
      api.get('/materials/', { project: material.value.project, include_inactive: true }),
      api.get(`/materials/${id}/schedule/`),
      api.get('/venues/', { project: material.value.project }),
      api.get('/material-categories/', { project: material.value.project }),
      loadDistribution(),
    ])
    const materialsList = Array.isArray(materialsData) ? materialsData : (materialsData.results ?? [])
    projectMaterials.value = materialsList
    projectVenues.value = Array.isArray(venuesData) ? venuesData : (venuesData.results ?? [])
    projectCategories.value = Array.isArray(categoriesData) ? categoriesData : (categoriesData.results ?? [])
    components.value = materialsList.filter((m) => m.parent_material === Number(id))
    schedule.value = scheduleData.entries ?? []
    scheduleWindow.value = scheduleData.window ?? null
    scheduleOutside.value = scheduleData.outside_window ?? 0
    // Le lieu par défaut du formulaire « Ajouter un composant » suit le lieu
    // d'origine du kit — un composant fraîchement acheté/reçu arrive
    // généralement au même endroit, sans empêcher de le changer.
    resetChildForm()
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

// Le kit dont ce matériel fait partie (mode lecture seulement — le mode
// édition a déjà son `<select>` `parent_material`). Cherché dans la liste du
// projet, déjà chargée avec `include_inactive: true` par `loadMaterial`.
const parentMaterialInfo = computed(() => {
  const pid = material.value?.parent_material
  if (!pid) return null
  return projectMaterials.value.find((m) => m.id === pid) ?? null
})

const decoratedComponents = computed(() =>
  components.value.map((c) => {
    const own = ownershipMeta[c.ownership_status] ?? ownershipMeta.owned
    return { ...c, ownLabel: own.label, ownColor: own.color, ownBg: own.bg }
  }),
)

/**
 * Chronologie affichée : spectacles, blocs et déplacements dans l'ordre où le
 * matériel les rencontre. L'ordre vient du backend, on ne retrie pas ici.
 *
 * Le sous-titre porte l'essentiel : la plage horaire, le lieu, la quantité si
 * elle dépasse 1, et le contexte du bloc. Un déplacement encore à approuver
 * n'a pas d'heure — il est renvoyé en fin de liste, avec une mention plutôt
 * qu'une date vide.
 */
const decoratedSchedule = computed(() =>
  schedule.value.map((e, index) => {
    const meta = e.kind === 'transport'
      ? typeMeta.transport
      : (typeMeta[e.event_type] ?? typeMeta.performance)
    const details = []
    if (e.start && e.end) {
      details.push(fmtRange(e.start, e.end))
    } else {
      details.push('Heure à confirmer')
    }
    if (e.venue_name) details.push(e.venue_name)
    if (e.quantity > 1) details.push(`×${e.quantity}`)
    if (e.inherited) details.push(`matériel de « ${e.parent_title} »`)
    else if (e.parent_title) details.push(`rattachée à « ${e.parent_title} »`)
    if (e.kind === 'transport' && e.status === 'to_approve') details.push('proposition à approuver')
    if (e.is_rental) details.push(`location${e.rental_vendor ? ` · ${e.rental_vendor}` : ''}`)
    return {
      ...e,
      key: `${e.kind}-${e.id}-${index}`,
      typeLabel: meta.label,
      typeColor: meta.color,
      typeBg: meta.bg,
      details: details.join(' · '),
    }
  }),
)

function goToEntry(entry) {
  router.push(entry.kind === 'transport' ? `/transports/${entry.id}` : `/spectacles/${entry.id}`)
}

// --- Répartition entre les lieux ---
// Affichée seulement pour un matériel possédé en plusieurs exemplaires : à
// quantity = 1, la chronologie et le lieu d'origine disent déjà tout, une
// barre à 100 % n'apprendrait rien.
const showsDistribution = computed(() => (material.value?.quantity ?? 1) > 1)

function fmtInstant(iso) {
  const d = new Date(iso)
  return `${dateTimeFmt.format(d)} ${timeFmt.format(d)}`
}

const distributionBounds = computed(() => {
  const w = distribution.value?.window
  if (!w?.start || !w?.end) return null
  const start = new Date(w.start).getTime()
  const end = new Date(w.end).getTime()
  return end > start ? { start, end, span: end - start } : null
})

/** Position (0-100 %) d'un instant dans la fenêtre du projet, bornée. */
function pct(iso) {
  const b = distributionBounds.value
  if (!b || !iso) return 0
  const t = new Date(iso).getTime()
  return Math.min(100, Math.max(0, ((t - b.start) / b.span) * 100))
}

function segmentStyle(startIso, endIso) {
  const left = pct(startIso)
  return { left: `${left}%`, width: `${Math.max(pct(endIso) - left, 0.4)}%` }
}

/**
 * Une ligne par LIEU, avec ses périodes de détention.
 *
 * Le backend renvoie les séjours par *lane* (la découpe qui sert à tracer les
 * bifurcations sur l'écran Parcours). Ici on les regroupe par lieu : deux
 * lanes au même endroit au même moment donnent deux segments sur la même
 * ligne, ce qui se lit comme « ce lieu détient N + M exemplaires ».
 *
 * Les déplacements confirmés occupent une ligne à part, en fin de liste :
 * pendant le trajet le matériel n'est chez personne, et le montrer sur la
 * ligne d'un lieu serait faux.
 */
const distributionRows = computed(() => {
  const data = distribution.value
  if (!data || !distributionBounds.value) return []

  const parLieu = new Map()
  data.stays.forEach((s) => {
    if (!parLieu.has(s.venue_id)) {
      parLieu.set(s.venue_id, { name: s.venue_name, segments: [], peak: 0 })
    }
    const row = parLieu.get(s.venue_id)
    row.segments.push({
      key: `stay-${s.lane}-${s.start}`,
      style: segmentStyle(s.start, s.end),
      quantity: s.quantity,
      tooltip: `${s.quantity} exemplaire(s) · ${fmtInstant(s.start)} → ${fmtInstant(s.end)}`,
    })
    row.peak = Math.max(row.peak, s.quantity)
  })

  const rows = [...parLieu.entries()].map(([venueId, row]) => ({
    key: `venue-${venueId}`,
    label: row.name,
    detail: `jusqu'à ${row.peak} exemplaire(s) sur place`,
    color: 'var(--accent)',
    segments: row.segments,
  }))

  if (data.transports.length > 0) {
    rows.push({
      key: 'transit',
      label: 'En transit',
      detail: `${data.transports.length} déplacement(s) confirmé(s)`,
      // Même teinte que partout ailleurs pour un transport (`--transport`,
      // fuchsia) — reprenait par erreur la teinte de « Démontage » avant ce
      // passage en source unique (2026-08-02, voir typeMeta plus haut).
      color: 'var(--transport)',
      segments: data.transports.map((t) => ({
        key: `transit-${t.transport_id}`,
        style: segmentStyle(t.start, t.end),
        quantity: t.quantity,
        tooltip: `${t.quantity} exemplaire(s) · ${t.origin_name} → ${t.destination_name}`,
      })),
    })
  }
  return rows
})

/** Graduation de l'axe : un repère par jour de la fenêtre du projet. */
const distributionTicks = computed(() => {
  const b = distributionBounds.value
  if (!b) return []
  const marks = []
  const curseur = new Date(b.start)
  curseur.setHours(0, 0, 0, 0)
  while (curseur.getTime() <= b.end) {
    if (curseur.getTime() >= b.start) {
      marks.push({
        key: curseur.toISOString(),
        left: `${pct(curseur.toISOString())}%`,
        label: dateTimeFmt.format(curseur),
      })
    }
    curseur.setDate(curseur.getDate() + 1)
  }
  // Une graduation par jour devient illisible sur une longue production : on
  // n'en garde qu'une sur N pour rester sous une quinzaine de repères.
  const pas = Math.ceil(marks.length / 12) || 1
  return marks.filter((_, i) => i % pas === 0)
})

// Libellé de la fenêtre, lu sur la réponse de la répartition plutôt que sur
// celle de la chronologie : c'est la même fenêtre côté backend, mais deux
// appels distincts — pas la peine de rendre une carte dépendante de l'autre.
const distributionWindowLabel = computed(() => {
  const w = distribution.value?.window
  if (!w?.start || !w?.end) return null
  return `${dayFmt.format(new Date(w.start))} → ${dayFmt.format(new Date(w.end))}`
})

/** Repère « maintenant », seulement s'il tombe dans la fenêtre du projet. */
const nowMarker = computed(() => {
  const b = distributionBounds.value
  if (!b) return null
  const now = Date.now()
  if (now < b.start || now > b.end) return null
  return { left: `${((now - b.start) / b.span) * 100}%` }
})

// Fenêtre du projet, calculée par le backend (`get_project_window`, la même
// que les écrans Parcours) : dates du projet si elles sont saisies, sinon du
// premier au dernier événement. `null` quand le projet n'a ni l'un ni l'autre.
const dayFmt = new Intl.DateTimeFormat('fr-CA', { day: 'numeric', month: 'long', year: 'numeric' })

const scheduleWindowLabel = computed(() => {
  const w = scheduleWindow.value
  if (!w?.start || !w?.end) return null
  return `${dayFmt.format(new Date(w.start))} → ${dayFmt.format(new Date(w.end))}`
})

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
    'venue', 'parent_material', 'is_kit_parent', 'is_active', 'notes',
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
    is_kit_parent: Boolean(m.is_kit_parent),
    is_active: Boolean(m.is_active),
    notes: m.notes ?? '',
  }),
  // Le lieu d'origine ne peut plus être vidé (obligatoire depuis le 2026-07-30).
  // `is_kit_parent` réservé à quantity=1 (MaterialSerializer.validate(), même
  // esprit que la contrainte kit existante) — voir aussi `kitParentLocked`.
  isValid: (d) =>
    d.name.trim().length > 0 && Number(d.quantity) >= 1 && d.venue !== ''
    && !(Number(d.quantity) > 1 && d.is_kit_parent),
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
    is_kit_parent: d.is_kit_parent,
    is_active: d.is_active,
    notes: d.notes.trim(),
  }),
})

async function saveMaterial() {
  // Recharge derrière l'enregistrement : changer le parent ou la quantité
  // modifie l'arbre des composants affiché plus bas.
  if (await save()) await loadMaterial()
}

// --- Suppression (2026-08-04, même comportement que Spectacle/Transport) ---
// Autorisée même si le matériel a un historique d'assignations — pas de
// blocage façon Lieu. `MaterialSerializer.deletion_impact` distingue ce qui
// est réellement supprimé (assignations spectacle/transport, en CASCADE) de
// ce qui est seulement détaché (composants d'un kit, `parent_material` en
// SET_NULL côté modèle : ils redeviennent du matériel autonome plutôt que de
// disparaître).
const {
  confirming, deleting, deleteError, askDelete, cancelDelete, confirmDelete,
} = useSuppressionFiche({ endpoint: '/materials', redirectTo: '/materiel' })

const deletionImpact = computed(() => material.value?.deletion_impact ?? null)
const hasCascade = computed(
  () => !!deletionImpact.value && Object.values(deletionImpact.value).some((n) => n > 0),
)

// Le backend refuse un parent qui n'a pas quantity=1 ET is_kit_parent=true
// (MaterialSerializer.validate_parent_material — champ ajouté le 2026-08-02,
// demande de Samuel), et le matériel ne peut pas être son propre parent — on
// retire ces cas de la liste plutôt que de laisser l'utilisateur se faire
// refuser l'enregistrement.
const parentOptions = computed(() =>
  projectMaterials.value.filter(
    (m) => m.id !== material.value?.id && m.quantity === 1 && m.parent_material == null && m.is_kit_parent,
  ),
)

// Règles de MaterialSerializer.validate() : un matériel en plusieurs
// exemplaires ne peut ni avoir un parent, ni être un kit. On l'annonce dans
// le formulaire au lieu d'attendre l'erreur 400.
const quantityLocked = computed(
  () => draft.value?.parent_material !== '' || components.value.length > 0,
)

// « Peut être un parent (kit) » (2026-08-02, demande de Samuel) : réservé à
// quantity=1, même contrainte que le matériel parent lui-même — cochée sur un
// item à plusieurs exemplaires, l'enregistrement serait refusé côté API.
const kitParentLocked = computed(() => Number(draft.value?.quantity) > 1)

// --- Ajouter un composant (2026-08-02, demande de Samuel) ---
// Même formulaire que « Ajouter du matériel » sur MaterielView.vue, mais
// `parent_material` et `quantity` (toujours 1 pour un composant, voir
// MaterialSerializer.validate()) sont fixés automatiquement plutôt que
// saisis — visible uniquement quand ce matériel est activé comme parent
// (`material.is_kit_parent`), même condition que le filtre `parentOptions`
// ci-dessus côté sélection.
const childForm = ref({ name: '', category: '', venue: '', ownership_status: 'owned' })
const childFormError = ref(null)
const childNameError = ref(false)
const childVenueError = ref(false)
const childSubmitting = ref(false)

const canSubmitChild = computed(
  () => childForm.value.name.trim().length > 0 && !!childForm.value.venue && !childSubmitting.value,
)

function resetChildForm() {
  childForm.value = {
    name: '',
    category: '',
    venue: material.value?.venue ?? '',
    ownership_status: 'owned',
  }
  childNameError.value = false
  childVenueError.value = false
}

async function addChildMaterial() {
  childFormError.value = null
  const name = childForm.value.name.trim()
  if (!name) {
    childNameError.value = true
    return
  }
  if (!childForm.value.venue) {
    childVenueError.value = true
    return
  }
  childSubmitting.value = true
  try {
    await api.post('/materials/', {
      project: material.value.project,
      name,
      category: childForm.value.category || null,
      venue: childForm.value.venue,
      ownership_status: childForm.value.ownership_status,
      quantity: 1,
      parent_material: material.value.id,
    })
    await loadMaterial()
  } catch (e) {
    childFormError.value = e.data?.detail ?? "Impossible d'enregistrer le composant."
  } finally {
    childSubmitting.value = false
  }
}

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

      <!-- Résumé (mode lecture) : quantité et appartenance à un kit, absentes
           du reste de la fiche en lecture alors qu'éditables dans le
           formulaire — voir demande de Samuel du 2026-08-02. -->
      <div v-if="!editing" class="card summary-grid">
        <div>
          <div class="summary-label">Quantité</div>
          <div class="summary-value">
            {{ material.quantity }} exemplaire{{ material.quantity > 1 ? 's' : '' }}
          </div>
        </div>
        <div>
          <div class="summary-label">Fait partie du kit</div>
          <div class="summary-value">
            <RouterLink v-if="parentMaterialInfo" :to="`/materiel/${parentMaterialInfo.id}`" class="summary-link">
              {{ parentMaterialInfo.name }}
            </RouterLink>
            <span v-else class="summary-value--muted">Aucun (matériel autonome)</span>
          </div>
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
            <span class="fiche-label">Kit</span>
            <label class="fiche-checkbox">
              <input
                v-model="draft.is_kit_parent"
                type="checkbox"
                :disabled="kitParentLocked"
              />
              Peut être un parent (kit)
            </label>
            <span v-if="fieldErrors.is_kit_parent" class="fiche-error">
              {{ fieldErrors.is_kit_parent }}
            </span>
            <span v-else-if="kitParentLocked" class="fiche-hint">
              Réservé à une quantité de 1 — un kit reste une unité conceptuelle unique.
            </span>
            <span v-else class="fiche-hint">
              Fait apparaître une section pour lui ajouter des composants, et le
              rend sélectionnable comme parent depuis un autre matériel.
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

        <div class="fiche-danger">
          <div class="fiche-danger__hint">
            Supprimer ce matériel retire aussi ses assignations et ses déplacements.
            Les composants de ce kit, s'il en a, seront détachés (pas supprimés).
          </div>
          <button type="button" class="fiche-btn fiche-btn--danger" @click="askDelete">
            Supprimer ce matériel
          </button>
        </div>
      </div>

      <div v-if="confirming" class="fiche-confirm-backdrop" @click.self="cancelDelete">
        <div class="fiche-confirm">
          <div class="fiche-confirm__title">Supprimer « {{ material.name }} » ?</div>
          <p class="fiche-confirm__text">Cette action est définitive.</p>
          <template v-if="hasCascade">
            <p class="fiche-confirm__text">Seront supprimés en même temps :</p>
            <ul class="fiche-confirm__list">
              <li v-if="deletionImpact.shows > 0">
                {{ deletionImpact.shows }} assignation(s) à un spectacle
              </li>
              <li v-if="deletionImpact.transports > 0">
                {{ deletionImpact.transports }} assignation(s) de transport
              </li>
              <li v-if="deletionImpact.components > 0">
                {{ deletionImpact.components }} composant(s) de kit seront détachés (pas supprimés)
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
              @click="confirmDelete(material.id)"
            >
              {{ deleting ? 'Suppression…' : 'Supprimer' }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="!editing && material.description" class="card">
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

      <!-- Ajouter un composant (2026-08-02, demande de Samuel) : même
           formulaire que « Ajouter du matériel » sur la page Matériel, mais
           parent_material et quantity sont fixés automatiquement. Visible
           uniquement quand ce matériel est activé comme parent — voir la
           case « Peut être un parent (kit) » du formulaire d'édition
           ci-dessus. -->
      <div v-if="material.is_kit_parent" class="add-form">
        <div class="add-form__title">Ajouter un composant à ce kit</div>
        <div class="fiche-hint">
          Si ce kit est déjà assigné à un ou plusieurs spectacles, le composant
          héritera automatiquement des mêmes assignations — modifiable ensuite
          comme n'importe quelle assignation.
        </div>
        <div class="add-form__row">
          <label class="add-form__field add-form__field--wide">
            <span class="add-form__label">Nom du matériel</span>
            <input
              v-model="childForm.name"
              placeholder="ex. Micro sans fil"
              class="add-form__input"
              :class="{ 'add-form__input--error': childNameError }"
              @input="childNameError = false"
            />
          </label>
          <label class="add-form__field">
            <span class="add-form__label">Catégorie</span>
            <select v-model="childForm.category" class="add-form__input">
              <option value="">Sans catégorie</option>
              <option v-for="c in projectCategories" :key="c.id" :value="c.id">{{ c.name }}</option>
            </select>
          </label>
          <label class="add-form__field">
            <span class="add-form__label">Lieu d'origine *</span>
            <select
              v-model="childForm.venue"
              class="add-form__input"
              :class="{ 'add-form__input--error': childVenueError }"
              @change="childVenueError = false"
            >
              <option value="" disabled>Choisir un lieu…</option>
              <option v-for="v in projectVenues" :key="v.id" :value="v.id">{{ v.name }}</option>
            </select>
          </label>
          <label class="add-form__field">
            <span class="add-form__label">Propriété</span>
            <select v-model="childForm.ownership_status" class="add-form__input">
              <option value="owned">Propriété</option>
              <option value="rental">Location</option>
            </select>
          </label>
          <div
            class="add-form__submit"
            :class="{ 'add-form__submit--disabled': !canSubmitChild }"
            @click="canSubmitChild && addChildMaterial()"
          >
            + Ajouter
          </div>
        </div>
        <div v-if="childNameError" class="add-form__error">Le nom du matériel est requis.</div>
        <div v-if="childVenueError" class="add-form__error">
          Le lieu d'origine est requis — c'est là que le matériel doit revenir en fin de projet.
        </div>
        <div v-if="childFormError" class="add-form__error">{{ childFormError }}</div>
      </div>

      <!-- Répartition (2026-08-01, demande de Samuel) : où sont les
           exemplaires d'un matériel possédé en plusieurs unités, à un instant
           donné. Uniquement à quantity > 1 — voir `showsDistribution`. -->
      <div v-if="showsDistribution && distribution" class="card">
        <div class="repartition-head">
          <div class="card-title">Répartition</div>
          <div v-if="distributionWindowLabel" class="schedule-window">
            {{ distributionWindowLabel }}
          </div>
        </div>

        <div class="fiche-hint" style="margin: 10px 0 16px">
          Où se trouvent les {{ distribution.total }} exemplaires sur la durée du
          projet, une ligne par lieu. Positions déduites du lieu d'origine et des
          déplacements confirmés — même source que l'écran Parcours Matériel.
        </div>

        <div v-if="distributionRows.length > 0" class="repartition">
          <div class="repartition-axis">
            <div
              v-for="t in distributionTicks"
              :key="t.key"
              class="repartition-axis__tick"
              :style="{ left: t.left }"
            >{{ t.label }}</div>
          </div>

          <div v-for="r in distributionRows" :key="r.key" class="repartition-row">
            <div class="repartition-row__label">
              <div class="repartition-row__name">{{ r.label }}</div>
              <div class="repartition-row__detail">{{ r.detail }}</div>
            </div>
            <div class="repartition-track">
              <div
                v-for="t in distributionTicks"
                :key="`grid-${r.key}-${t.key}`"
                class="repartition-gridline"
                :style="{ left: t.left }"
              />
              <div
                v-for="seg in r.segments"
                :key="seg.key"
                class="repartition-seg"
                :style="{ ...seg.style, background: r.color }"
                :title="seg.tooltip"
              >{{ seg.quantity }}x</div>
              <div v-if="nowMarker" class="repartition-now" :style="nowMarker" />
            </div>
          </div>
        </div>
        <div v-else class="row-empty">
          Ce projet n'a ni dates ni événement : il n'y a pas encore de période à
          afficher. Tu peux saisir les dates du projet dans les Réglages.
        </div>
      </div>

      <!-- Chronologie (2026-08-01) : mêmes lignes cliquables que la
           chronologie de la fiche spectacle. Les blocs de montage/démontage
           apparaissent sans être assignés — ils utilisent le matériel de leur
           événement, voir get_material_schedule côté backend. -->
      <div class="card">
        <div class="repartition-head">
          <div class="card-title">Chronologie</div>
          <div v-if="scheduleWindowLabel" class="schedule-window">{{ scheduleWindowLabel }}</div>
        </div>
        <div class="fiche-hint" style="margin: 10px 0 12px">
          Tout ce qui mobilise ce matériel sur la durée du projet, dans l'ordre :
          spectacles, montages, répétitions, démontages et déplacements. Clique
          une ligne pour aller à sa fiche.
          <template v-if="scheduleOutside > 0">
            <br />
            {{ scheduleOutside }} élément(s) hors de cette fenêtre ne sont pas
            affichés — vérifie les dates du projet dans les Réglages.
          </template>
        </div>
        <div v-if="decoratedSchedule.length > 0" class="row-list">
          <div
            v-for="e in decoratedSchedule"
            :key="e.key"
            class="row row--clickable"
            :class="{ 'row--transit': e.kind === 'transport' }"
            @click="goToEntry(e)"
          >
            <div class="row__badge" :style="{ color: e.typeColor, background: e.typeBg }">
              {{ e.typeLabel }}
            </div>
            <div class="row__body">
              <div class="row__title">{{ e.title }}</div>
              <div class="row__subtitle">{{ e.details }}</div>
            </div>
            <div v-if="e.conflict" class="row__conflict">CONFLIT</div>
          </div>
        </div>
        <div v-else class="row-empty">
          Ce matériel n'est mobilisé nulle part pour l'instant.
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
  max-width: 920px;
}

.hint {
  padding: 32px 40px;
  font: 500 13px system-ui;
  color: rgba(var(--fg-rgb), 0.5);
}

.hint--error {
  color: oklch(0.78 0.16 35);
}

.breadcrumb {
  font: 500 12px system-ui;
  color: rgba(var(--fg-rgb), 0.4);
}

.breadcrumb :deep(a) {
  color: var(--link);
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
  color: rgba(var(--fg-rgb), 0.5);
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
  color: rgba(var(--fg-rgb), 0.5);
  background: rgba(var(--fg-rgb), 0.08);
}

.card {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-notch-lg);
  padding: 20px;
}

/* Même gabarit que SpectacleDetailView.vue/TransportDetailView.vue (dupliqué
   localement, pas de composant partagé pour ces fiches). */
.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
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

.summary-value--muted {
  font-weight: 400;
  color: rgba(var(--fg-rgb), 0.5);
}

.summary-link {
  color: var(--link);
  text-decoration: none;
}

.card-title {
  font: 700 12px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: rgba(var(--fg-rgb), 0.65);
}

.card-text {
  font: 400 13.5px/1.6 system-ui;
  color: rgba(var(--fg-rgb), 0.75);
  margin-top: 14px;
}

.tree {
  position: relative;
  margin-left: 18px;
  padding-left: 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-left: 2px solid rgba(var(--accent-rgb), 0.25);
}

.tree-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: var(--radius-notch-sm);
  background: var(--bg-row);
}

.tree-item::before {
  content: '';
  position: absolute;
  left: -20px;
  top: 50%;
  width: 14px;
  height: 2px;
  background: rgba(var(--accent-rgb), 0.25);
}

.tree-item__body {
  flex: 1;
  min-width: 0;
  text-decoration: none;
}

.tree-item__name {
  font: 600 13px system-ui;
  color: rgb(var(--fg-rgb));
}

.tree-item__meta {
  font: 400 11.5px system-ui;
  color: rgba(var(--fg-rgb), 0.5);
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
  background: var(--bg-row);
}

.repartition-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
}

.schedule-window {
  font: 600 12px var(--font-mono);
  color: rgba(var(--fg-rgb), 0.5);
}

.repartition {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* Axe des jours, aligné sur les mêmes repères que les lignes verticales des
   pistes en dessous. Décalé de la largeur du libellé de ligne. */
.repartition-axis {
  position: relative;
  height: 18px;
  margin-left: 150px;
}

.repartition-axis__tick {
  position: absolute;
  transform: translateX(-50%);
  font: 500 10px var(--font-mono);
  color: rgba(var(--fg-rgb), 0.35);
  white-space: nowrap;
}

.repartition-row {
  display: flex;
  align-items: stretch;
  gap: 10px;
}

.repartition-row__label {
  width: 140px;
  flex: none;
}

.repartition-row__name {
  font: 600 12.5px system-ui;
  color: rgb(var(--fg-rgb));
}

.repartition-row__detail {
  font: 400 10.5px system-ui;
  color: rgba(var(--fg-rgb), 0.45);
}

.repartition-track {
  position: relative;
  flex: 1;
  min-width: 0;
  height: 30px;
  border-radius: 4px;
  background: rgba(var(--fg-rgb), 0.04);
}

.repartition-gridline {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: rgba(var(--fg-rgb), 0.06);
}

/* Un segment = une période de détention. La quantité est écrite dedans plutôt
   qu'en légende : c'est l'information qu'on vient chercher, et elle change
   d'un segment à l'autre quand le stock se sépare. */
.repartition-seg {
  position: absolute;
  top: 5px;
  bottom: 5px;
  border-radius: 3px;
  display: flex;
  align-items: center;
  justify-content: center;
  font: 700 10.5px var(--font-mono);
  color: #211c33;
  overflow: hidden;
}

/* Repère « maintenant » — seulement si la date du jour tombe dans la fenêtre
   du projet, sinon il collerait à un bord et mentirait. */
.repartition-now {
  position: absolute;
  top: -2px;
  bottom: -2px;
  width: 2px;
  background: oklch(0.8 0.16 35);
  border-radius: 1px;
}

/* Même geste que la chronologie de la fiche spectacle : toute la ligne mène
   à la fiche de l'élément. */
.row--clickable {
  cursor: pointer;
}

/* Déplacements en retrait et en plus petit (2026-08-01, demande de Samuel) :
   un transport est un CHANGEMENT DE LIEU entre deux utilisations, pas une
   utilisation. Le décrochage visuel évite de lire la liste comme une suite
   d'engagements de même nature. */
.row--transit {
  margin-left: 32px;
  padding: 7px 12px;
  background: rgba(27, 31, 37, 0.6);
}

.row--transit .row__badge {
  font-size: 9px;
  padding: 1px 6px;
}

.row--transit .row__title {
  font-size: 11.5px;
  font-weight: 500;
  color: rgba(var(--fg-rgb), 0.8);
}

.row--transit .row__subtitle {
  font-size: 10.5px;
}

.row__badge {
  font: 700 10px system-ui;
  text-transform: uppercase;
  padding: 2px 8px;
  border-radius: 0 6px 0 6px;
  flex: none;
}

.row__body {
  flex: 1;
  min-width: 0;
}

.row__title {
  font: 600 13px system-ui;
  color: rgb(var(--fg-rgb));
}

.row__subtitle {
  font: 400 11.5px system-ui;
  color: rgba(var(--fg-rgb), 0.5);
  margin-top: 2px;
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
  color: rgba(var(--fg-rgb), 0.4);
  padding: 10px 12px;
}
</style>

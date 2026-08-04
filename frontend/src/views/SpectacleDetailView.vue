<script setup>
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppShell from '../components/AppShell.vue'
import AssignerMaterielModal from '../components/AssignerMaterielModal.vue'
import AssignerTechnicienModal from '../components/AssignerTechnicienModal.vue'
import { api } from '../api/client'
import { useFicheEdition } from '../composables/useFicheEdition'
import { useSuppressionFiche } from '../composables/useSuppressionFiche'
import { EVENT_TYPE_META } from '../constants/eventTypeMeta'

/**
 * Fiche spectacle — port de SpectacleDetail.dc.html, branché sur l'API réelle.
 *
 * Le prototype montrait des données figées (un seul spectacle "Vertiges" en
 * dur). Ici on charge le vrai spectacle (id dans l'URL), ses conflits
 * (GET /api/shows/{id}/conflicts/), son matériel et ses techniciens assignés,
 * et les transports qui le desservent.
 */

const route = useRoute()
const router = useRouter()

const show = ref(null)
// Fiche du parent quand on est SUR un bloc (montage/répétition/démontage) —
// 2026-07-31, demande de Samuel : « on active le même affichage » sur la
// fiche d'un bloc, pas seulement sur celle de l'événement. `ShowSerializer.
// get_phases()` renvoie toujours `[]` pour un bloc (pas de récursion), donc
// il faut aller chercher les blocs FRÈRES (et l'horaire de l'événement) sur
// le parent — voir `timelineSource`.
const parentShow = ref(null)
const conflicts = ref({ venue_conflicts: [], material_conflicts: [], technician_conflicts: [] })
const showMaterials = ref([])
const showTechnicians = ref([])
const transports = ref([])
const techniciansById = ref(new Map())
// Catalogue complet du matériel du projet (2026-08-02, demande de Samuel) —
// sert uniquement à retrouver `parent_material` pour indenter les composants
// de kit dans « Matériel assigné » (ShowMaterialSerializer n'expose pas ce
// champ, voir `materialsById`/`decoratedMaterials`).
const materials = ref([])

const loading = ref(false)
const loadError = ref(null)

// Couleurs personnalisables depuis Réglages (2026-08-02) — voir
// constants/eventTypeMeta.js, source unique partagée entre cette fiche,
// SpectaclesView.vue, MaterielDetailView.vue et DashboardView.vue.
const typeMeta = EVENT_TYPE_META

// Catégorie du matériel (voir MaterialCategory, models.py) — remplace la
// couleur/nom de département (`department_color`/`department_name`), retirés
// le 2026-07-29 avec le modèle `Department`. Depuis le 2026-07-30, le nom et
// la couleur viennent de l'API (`material_category_name`/`_color` sur
// ShowMaterialSerializer) au lieu d'une table codée en dur ici.
const NO_CATEGORY = { label: 'Sans catégorie', color: 'rgba(var(--fg-rgb),.3)' }

const dateTimeFmt = new Intl.DateTimeFormat('fr-CA', {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
  year: 'numeric',
})
const timeFmt = new Intl.DateTimeFormat('fr-CA', { hour: '2-digit', minute: '2-digit', hour12: false })
const dayShortFmt = new Intl.DateTimeFormat('fr-CA', { weekday: 'short', day: 'numeric', month: 'short' })

function fmtTimeRange(startIso, endIso) {
  return `${timeFmt.format(new Date(startIso))} – ${timeFmt.format(new Date(endIso))}`
}

/**
 * Plage horaire d'un bloc rattaché, affichée dans la carte de résumé.
 *
 * La journée du début est TOUJOURS rappelée (2026-08-01, demande de Samuel :
 * « comme il y a déjà pour la répétition » — une répétition tombe souvent un
 * autre jour que l'événement et affichait donc déjà sa date ; montage,
 * démontage et l'événement lui-même, eux, restaient muets dès qu'ils
 * tombaient le même jour que l'événement, incohérent au premier coup d'œil
 * dans une liste qui mélange les deux cas). La fin, elle, ne répète la
 * journée que si elle diffère de celle du début (bloc à cheval sur minuit) —
 * pas de raison de la doubler sinon.
 */
function fmtBlockRange(startIso, endIso) {
  const debut = new Date(startIso)
  const fin = new Date(endIso)
  const memeJour = (a, b) => a.toDateString() === b.toDateString()
  const debutTexte = `${dayShortFmt.format(debut)} ${timeFmt.format(debut)}`
  const finTexte = memeJour(fin, debut)
    ? timeFmt.format(fin)
    : `${dayShortFmt.format(fin)} ${timeFmt.format(fin)}`
  return `${debutTexte} – ${finTexte}`
}

function initials(name) {
  return name
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join('')
}

async function loadShow() {
  const id = route.params.id
  loading.value = true
  loadError.value = null
  try {
    show.value = await api.get(`/shows/${id}/`)
    // Un bloc de montage/démontage utilise le matériel et l'équipe de son
    // événement (2026-07-31) : on lit les assignations du parent, en lecture
    // seule. Un bloc de RÉPÉTITION a les siennes — copiées de l'événement à sa
    // création, puis modifiables — donc on lit les siennes. Voir `inherited`.
    const heriteDuParent = !!show.value.parent_show
      && show.value.event_type !== 'rehearsal'
    const resourceId = heriteDuParent ? show.value.parent_show : id
    const [conflictsData, smData, stData, trData, parentData, matData] = await Promise.all([
      api.get(`/shows/${id}/conflicts/`),
      api.get('/show-materials/', { show: resourceId }),
      api.get('/show-technicians/', { show: resourceId }),
      api.get('/transports/', { show: id }),
      // `phases` est toujours vide côté API pour un bloc (pas de récursion) —
      // pour afficher la même chronologie sur sa fiche, on va chercher les
      // blocs frères (et l'horaire de l'événement) sur le parent.
      show.value.parent_show ? api.get(`/shows/${show.value.parent_show}/`) : Promise.resolve(null),
      api.get('/materials/', { project: show.value.project }),
    ])
    conflicts.value = conflictsData
    showMaterials.value = Array.isArray(smData) ? smData : (smData.results ?? [])
    showTechnicians.value = Array.isArray(stData) ? stData : (stData.results ?? [])
    transports.value = Array.isArray(trData) ? trData : (trData.results ?? [])
    parentShow.value = parentData
    materials.value = Array.isArray(matData) ? matData : (matData.results ?? [])

    const techniciansData = await api.get('/technicians/', { project: show.value.project })
    const techniciansList = Array.isArray(techniciansData) ? techniciansData : (techniciansData.results ?? [])
    techniciansById.value = new Map(techniciansList.map((t) => [t.id, t]))
  } catch (e) {
    loadError.value = e
  } finally {
    loading.value = false
  }
}

watch(() => route.params.id, loadShow, { immediate: true })

const typeInfo = computed(() => typeMeta[show.value?.event_type] ?? typeMeta.performance)

/// Sur un bloc de montage/démontage, le matériel et l'équipe affichés sont ceux
// de l'événement : on les montre pour référence, sans possibilité de les
// modifier ici. Un bloc de répétition rattaché est autonome (précision de
// Samuel, 2026-07-31) — il a reçu une copie à sa création et se modifie comme
// n'importe quel événement. Mêmes types que `Show.INHERITING_PHASE_TYPES`.
const inherited = computed(
  () => !!show.value?.parent_show && show.value.event_type !== 'rehearsal',
)

// Bloc de répétition rattaché : autonome, mais amorcé par une copie — d'où le
// rappel affiché, pour que la divergence avec l'événement ne surprenne pas.
const copiedFromEvent = computed(
  () => !!show.value?.parent_show && show.value.event_type === 'rehearsal',
)

// N'importe quel bloc (montage/démontage/répétition), tous types confondus —
// contrairement à `inherited` ci-dessus, qui ne couvre que montage/démontage.
// Sert au champ « Titre »/« Précision » du formulaire d'édition (2026-08-02) :
// un bloc n'a plus de nom complet à saisir, voir `Show.display_title`.
const isBlock = computed(() => !!show.value?.parent_show)

const hasConflicts = computed(
  () =>
    (conflicts.value.venue_conflicts?.length ?? 0) +
      (conflicts.value.material_conflicts?.length ?? 0) +
      (conflicts.value.technician_conflicts?.length ?? 0) >
    0,
)

const conflictSummary = computed(() => {
  const parts = []
  const mat = conflicts.value.material_conflicts ?? []
  const tech = conflicts.value.technician_conflicts ?? []
  const venue = conflicts.value.venue_conflicts ?? []
  if (mat.length) {
    const names = [...new Set(mat.map((c) => c.material_name))].join(', ')
    parts.push(`Matériel : ${names} — chevauche ${mat.map((c) => `« ${c.show_title} »`).join(', ')}`)
  }
  if (tech.length) {
    const names = [...new Set(tech.map((c) => c.technician_name).filter(Boolean))].join(', ')
    parts.push(`Technicien : ${names} — chevauche ${tech.map((c) => `« ${c.show_title} »`).join(', ')}`)
  }
  if (venue.length) {
    parts.push(`Lieu — chevauche ${venue.map((c) => `« ${c.show_title} »`).join(', ')}`)
  }
  return parts.join(' · ')
})

const materialConflictIds = computed(
  () => new Set((conflicts.value.material_conflicts ?? []).map((c) => c.material_id)),
)
const technicianConflictIds = computed(
  () => new Set((conflicts.value.technician_conflicts ?? []).map((c) => c.technician_id)),
)

// `parent_material` par id de matériel — `ShowMaterialSerializer` ne
// l'expose pas (voir la recherche du 2026-08-02), d'où le croisement avec le
// catalogue complet chargé dans `loadShow`.
const parentMaterialById = computed(() => new Map(materials.value.map((m) => [m.id, m.parent_material])))

/**
 * Sous-items de kit en retrait (2026-08-02, demande de Samuel) : même
 * traitement que le panneau de sélection du Parcours Matériel — un
 * composant n'est marqué `nested` (et déplacé juste après son kit) que si le
 * kit parent est LUI AUSSI assigné à ce spectacle ; sinon il reste affiché à
 * plat, orphelin plutôt que perdu.
 */
const decoratedMaterials = computed(() => {
  const assignedIds = new Set(showMaterials.value.map((sm) => sm.material))
  const items = showMaterials.value.map((sm) => {
    const meta = sm.material_category
      ? { label: sm.material_category_name, color: sm.material_category_color }
      : NO_CATEGORY
    const parentId = parentMaterialById.value.get(sm.material) ?? null
    return {
      ...sm,
      catLabel: meta.label,
      catColor: meta.color,
      conflict: materialConflictIds.value.has(sm.material),
      nested: parentId != null && assignedIds.has(parentId),
    }
  })

  const enfants = new Map()
  items.forEach((it) => {
    if (!it.nested) return
    const parentId = parentMaterialById.value.get(it.material)
    if (!enfants.has(parentId)) enfants.set(parentId, [])
    enfants.get(parentId).push(it)
  })

  const ordonne = []
  items.forEach((it) => {
    if (it.nested) return
    ordonne.push(it)
    ;(enfants.get(it.material) ?? []).forEach((child) => ordonne.push(child))
  })
  return ordonne
})

const decoratedTechnicians = computed(() =>
  showTechnicians.value.map((st) => {
    const tech = techniciansById.value.get(st.technician)
    return {
      ...st,
      role: tech?.specialty || '—',
      initials: initials(st.technician_name || '?'),
      conflict: technicianConflictIds.value.has(st.technician),
    }
  }),
)

// Triés chronologiquement (2026-08-01, demande de Samuel) — l'API ne les
// renvoie pas déjà triés. Une proposition sans `scheduled_datetime` (pas
// encore complétée) va en fin de liste plutôt que de casser le tri, même
// convention que la chronologie de la fiche matériel (2026-08-01, note
// dédiée dans CLAUDE.md).
const decoratedTransports = computed(() =>
  transports.value
    .map((tr) => ({
      ...tr,
      // Tournées multi-arrêts (2026-08-04) : trajet = la séquence complète
      // des arrêts ; le type livraison/ramassage n'existe plus.
      routeLabel: (tr.stops ?? []).map((s) => s.venue_name).join(' → '),
      time: tr.scheduled_datetime
        ? `${dayShortFmt.format(new Date(tr.scheduled_datetime))} ${timeFmt.format(new Date(tr.scheduled_datetime))}`
        : 'à planifier',
    }))
    .sort((a, b) => {
      if (!a.scheduled_datetime && !b.scheduled_datetime) return 0
      if (!a.scheduled_datetime) return 1
      if (!b.scheduled_datetime) return -1
      return new Date(a.scheduled_datetime) - new Date(b.scheduled_datetime)
    }),
)

// --- Édition de la fiche ---
// Même pattern que les autres fiches (voir useFicheEdition) : bouton
// « Modifier la fiche » dans l'entête, bascule complète, un seul PATCH.
// Spécificité du spectacle : le conflit de lieu est bloquant mais overridable
// (`force: true`, voir ShowSerializer.validate) — il a donc son propre
// bandeau, distinct des erreurs de champ.

const venues = ref([])

const {
  editing, draft, saving, saveError, fieldErrors, lastError, canSave,
  startEdit: beginEdit, cancelEdit, save,
} = useFicheEdition({
  entity: show,
  endpoint: '/shows',
  fields: [
    'title', 'venue', 'event_type', 'start_datetime', 'end_datetime',
    'buffer_before_minutes', 'buffer_after_minutes', 'notes',
  ],
  errorMessage: "Impossible d'enregistrer les changements.",
  toDraft: (s) => ({
    title: s.title ?? '',
    venue: s.venue,
    event_type: s.event_type,
    // `datetime-local` attend `YYYY-MM-DDTHH:mm` — on tronque l'ISO renvoyé
    // par DRF, et on reconvertit à l'envoi (voir toPayload).
    start: s.start_datetime.slice(0, 16),
    end: s.end_datetime.slice(0, 16),
    buffer_before_minutes: s.buffer_before_minutes,
    buffer_after_minutes: s.buffer_after_minutes,
    notes: s.notes ?? '',
  }),
  // Le titre reste requis pour un événement, mais devient une précision
  // facultative sur un bloc (2026-08-02) — voir `isBlock`/`Show.display_title`.
  isValid: (d) => (isBlock.value || d.title.trim().length > 0) && !!d.start && !!d.end,
  toPayload: (d) => ({
    title: d.title.trim(),
    venue: d.venue,
    event_type: d.event_type,
    start_datetime: new Date(d.start).toISOString(),
    end_datetime: new Date(d.end).toISOString(),
    buffer_before_minutes: d.buffer_before_minutes,
    buffer_after_minutes: d.buffer_after_minutes,
    notes: d.notes.trim(),
  }),
})

// Le bandeau « Forcer » n'apparaît que sur une réponse contenant `conflicts`
// (chevauchement de lieu) — les autres erreurs restent des erreurs normales.
const editConflict = computed(() => (lastError.value?.conflicts ? lastError.value : null))

async function startEdit() {
  const venuesData = await api.get('/venues/', { project: show.value.project })
  venues.value = Array.isArray(venuesData) ? venuesData : (venuesData.results ?? [])
  beginEdit()
}

async function saveEdit(force = false) {
  // Recharge derrière l'enregistrement : changer l'horaire, le lieu ou les
  // buffers modifie les conflits et la fenêtre effective affichés.
  if (await save(force ? { force: true } : {})) await loadShow()
}

// --- Suppression (2026-07-30) ---
// Autorisée, mais emporte en cascade les assignations et les déplacements du
// spectacle (FK en CASCADE) : la confirmation annonce les décomptes exposés
// par `ShowSerializer.deletion_impact`.
const {
  confirming, deleting, deleteError, askDelete, cancelDelete, confirmDelete,
} = useSuppressionFiche({ endpoint: '/shows', redirectTo: '/spectacles' })

const deletionImpact = computed(() => show.value?.deletion_impact ?? null)
const hasCascade = computed(
  () => !!deletionImpact.value && Object.values(deletionImpact.value).some((n) => n > 0),
)

// --- Blocs rattachés (montage / répétition / démontage) ---
// Un bloc est un `Show` complet rattaché par `parent_show` : il a son lieu
// (le même que l'événement) et ses horaires. Son matériel et son équipe sont
// en revanche ceux de l'événement (2026-07-31) — d'où le simple lien vers sa
// fiche plutôt qu'une édition en place.

const phaseFmt = new Intl.DateTimeFormat('fr-CA', {
  weekday: 'short', day: 'numeric', month: 'short',
  hour: '2-digit', minute: '2-digit', hour12: false,
})

/**
 * Source de la chronologie : l'événement lui-même quand on est sur SA fiche,
 * le parent quand on est sur la fiche d'un bloc (2026-07-31, demande de
 * Samuel : « on active le même affichage » sur les fiches de bloc aussi).
 * `source.phases` porte alors les blocs FRÈRES — y compris celui qu'on
 * regarde, listé comme les autres et simplement marqué `isCurrent`.
 */
const timelineSource = computed(() => (show.value?.parent_show ? parentShow.value : show.value))

const decoratedPhases = computed(() => {
  const source = timelineSource.value
  if (!source) return []
  return (source.phases ?? []).map((p) => {
    const meta = typeMeta[p.event_type] ?? typeMeta.rehearsal
    return {
      ...p,
      typeLabel: meta.label,
      typeColor: meta.color,
      typeBg: meta.bg,
      // Avant ou après ? Déduit de l'horaire plutôt que stocké : impossible
      // que les deux se contredisent.
      position: new Date(p.start_datetime) < new Date(source.start_datetime) ? 'Avant' : 'Après',
      range: `${phaseFmt.format(new Date(p.start_datetime))} – ${phaseFmt.format(new Date(p.end_datetime))}`,
      // Version compacte pour la carte de résumé, en haut de la fiche.
      summaryRange: fmtBlockRange(p.start_datetime, p.end_datetime),
      // Un montage/démontage puise dans les ressources de l'événement ; une
      // répétition rattachée a les siennes (voir `inherits_resources`, exposé
      // par l'API depuis le 2026-07-31).
      resourceNote: p.inherits_resources
        ? "matériel et équipe de l'événement"
        : `${p.material_count} matériel · ${p.technician_count} technicien(s)`,
      // La fiche affichée en ce moment, pour la mettre en couleur et éviter
      // de proposer de naviguer vers la page où on se trouve déjà.
      isCurrent: show.value && p.id === show.value.id,
    }
  })
})

/**
 * Chronologie complète (2026-07-31, demande de Samuel) : la liste « Montage,
 * répétition, démontage » n'affichait que les blocs rattachés, sans la ligne
 * de l'événement lui-même — pourtant déjà visible plus haut dans la carte de
 * résumé. On fusionne les deux en une seule liste triée par heure de début,
 * avec une entrée synthétique (`isEvent: true`, pas de bouton de
 * suppression — ce n'est pas un bloc) pour l'événement.
 */
const timelineEntries = computed(() => {
  const source = timelineSource.value
  if (!source) return []
  const meta = typeMeta[source.event_type] ?? typeMeta.performance
  const evenement = {
    id: source.id,
    isEvent: true,
    isCurrent: show.value && source.id === show.value.id,
    typeLabel: meta.label,
    typeColor: meta.color,
    typeBg: meta.bg,
    title: source.title,
    start_datetime: source.start_datetime,
    range: `${phaseFmt.format(new Date(source.start_datetime))} – ${phaseFmt.format(new Date(source.end_datetime))}`,
    // La journée s'affiche maintenant ici aussi (voir `fmtBlockRange`) —
    // cohérent avec les blocs de la même liste.
    summaryRange: fmtBlockRange(source.start_datetime, source.end_datetime),
  }
  return [...decoratedPhases.value, evenement].sort(
    (a, b) => new Date(a.start_datetime) - new Date(b.start_datetime),
  )
})

/** Navigue vers la fiche d'une ligne de la chronologie — sauf celle où on est déjà. */
function goToItem(entry) {
  if (entry.isCurrent) return
  router.push(`/spectacles/${entry.id}`)
}

const addingPhase = ref(false)
const phaseForm = ref(null)
const phaseError = ref(null)
const savingPhase = ref(false)

function startAddPhase(kind) {
  const debutShow = new Date(show.value.start_datetime)
  const finShow = new Date(show.value.end_datetime)
  // Proposition par défaut : 3 h avant pour un montage/une répétition,
  // 2 h après pour un démontage — collées à l'événement.
  const avant = kind !== 'teardown'
  const debut = avant ? new Date(debutShow.getTime() - 3 * 3600e3) : new Date(finShow)
  const fin = avant ? new Date(debutShow) : new Date(finShow.getTime() + 2 * 3600e3)

  phaseForm.value = {
    event_type: kind,
    // Précision optionnelle seulement (2026-08-02) — le nom du spectacle
    // n'est plus recopié ici, voir `phasePreviewTitle` et `Show.display_title`
    // côté backend, qui le relit dynamiquement sur le parent.
    title: '',
    start: toLocalInput(debut),
    end: toLocalInput(fin),
  }
  phaseError.value = null
  addingPhase.value = true
}

/**
 * Aperçu du titre affiché une fois le bloc créé — mime `Show.display_title`
 * côté backend (2026-08-02) : le nom du spectacle n'est plus stocké en
 * double dans le bloc, donc rien à relire tant qu'il n'existe pas encore.
 */
const phasePreviewTitle = computed(() => {
  if (!phaseForm.value || !show.value) return ''
  const label = typeMeta[phaseForm.value.event_type]?.label ?? phaseForm.value.event_type
  const precision = phaseForm.value.title.trim()
  return `${precision ? `${label} ${precision}` : label} — ${show.value.title}`
})

/**
 * Même aperçu que `phasePreviewTitle`, pour le mode édition d'un bloc déjà
 * créé (`fiche-edit-card`) — mêmes règles, sur `draft`/`show.parent_show_title`
 * plutôt que `phaseForm`/`show.title`.
 */
const editPreviewTitle = computed(() => {
  if (!isBlock.value || !draft.value || !show.value) return ''
  const label = typeMeta[draft.value.event_type]?.label ?? draft.value.event_type
  const precision = draft.value.title.trim()
  return `${precision ? `${label} ${precision}` : label} — ${show.value.parent_show_title}`
})

function toLocalInput(date) {
  // `datetime-local` attend l'heure LOCALE : `toISOString()` renverrait UTC
  // et décalerait la proposition de plusieurs heures.
  const decale = new Date(date.getTime() - date.getTimezoneOffset() * 60000)
  return decale.toISOString().slice(0, 16)
}

function cancelAddPhase() {
  addingPhase.value = false
  phaseForm.value = null
  phaseError.value = null
}

async function savePhase(force = false) {
  savingPhase.value = true
  phaseError.value = null
  try {
    await api.post('/shows/', {
      project: show.value.project,
      venue: show.value.venue,
      parent_show: show.value.id,
      event_type: phaseForm.value.event_type,
      title: phaseForm.value.title.trim(),
      start_datetime: new Date(phaseForm.value.start).toISOString(),
      end_datetime: new Date(phaseForm.value.end).toISOString(),
      // Un bloc décrit déjà explicitement son créneau : lui ajouter des
      // marges reviendrait à compter le montage deux fois.
      buffer_before_minutes: 0,
      buffer_after_minutes: 0,
      force,
    })
    cancelAddPhase()
    await loadShow()
  } catch (e) {
    phaseError.value = e.data
  } finally {
    savingPhase.value = false
  }
}

async function removePhase(phase) {
  await api.delete(`/shows/${phase.id}/`)
  await loadShow()
}

watch(() => route.params.id, cancelEdit)

// --- Assignation de matériel/technicien (modales) ---

const showAssignMateriel = ref(false)
const showAssignTechnicien = ref(false)

const showLabel = computed(() =>
  show.value ? `${show.value.display_title} · ${dateTimeFmt.format(new Date(show.value.start_datetime))}` : '',
)

async function onMaterielAssigned() {
  showAssignMateriel.value = false
  await loadShow()
}

// Retrait immédiat (pas de modale de confirmation), même comportement que
// le bouton « ✕ » de la liste de matériel sur TransportDetailView.vue —
// mais ici DELETE /show-materials/{id}/ appelé tout de suite : contrairement
// au transport, ShowMaterial n'est pas du staging local, chaque ligne est
// déjà persistée dès l'assignation.
async function removeMaterial(showMaterialId) {
  await api.delete(`/show-materials/${showMaterialId}/`)
  await loadShow()
}

async function onTechnicienAssigned(payload) {
  // La modale peut assigner plusieurs techniciens d'un coup (2026-07-30) : on
  // ne la ferme que quand elle a tout passé, pour laisser visibles les
  // conflits à forcer ou les erreurs à corriger.
  if (payload?.done !== false) showAssignTechnicien.value = false
  await loadShow()
}

</script>

<template>
  <AppShell>
    <div v-if="loading" class="hint">Chargement…</div>
    <div v-else-if="loadError" class="hint hint--error">
      Impossible de charger ce spectacle. Es-tu connecté (session Django) ?
    </div>

    <div v-else-if="show" class="page">
      <div class="breadcrumb">
        <RouterLink to="/spectacles">Spectacles</RouterLink> /
        <template v-if="show.parent_show">
          <RouterLink :to="`/spectacles/${show.parent_show}`">{{ show.parent_show_title }}</RouterLink> /
        </template>
        {{ show.display_title }}
      </div>

      <div class="header">
        <div>
          <div class="header__top">
            <h1 class="header__title">{{ show.display_title }}</h1>
            <div class="header__type" :style="{ color: typeInfo.color, background: typeInfo.bg }">
              {{ typeInfo.label }}
            </div>
          </div>
          <div class="header__meta">{{ show.venue_name }} · {{ dateTimeFmt.format(new Date(show.start_datetime)) }}</div>
        </div>
        <div class="fiche-actions">
          <button v-if="!editing" type="button" class="fiche-btn" @click="startEdit()">
            Modifier la fiche
          </button>
          <template v-else>
            <button
              type="button"
              class="fiche-btn fiche-btn--primary"
              :disabled="!canSave"
              @click="saveEdit(false)"
            >
              {{ saving ? 'Enregistrement…' : 'Enregistrer' }}
            </button>
            <button type="button" class="fiche-btn" :disabled="saving" @click="cancelEdit">
              Annuler
            </button>
          </template>
        </div>
      </div>

      <div v-if="hasConflicts" class="alert">
        <span class="alert__dot" />
        <div class="alert__body">
          <div class="alert__title">Conflit d'horaire</div>
          <div class="alert__subtitle">{{ conflictSummary }}</div>
        </div>
      </div>

      <!-- Mode édition : un seul PATCH à l'enregistrement -->
      <div v-if="editing" class="fiche-edit-card">
        <div class="fiche-grid">
          <label class="fiche-field fiche-field--wide">
            <!-- Un bloc n'a plus de nom complet à saisir (2026-08-02) : le
                 nom du spectacle n'est plus dupliqué ici, seulement une
                 précision facultative ajoutée après le type — voir
                 `Show.display_title` côté backend et `editPreviewTitle`. -->
            <span class="fiche-label">{{ isBlock ? 'Précision (optionnel)' : 'Titre' }}</span>
            <input
              v-model="draft.title"
              class="fiche-input"
              :placeholder="isBlock ? 'ex. technique, costumes…' : ''"
              :class="{ 'fiche-input--error': fieldErrors.title }"
            />
            <span v-if="fieldErrors.title" class="fiche-error">{{ fieldErrors.title }}</span>
            <span v-if="isBlock" class="fiche-hint">Aperçu : {{ editPreviewTitle }}</span>
          </label>

          <label class="fiche-field">
            <span class="fiche-label">Lieu</span>
            <select
              v-model="draft.venue"
              class="fiche-input"
              :class="{ 'fiche-input--error': fieldErrors.venue }"
            >
              <option v-for="v in venues" :key="v.id" :value="v.id">{{ v.name }}</option>
            </select>
            <span v-if="fieldErrors.venue" class="fiche-error">{{ fieldErrors.venue }}</span>
          </label>

          <label class="fiche-field">
            <span class="fiche-label">Type</span>
            <select v-model="draft.event_type" class="fiche-input">
              <option value="rehearsal">Répétition</option>
              <option value="performance">Représentation</option>
              <option value="storage">Entreposage</option>
            </select>
          </label>

          <!-- `step` est en secondes : 300 = minutes par pas de 5 dans le
               sélecteur natif du navigateur. -->
          <label class="fiche-field">
            <span class="fiche-label">Début</span>
            <input
              v-model="draft.start"
              type="datetime-local"
              step="300"
              class="fiche-input"
              :class="{ 'fiche-input--error': fieldErrors.start_datetime }"
            />
            <span v-if="fieldErrors.start_datetime" class="fiche-error">
              {{ fieldErrors.start_datetime }}
            </span>
          </label>

          <label class="fiche-field">
            <span class="fiche-label">Fin</span>
            <input
              v-model="draft.end"
              type="datetime-local"
              step="300"
              class="fiche-input"
              :class="{ 'fiche-input--error': fieldErrors.end_datetime }"
            />
            <span v-if="fieldErrors.end_datetime" class="fiche-error">
              {{ fieldErrors.end_datetime }}
            </span>
          </label>

          <label class="fiche-field">
            <span class="fiche-label">Buffer avant (min)</span>
            <input
              v-model.number="draft.buffer_before_minutes"
              type="number"
              min="0"
              class="fiche-input"
              :class="{ 'fiche-input--error': fieldErrors.buffer_before_minutes }"
            />
            <span v-if="fieldErrors.buffer_before_minutes" class="fiche-error">
              {{ fieldErrors.buffer_before_minutes }}
            </span>
          </label>

          <label class="fiche-field">
            <span class="fiche-label">Buffer après (min)</span>
            <input
              v-model.number="draft.buffer_after_minutes"
              type="number"
              min="0"
              class="fiche-input"
              :class="{ 'fiche-input--error': fieldErrors.buffer_after_minutes }"
            />
            <span v-if="fieldErrors.buffer_after_minutes" class="fiche-error">
              {{ fieldErrors.buffer_after_minutes }}
            </span>
          </label>

          <label class="fiche-field fiche-field--full">
            <span class="fiche-label">Notes</span>
            <textarea v-model="draft.notes" rows="3" class="fiche-input fiche-input--area" />
          </label>
        </div>

        <div class="fiche-hint">
          Les buffers élargissent la fenêtre effective du spectacle (montage/démontage)
          et c'est cette fenêtre qui sert à la détection de conflits.
        </div>
        <div v-if="saveError" class="fiche-error">{{ saveError }}</div>

        <div class="fiche-danger">
          <div class="fiche-danger__hint">
            Supprimer ce spectacle retire aussi ses assignations et ses déplacements.
          </div>
          <button type="button" class="fiche-btn fiche-btn--danger" @click="askDelete">
            Supprimer ce spectacle
          </button>
        </div>

        <div v-if="editConflict" class="edit-conflict">
          <div>{{ editConflict.detail }}</div>
          <button type="button" class="fiche-btn fiche-btn--primary" @click="saveEdit(true)">
            Forcer malgré le conflit
          </button>
        </div>
      </div>

      <div class="card summary-grid">
        <div>
          <div class="summary-label">Horaire prévu</div>
          <div class="summary-value">{{ fmtTimeRange(show.start_datetime, show.end_datetime) }}</div>
        </div>
        <div>
          <div class="summary-label">Fenêtre effective</div>
          <div class="summary-value summary-value--accent">
            {{ fmtTimeRange(show.engagement_start, show.engagement_end) }}
          </div>
        </div>
        <div>
          <div class="summary-label">Buffers</div>
          <div class="summary-value">
            +{{ show.buffer_before_minutes }}min avant / +{{ show.buffer_after_minutes }}min après
          </div>
        </div>
        <div>
          <div class="summary-label">Lieu</div>
          <div class="summary-value">{{ show.venue_name }}</div>
        </div>

        <!-- Blocs rattachés, en ordre chronologique — et depuis le 2026-07-31,
             l'événement lui-même y figure aussi (`timelineEntries`), pas
             seulement les blocs : situer les blocs par rapport à l'événement
             se lit d'un coup d'œil sans remonter à « Horaire prévu ». Depuis
             le 2026-08-01, la « Fenêtre effective » affichée à gauche source
             `engagement_start`/`engagement_end` (pas `effective_start`/`_end`)
             et couvre donc déjà montage/démontage + buffer — mais PAS une
             répétition rattachée, autonome (voir `Show.engagement_start` côté
             backend) : cette liste peut donc encore déborder la fenêtre
             affichée si une répétition est planifiée hors de ce créneau. -->
        <div class="summary-phases">
          <div class="summary-label">Blocs rattachés</div>
          <div
            v-for="p in timelineEntries"
            :key="`sum-${p.id}`"
            class="summary-phase"
            :class="{
              'summary-phase--event': p.isEvent,
              'summary-phase--current': p.isCurrent,
              'summary-phase--clickable': !p.isCurrent,
            }"
            @click="goToItem(p)"
          >
            <span
              class="summary-phase__tag"
              :style="{ color: p.typeColor, background: p.typeBg }"
            >{{ p.typeLabel }}</span>
            <span class="summary-phase__range">{{ p.summaryRange }}</span>
            <span class="summary-phase__title">{{ p.title }}</span>
          </div>
        </div>
      </div>

      <div v-if="confirming" class="fiche-confirm-backdrop" @click.self="cancelDelete">
        <div class="fiche-confirm">
          <div class="fiche-confirm__title">Supprimer « {{ show.display_title }} » ?</div>
          <p class="fiche-confirm__text">Cette action est définitive.</p>
          <template v-if="hasCascade">
            <p class="fiche-confirm__text">Seront supprimés en même temps :</p>
            <ul class="fiche-confirm__list">
              <li v-if="deletionImpact.materials > 0">
                {{ deletionImpact.materials }} assignation(s) de matériel
              </li>
              <li v-if="deletionImpact.technicians > 0">
                {{ deletionImpact.technicians }} assignation(s) de technicien
              </li>
              <li v-if="deletionImpact.transports > 0">
                {{ deletionImpact.transports }} déplacement(s)
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
              @click="confirmDelete(show.id)"
            >
              {{ deleting ? 'Suppression…' : 'Supprimer' }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="!editing && show.notes" class="card">
        <div class="card-title">Notes</div>
        <div class="card-text">{{ show.notes }}</div>
      </div>

      <div class="card">
        <div class="card-header">
          <div class="card-title">
            Matériel assigné<template v-if="inherited"> — hérité de l'événement</template>
          </div>
          <div v-if="!inherited" class="card-action" @click="showAssignMateriel = true">
            + Assigner du matériel
          </div>
          <RouterLink v-else :to="`/spectacles/${show.parent_show}`" class="card-action">
            Gérer sur l'événement →
          </RouterLink>
        </div>
        <div class="row-list">
          <div
            v-for="m in decoratedMaterials"
            :key="m.id"
            class="row row--compact"
            :class="{ 'row--nested': m.nested }"
          >
            <span class="row__dot" :style="{ background: m.catColor }" />
            <div class="row__body">
              <div class="row__title">
                {{ m.material_name }}
                <span class="row__cat">· {{ m.catLabel }}</span>
                <span v-if="m.quantity > 1" class="row__qty">({{ m.quantity }})</span>
              </div>
            </div>
            <div v-if="m.conflict" class="row__conflict">CONFLIT</div>
            <div v-if="!inherited" class="row__remove" @click="removeMaterial(m.id)">✕</div>
          </div>
          <div v-if="decoratedMaterials.length === 0" class="row-empty">Aucun matériel assigné.</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <div class="card-title">
            Techniciens assignés<template v-if="inherited"> — hérités de l'événement</template>
          </div>
          <div v-if="!inherited" class="card-action" @click="showAssignTechnicien = true">
            + Assigner un technicien
          </div>
          <RouterLink v-else :to="`/spectacles/${show.parent_show}`" class="card-action">
            Gérer sur l'événement →
          </RouterLink>
        </div>
        <div class="row-list">
          <div v-for="t in decoratedTechnicians" :key="t.id" class="row">
            <div class="row__avatar">{{ t.initials }}</div>
            <div class="row__body">
              <div class="row__title">{{ t.technician_name }}</div>
              <div class="row__subtitle">{{ t.role }}</div>
            </div>
            <div v-if="t.conflict" class="row__conflict">CONFLIT</div>
          </div>
          <div v-if="decoratedTechnicians.length === 0" class="row-empty">Aucun technicien assigné.</div>
        </div>
      </div>

      <div v-if="inherited" class="inherit-note">
        Ce bloc fait partie de « {{ show.parent_show_title }} » : il mobilise le
        même matériel et la même équipe, sur toute la durée montage → démontage.
        Les assignations se gèrent sur l'événement.
      </div>

      <div v-else-if="copiedFromEvent" class="inherit-note">
        Cette répétition est rattachée à « {{ show.parent_show_title }} », mais
        elle a son propre matériel et sa propre équipe : la liste ci-dessus a
        été copiée de l'événement à la création du bloc, et se modifie ici sans
        rien changer à l'événement.
      </div>

      <!-- Blocs rattachés (2026-07-31) : montage/répétition en amont,
           démontage en aval. Affichée aussi sur la fiche d'un bloc (2026-07-31,
           suite, demande de Samuel) — `timelineSource` va alors chercher les
           blocs frères sur le parent. Seuls les boutons d'ajout restent
           réservés à la fiche de l'événement : créer un bloc depuis la fiche
           d'un autre bloc l'accrocherait à CE bloc, pas à l'événement (la API
           refuse plus d'un niveau de hiérarchie). -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">Montage, répétition, démontage</div>
          <div v-if="!show.parent_show" class="phase-actions">
            <span class="card-action" @click="startAddPhase('setup')">+ Montage</span>
            <span class="card-action" @click="startAddPhase('rehearsal')">+ Répétition</span>
            <span class="card-action" @click="startAddPhase('teardown')">+ Démontage</span>
          </div>
        </div>

        <div class="fiche-hint" style="margin-bottom: 10px">
          Chronologie complète — la ligne « Événement » est le spectacle
          lui-même, et celle en surbrillance est la fiche affichée en ce
          moment. Clique une ligne pour aller directement à sa fiche.
        </div>

        <div class="row-list">
          <div
            v-for="p in timelineEntries"
            :key="p.id"
            class="row"
            :class="{ 'row--event': p.isEvent, 'row--current': p.isCurrent, 'row--clickable': !p.isCurrent }"
            @click="goToItem(p)"
          >
            <div class="row__badge" :style="{ color: p.typeColor, background: p.typeBg }">
              {{ p.typeLabel }}
            </div>
            <div class="row__body">
              <span class="row__title">{{ p.title }}</span>
              <div class="row__subtitle">
                <template v-if="p.isEvent">Événement · {{ p.range }}</template>
                <template v-else>{{ p.position }} · {{ p.range }} · {{ p.resourceNote }}</template>
              </div>
            </div>
            <div
              v-if="!p.isEvent && !p.isCurrent"
              class="row__remove"
              title="Supprimer ce bloc"
              @click.stop="removePhase(p)"
            >✕</div>
          </div>
          <div v-if="decoratedPhases.length === 0" class="row-empty">
            Aucun bloc rattaché. Un bloc occupe le lieu et compte dans la détection
            de conflits. Un montage ou un démontage mobilise le matériel et l'équipe
            de l'événement ; une répétition rattachée en reçoit une copie qu'on ajuste.
          </div>
        </div>

        <div v-if="addingPhase" class="phase-form">
          <div class="fiche-grid">
            <label class="fiche-field fiche-field--wide">
              <span class="fiche-label">Précision (optionnel)</span>
              <input v-model="phaseForm.title" class="fiche-input" placeholder="ex. technique, costumes…" />
              <span class="fiche-hint">Aperçu : {{ phasePreviewTitle }}</span>
            </label>
            <label class="fiche-field">
              <span class="fiche-label">Type</span>
              <select v-model="phaseForm.event_type" class="fiche-input">
                <option value="setup">Montage</option>
                <option value="rehearsal">Répétition</option>
                <option value="teardown">Démontage</option>
              </select>
            </label>
            <label class="fiche-field">
              <span class="fiche-label">Début</span>
              <input v-model="phaseForm.start" type="datetime-local" step="300" class="fiche-input" />
            </label>
            <label class="fiche-field">
              <span class="fiche-label">Fin</span>
              <input v-model="phaseForm.end" type="datetime-local" step="300" class="fiche-input" />
            </label>
          </div>
          <div class="fiche-hint">
            Le bloc se déroule au même lieu que l'événement ({{ show.venue_name }}).
          </div>
          <div v-if="phaseError && !phaseError.conflicts" class="fiche-error">
            {{ phaseError.detail ?? phaseError.venue?.[0] ?? phaseError.parent_show?.[0]
               ?? "Impossible d'enregistrer ce bloc." }}
          </div>
          <div v-if="phaseError && phaseError.conflicts" class="edit-conflict">
            <div>{{ phaseError.detail }}</div>
            <button type="button" class="fiche-btn fiche-btn--primary" @click="savePhase(true)">
              Forcer malgré le conflit
            </button>
          </div>
          <div class="phase-form__actions">
            <button type="button" class="fiche-btn" :disabled="savingPhase" @click="cancelAddPhase">
              Annuler
            </button>
            <button
              type="button"
              class="fiche-btn fiche-btn--primary"
              :disabled="savingPhase"
              @click="savePhase(false)"
            >
              {{ savingPhase ? 'Enregistrement…' : 'Ajouter le bloc' }}
            </button>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-title" style="margin-bottom: 14px">Transports liés</div>
        <div class="row-list">
          <div v-for="tr in decoratedTransports" :key="tr.id" class="row">
            <div class="row__badge">Tournée</div>
            <div class="row__body row__body--flex">{{ tr.routeLabel }}</div>
            <div class="row__time">{{ tr.time }}</div>
          </div>
          <div v-if="decoratedTransports.length === 0" class="row-empty">Aucun transport lié.</div>
        </div>
      </div>
    </div>

    <AssignerMaterielModal
      v-if="showAssignMateriel && show"
      :show-id="show.id"
      :project-id="show.project"
      :show-label="showLabel"
      :assigned-materials="showMaterials"
      @close="showAssignMateriel = false"
      @assigned="onMaterielAssigned"
    />
    <AssignerTechnicienModal
      v-if="showAssignTechnicien && show"
      :show-id="show.id"
      :project-id="show.project"
      :show-label="showLabel"
      :assigned-technicians="showTechnicians"
      @close="showAssignTechnicien = false"
      @assigned="onTechnicienAssigned"
    />
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
  flex-wrap: wrap;
}

.header__type {
  font: 700 10px system-ui;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 3px 9px;
  border-radius: 0 6px 0 6px;
}

.header__meta {
  font: 400 13px system-ui;
  color: rgba(var(--fg-rgb), 0.5);
  margin-top: 6px;
}

.alert {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 14px 18px;
  border-radius: var(--radius-notch-lg);
  background: oklch(0.27 0.07 35);
  border: 1px solid oklch(0.5 0.15 35);
}

.alert__dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: oklch(0.7 0.16 35);
  flex: none;
  box-shadow: 0 0 0 4px oklch(0.7 0.16 35 / 0.25);
}

.alert__title {
  font: 700 13.5px system-ui;
  color: #ffe3c9;
}

.alert__subtitle {
  font: 400 12px system-ui;
  color: rgba(255, 217, 207, 0.75);
}

.card {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-notch-lg);
  padding: 20px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.card-title {
  font: 700 12px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: rgba(var(--fg-rgb), 0.65);
}

.card-action {
  font: 600 11.5px system-ui;
  color: var(--link);
  cursor: pointer;
}

.inherit-note {
  padding: 12px 16px;
  border-radius: 0 10px 0 10px;
  background: rgba(var(--accent-rgb), 0.1);
  border: 1px solid rgba(var(--accent-rgb), 0.25);
  font: 400 12.5px/1.5 system-ui;
  color: rgba(var(--fg-rgb), 0.7);
}

.phase-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.phase-form {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--border-card);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.phase-form__actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.row__remove {
  flex: none;
  padding: 2px 8px;
  color: rgba(var(--fg-rgb), 0.3);
  font: 600 13px system-ui;
  cursor: pointer;
}

.row__remove:hover {
  color: oklch(0.78 0.16 35);
}

.card-text {
  margin-top: 8px;
  font: 400 13px/1.6 system-ui;
  color: rgba(var(--fg-rgb), 0.7);
  white-space: pre-wrap;
}

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

.summary-value--accent {
  color: oklch(0.85 0.13 35);
}

/* Pleine largeur sous les quatre cellules : une ligne par bloc, alignées. */
.summary-phases {
  grid-column: 1 / -1;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-top: 14px;
  border-top: 1px solid rgba(var(--fg-rgb), 0.08);
}

.summary-phase {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

/* Ligne de l'événement lui-même (2026-07-31) — même accent que `.row--event`
   dans la liste plus bas, pour la distinguer des vrais blocs rattachés. */
.summary-phase--event .summary-phase__range,
.summary-phase--event .summary-phase__title {
  color: var(--accent);
}

.summary-phase {
  padding: 3px 6px;
  border-radius: 0 6px 0 6px;
}

.summary-phase--clickable {
  cursor: pointer;
}

.summary-phase--current {
  background: rgba(var(--accent-rgb), 0.16);
}

.summary-phase__tag {
  flex: none;
  min-width: 84px;
  text-align: center;
  padding: 2px 8px;
  border-radius: 0 6px 0 6px;
  font: 700 10px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.summary-phase__range {
  flex: none;
  font: 600 14px var(--font-mono);
  color: rgb(var(--fg-rgb));
}

.summary-phase__title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font: 400 13px system-ui;
  color: rgba(var(--fg-rgb), 0.5);
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

/* Ligne de l'événement lui-même dans la chronologie « Montage, répétition,
   démontage » (2026-07-31) : pas un bloc, juste un repère — léger accent
   plutôt qu'un fond identique aux blocs, pour la distinguer d'un coup d'œil. */
.row--event {
  background: rgba(var(--accent-rgb), 0.08);
  border: 1px solid rgba(var(--accent-rgb), 0.2);
}

/* Ligne cliquable de la chronologie (2026-07-31, demande de Samuel) — toutes
   sauf celle où on est déjà, `goToItem` l'ignore de toute façon mais le
   curseur ne doit pas laisser croire qu'un clic ferait quelque chose. */
.row--clickable {
  cursor: pointer;
}

/* Fiche actuellement affichée (2026-07-31) : surbrillance plus marquée que
   `.row--event` (bordure gauche en plus), les deux peuvent se cumuler quand
   on est sur la fiche de l'événement lui-même. */
.row--current {
  border-left: 3px solid var(--accent);
  background: rgba(var(--accent-rgb), 0.14);
}

/* Matériel assigné (2026-08-01, demande de Samuel) : catégorie remontée à la
   suite du titre plutôt qu'en sous-ligne (voir `.row__cat` ci-dessous), donc
   la ligne tient sur une seule ligne de texte — le padding vertical est
   réduit d'autant, sans toucher `.row` (partagé avec techniciens/blocs/
   transports, qui gardent leur hauteur habituelle). */
.row--compact {
  padding: 6px 12px;
}

/* Composant de kit en retrait dans « Matériel assigné » (2026-08-02, demande
   de Samuel) — même trait de raccordement que `.parcours-option--nested`
   (Parcours Matériel) et `.kit-child` (inventaire) : indentation + tick
   horizontal, sans toucher `.row`/`.row--compact` partagés avec les autres
   listes de la fiche. */
.row--nested {
  position: relative;
  margin-left: 18px;
  border-left: 2px solid rgba(var(--accent-rgb), 0.25);
}

.row--nested::before {
  content: '';
  position: absolute;
  left: -2px;
  top: 50%;
  width: 10px;
  height: 2px;
  background: rgba(var(--accent-rgb), 0.25);
}

.row__dot {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  flex: none;
}

.row__avatar {
  width: 26px;
  height: 26px;
  border-radius: var(--radius-notch-sm);
  background: oklch(0.65 0.15 290 / 0.3);
  color: var(--accent);
  display: flex;
  align-items: center;
  justify-content: center;
  font: 700 11px system-ui;
  flex: none;
}

.row__body {
  flex: 1;
}

.row__body--flex {
  font: 500 12.5px system-ui;
  color: rgba(var(--fg-rgb), 0.75);
}

.row__title {
  font: 600 13px system-ui;
  color: rgb(var(--fg-rgb));
}

.row__subtitle {
  font: 400 11.5px system-ui;
  color: rgba(var(--fg-rgb), 0.5);
}

/* Catégorie du matériel, à la suite du titre sur la même ligne (2026-08-01,
   remplace l'ancienne sous-ligne `.row__subtitle`) — poids et couleur plus
   discrets que le titre pour rester secondaire. */
.row__cat {
  font: 400 11.5px system-ui;
  color: rgba(var(--fg-rgb), 0.5);
}

/* Quantité entre parenthèses, à la suite (2026-08-01, remplace le `×N`
   accolé au titre). */
.row__qty {
  font: 600 12px system-ui;
  color: rgba(var(--fg-rgb), 0.6);
}

.row__conflict {
  font: 700 10px system-ui;
  color: oklch(0.85 0.13 35);
  background: oklch(0.7 0.16 35 / 0.18);
  padding: 2px 8px;
  border-radius: 0 10px 0 10px;
}

.row__remove {
  font: 700 12px system-ui;
  color: rgba(var(--fg-rgb), 0.35);
  cursor: pointer;
  padding: 2px 6px;
  flex: none;
}

.row__badge {
  font: 700 10px system-ui;
  text-transform: uppercase;
  color: rgba(var(--fg-rgb), 0.55);
  background: rgba(var(--fg-rgb), 0.08);
  padding: 2px 8px;
  border-radius: 0 6px 0 6px;
}

.row__time {
  font: 600 12px system-ui;
  color: rgba(var(--fg-rgb), 0.5);
}

.row-empty {
  font: 500 12.5px system-ui;
  color: rgba(var(--fg-rgb), 0.4);
  padding: 10px 12px;
}

.edit-conflict {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  padding: 10px;
  border-radius: var(--radius-notch-sm);
  background: oklch(0.27 0.07 35);
  border: 1px solid oklch(0.5 0.15 35);
  font: 400 12px system-ui;
  color: rgba(255, 217, 207, 0.9);
}
</style>

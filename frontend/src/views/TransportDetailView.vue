<script setup>
import { ref, computed, watch, defineAsyncComponent } from 'vue'
import { useRoute } from 'vue-router'
import AppShell from '../components/AppShell.vue'
import { api } from '../api/client'
import { useSuppressionFiche } from '../composables/useSuppressionFiche'
import { useEscapeKey } from '../composables/useEscapeKey'
import { useLeaveGuard } from '../composables/useLeaveGuard'
import LeaveEditPrompt from '../components/LeaveEditPrompt.vue'
// Chargé à la demande : TipTap pèse l'essentiel du paquet, et l'éditeur ne
// sert qu'en mode ÉDITION de cette fiche. En import statique, tout visiteur
// du Tableau de bord le téléchargerait sans jamais s'en servir.
const RichTextEditor = defineAsyncComponent(() => import('../components/RichTextEditor.vue'))
import { useChipFilter } from '../composables/useChipFilter'
import { normalizeText } from '../utils/text'

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
 *
 * Mode lecture/édition (2026-08-02, suite, demande de Samuel) : cette fiche
 * était volontairement EXCLUE du pattern « Modifier la fiche » des trois
 * autres (Lieu/Matériel/Technicien/Spectacle) depuis le 2026-07-30 — elle
 * était déjà un formulaire toujours ouvert (on y arrive typiquement pour
 * compléter une proposition auto-générée). Samuel a demandé le même
 * traitement que les autres : `editing` (local, PAS `useFicheEdition.js` —
 * `save()` a déjà sa propre logique métier, imbriquée technicians/materials
 * + statut à confirmer + conflit à forcer, qui ne correspond pas au simple
 * `toDraft`/`toPayload` générique du composable) bascule entre un affichage
 * statique (voir la note suivante pour son gabarit) et le formulaire
 * existant, inchangé, simplement déplacé sous `v-if="editing"` (le seul
 * endroit où `.field__static` reste utilisée, ex. le champ « Spectacle »).
 * `buildForm(t)` (extrait de `loadTransport`) est
 * réutilisé pour réinitialiser le brouillon à l'entrée ET à la sortie
 * (Annuler) du mode édition, pour ne jamais laisser une modification
 * abandonnée traîner. Bouton « Modifier la fiche » dans l'entête ; en
 * édition, le bouton principal reste « Confirmer le transport » ou
 * « Enregistrer » selon le statut — EXACTEMENT le choix qu'affichait déjà
 * l'ancien bas de page, juste relocalisé dans `.fiche-actions` — plus
 * « Annuler ». La suppression, elle, rejoint le bas du formulaire d'édition
 * (comme les trois autres fiches qui en ont un) : plus visible en lecture.
 *
 * Présentation du mode lecture alignée sur SpectacleDetailView.vue (2026-08-02,
 * suite, demande de Samuel : « mêmes règles visuelles », « retirer les
 * boîtes des champs ») — remplace les `.field__static` (fond + bordure,
 * gardés en mode ÉDITION uniquement, inchangé) par le gabarit sans boîte de
 * la fiche spectacle : `.summary-grid`/`.summary-label`/`.summary-value`
 * pour les champs à valeur unique (type, lieux, horaires), `.card`/
 * `.card-title`/`.card-text` pour les notes (carte absente s'il n'y en a
 * pas, comme sur la fiche spectacle), et `.row-list`/`.row` pour les listes
 * (techniciens avec avatar à initiales, matériel avec pastille de
 * catégorie) — même fond `var(--bg-row)` SANS bordure que les lignes de la fiche
 * spectacle, à ne pas confondre avec les `.field__static` boîtées : ce
 * n'est pas la même règle visuelle, les listes gardent un fond doux pour
 * rester lisibles en jeu de plusieurs lignes.
 *
 * Réorganisation des champs (2026-08-02, suite, demande de Samuel) :
 * `Heure prévue` (+ `Durée estimée`, restée groupée avec elle) passe en
 * première position — « l'élément le plus important » — devant Type/
 * Spectacle. Lieu de départ et lieu d'arrivée sont fusionnés sur une seule
 * ligne avec une flèche de direction (`.route-value` en lecture,
 * `.field-grid--route` en édition — un `<select>` de chaque côté, la flèche
 * au milieu). `Fin de l'événement au départ`/`Début de l'événement à
 * l'arrivée` déménagent dans leur propre carte séparée juste après le bloc
 * principal (lecture : second `.card.summary-grid` ; édition : `.reference-
 * times` repositionnée après le trajet plutôt qu'avant l'heure prévue).
 * Même ordre reproduit des deux côtés, comme demandé.
 *
 * Mise en page fine (2026-08-02, suite, demande de Samuel) : le titre du
 * spectacle de référence et sa date/heure passent sur 2 lignes distinctes
 * (`.summary-value--lines` en lecture, deux `.reference-times__value` en
 * édition — `.reference-times__item` est déjà en colonne, donc les empiler
 * suffit) plutôt qu'un seul texte "Titre · date". Le trajet (`.summary-
 * span-2`) prend maintenant 2 colonnes de la grille pour ne pas forcer de
 * retour de ligne — uniquement en lecture, l'édition avait déjà 2 `<select>`
 * explicites qui ne wrappent pas.
 *
 * Jour de la semaine (2026-08-02, suite, demande de Samuel) : `dateTimeFmt`
 * (donc `fmtReference`, donc le spectacle de référence en lecture ET en
 * édition) gagne `weekday: 'short'` — « ven. 31 juill., 20 h 00 ». « Heure
 * prévue » (lecture seulement, l'édition reste un `<input type="datetime-
 * local">` natif) est éclatée sur 2 lignes avec les nouveaux `fmtDate`/
 * `fmtTime` : jour+date d'abord, heure ensuite — la ligne secondaire n'est
 * donc pas toujours la même (`.summary-value__sub` posé explicitement sur
 * la bonne ligne selon le champ, plutôt qu'un `:last-child` positionnel qui
 * aurait dimé l'heure au lieu de la date).
 *
 * **Tournées multi-arrêts (2026-08-04, décision de Samuel — refonte)** : un
 * transport n'est plus un trajet A → B mais une SÉQUENCE ordonnée d'arrêts
 * (`stops`, voir TransportStop côté backend). Conséquences sur cette fiche :
 * - Le couple de `<select>` départ/arrivée et le toggle Livraison/Ramassage
 *   disparaissent (champ `transport_type` retiré du modèle) — remplacés par
 *   un éditeur de séquence : une ligne par arrêt (lieu, durée du segment
 *   depuis l'arrêt précédent, heure d'arrivée dérivée affichée en direct),
 *   réordonnable (↑/↓), avec ajout/retrait. Une durée laissée vide est
 *   estimée côté serveur (Google Routes, repli Settings) — le champ est donc
 *   envoyé seulement s'il est renseigné.
 * - « Durée estimée » devient la durée TOTALE (somme des segments), en
 *   lecture seule — elle s'édite segment par segment.
 * - Chaque ligne de matériel porte sa PORTION de la tournée : deux `<select>`
 *   (chargement/déchargement, positions dans la séquence) en édition, un
 *   libellé « Lieu X → Lieu Y » en lecture. Défaut : tournée entière.
 *   Retirer/réordonner un arrêt remappe les indexes des lignes (elles
 *   suivent leur arrêt) puis `fixupLines()` répare les cas devenus invalides
 *   (chargement ≥ déchargement → retour au défaut tournée entière).
 * - La modale « Ajouter du matériel » se fait PAR ARRÊT de chargement :
 *   un `<select>` en tête recharge `material-availability?stop=<n>` — on ne
 *   propose que ce qui sera sur place à l'arrivée du camion à CET arrêt. La
 *   modale ne pilote que les lignes chargées à cet arrêt ; les autres sont
 *   préservées telles quelles (même règle que le matériel hors catalogue).
 */

const route = useRoute()

const transport = ref(null)
const venues = ref([])
const technicians = ref([])
const materialsCatalog = ref([])
const loading = ref(false)
const loadError = ref(null)

const timeFmt = new Intl.DateTimeFormat('fr-CA', { hour: '2-digit', minute: '2-digit', hour12: false })
// Jour de la semaine ajouté aux deux (2026-08-02, demande de Samuel) —
// « ven. 31 juill., 20 h 00 ».
const dateFmt = new Intl.DateTimeFormat('fr-CA', { weekday: 'short', day: 'numeric', month: 'short' })
const dateTimeFmt = new Intl.DateTimeFormat('fr-CA', {
  weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
})

function fmtReference(iso) {
  return dateTimeFmt.format(new Date(iso))
}

// Date seule (avec jour de la semaine) / heure seule — utilisées pour
// éclater « Heure prévue » sur 2 lignes en mode lecture.
function fmtDate(iso) {
  return dateFmt.format(new Date(iso))
}

function fmtTime(iso) {
  return timeFmt.format(new Date(iso))
}

// Jour court pour la liste des spectacles aux lieux desservis — l'heure
// exacte n'y apporte rien, on cherche « lesquels et quand, en gros ».
function fmtShortDay(iso) {
  return dateFmt.format(new Date(iso))
}

// Spectacles des lieux de la tournée (2026-08-05, `touched_shows` côté API) :
// tous ceux qui se tiennent dans les lieux visités, sur la fenêtre du projet.
// Liste de CONTEXTE, volontairement large — à ne pas confondre avec les
// spectacles de référence (départ/arrivée) affichés plus bas, qui bornent
// l'horaire du déplacement.
const touchedShows = computed(() => transport.value?.touched_shows ?? [])

// Chaque arrêt reçoit les spectacles de SON lieu (2026-08-05) : `touched_shows`
// est groupé par lieu, la séquence par arrêt — un lieu visité deux fois dans
// une tournée aller-retour affiche donc la même liste aux deux passages, ce
// qui est correct (ce sont bien les mêmes spectacles).
const decoratedStops = computed(() => {
  const parLieu = new Map(touchedShows.value.map((g) => [g.venue_id, g.shows]))
  return (transport.value?.stops ?? []).map((s) => ({
    ...s,
    shows: parLieu.get(s.venue) ?? [],
  }))
})

// Initiales pour l'avatar d'un technicien en mode lecture (2026-08-02,
// suite) — même helper que SpectacleDetailView.vue, dupliqué ici faute de
// composant partagé.
function initials(name) {
  return name
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join('')
}

const form = ref(null)
const saving = ref(false)
const saveError = ref(null)
const conflictDetail = ref(null)

// --- Mode lecture/édition (2026-08-02, suite, demande de Samuel) ---
// Même bouton « Modifier la fiche » que les autres fiches (Lieu/Matériel/
// Technicien/Spectacle) — jusqu'ici volontairement exclue de ce pattern
// (voir la note de tête du module, 2026-07-30 : « déjà un formulaire
// toujours ouvert »). Contrairement à `useFicheEdition.js`, ce champ reste
// local plutôt que d'y passer : `save()` a déjà sa propre gestion (payload
// imbriqué technicians/materials, statut à confirmer, conflit à forcer) qui
// ne correspond pas au simple `toDraft`/`toPayload` du composable partagé —
// pas de raison de le forcer dans ce moule pour un seul écran.
const editing = ref(false)

// Brouillon tel qu'il était à l'entrée en édition — sert à savoir si quelque
// chose a vraiment changé avant d'interrompre une navigation (2026-08-05).
const formInitial = ref(null)

function startEdit() {
  form.value = buildForm(transport.value)
  formInitial.value = JSON.stringify(form.value)
  saveError.value = null
  conflictDetail.value = null
  editing.value = true
}

function cancelEdit() {
  form.value = buildForm(transport.value)
  formInitial.value = null
  saveError.value = null
  conflictDetail.value = null
  editing.value = false
}

function isDirty() {
  if (!editing.value || !form.value) return false
  return JSON.stringify(form.value) !== formInitial.value
}

// Quitter la fiche en cours d'édition demande d'abord quoi faire — même
// garde-fou que les quatre autres fiches, branché à la main ici puisque cet
// écran n'utilise pas `useFicheEdition` (voir la note de tête).
const { leavePrompt, leaveSaving, leaveError, stayOnPage, saveAndLeave } = useLeaveGuard({
  isDirty,
  save: () => save(),
})

const showAddModal = ref(false)
const catalogQty = ref({})

// Catégorie du matériel (voir MaterialCategory, models.py) — même helper que
// AssignerMaterielModal.vue / MaterielView.vue, dupliqué ici faute de composant
// partagé. Sert au filtre par puces dans la modale d'ajout (2026-07-30, suite).
const NO_CATEGORY = { label: 'Sans catégorie', color: 'rgba(var(--fg-rgb),.3)' }

function categoryOf(material) {
  return material?.category
    ? { label: material.category_name, color: material.category_color }
    : NO_CATEGORY
}

// Catégorie par id de matériel (2026-08-02, suite) — pour la pastille de
// couleur des lignes de matériel en mode lecture, même lecture visuelle que
// `decoratedMaterials` sur SpectacleDetailView.vue.
const materialCategoryById = computed(() => new Map(materialsCatalog.value.map((m) => [m.id, categoryOf(m)])))

// ⌘+clic pour combiner plusieurs catégories (2026-08-01, à la demande de
// Samuel — même comportement que toutes les puces de filtre de l'app, voir
// useChipFilter.js).
const categoryFilter = useChipFilter()

const categoryChips = computed(() => {
  const seen = new Map()
  materialsCatalog.value.forEach((m) => {
    const key = m.category ?? 'none'
    if (!seen.has(key)) seen.set(key, categoryOf(m))
  })
  const sorted = [...seen.entries()].sort((a, b) => a[1].label.localeCompare(b[1].label, 'fr'))
  return [
    { key: 'all', label: 'Tous', active: categoryFilter.selected.value.size === 0, select: () => categoryFilter.selectAll() },
    ...sorted.map(([key, meta]) => ({
      key,
      label: meta.label,
      active: categoryFilter.isSelected(key),
      select: (event) => categoryFilter.toggle(key, event),
    })),
  ]
})

// Recherche texte (2026-07-31, à la demande de Samuel — même comportement
// que MaterielView.vue et AssignerMaterielModal.vue) : se combine avec le
// filtre de catégorie. Un kit reste visible si son propre nom correspond
// (avec tous ses composants, comme d'habitude ici — jamais repliés) ou si
// un seul composant correspond (le kit reste visible pour le contexte).
const search = ref('')
const searchNormalized = computed(() => normalizeText(search.value.trim()))
function matchesSearch(name) {
  return !searchNormalized.value || normalizeText(name).includes(searchNormalized.value)
}

const searchFilteredIds = computed(() => {
  if (!searchNormalized.value) return null
  const ids = new Set()
  materialsCatalog.value.forEach((m) => {
    if (!matchesSearch(m.name)) return
    ids.add(m.id)
    if (m.parent_material != null) ids.add(m.parent_material)
    ;(childrenByParent.value.get(m.id) ?? []).forEach((c) => ids.add(c.id))
  })
  return ids
})

// Construit le brouillon à partir du transport enregistré — utilisé au
// chargement ET à chaque entrée/sortie du mode édition (2026-08-02, suite),
// pour repartir toujours des dernières valeurs serveur plutôt que de
// laisser traîner une modification abandonnée après un « Annuler ».
function buildForm(t) {
  // Propose l'heure de départ effective (avec buffer) comme valeur par
  // défaut si aucune heure n'est encore saisie — seulement pour un
  // transport jamais encore horodaté (voir note du module en tête de
  // fichier) : un `scheduled_datetime` déjà enregistré n'est jamais
  // remplacé par cette proposition.
  let scheduledDefault = t.scheduled_datetime ? t.scheduled_datetime.slice(0, 16) : ''
  if (!scheduledDefault && t.departure_show) {
    scheduledDefault = t.departure_show.effective_end.slice(0, 16)
  }
  return {
    scheduled_datetime: scheduledDefault,
    // Séquence d'arrêts (tournées 2026-08-04) : `travel` est la durée du
    // segment depuis l'arrêt précédent. `''` (champ vidé) = « à estimer par
    // le serveur » — on n'envoie alors pas la clé (voir save()).
    stops: (t.stops ?? []).map((s) => ({
      venue: s.venue,
      travel: s.travel_minutes_from_previous,
    })),
    technicians: (t.technicians ?? []).map((tt) => tt.technician),
    notes: t.notes ?? '',
    materials: (t.materials ?? []).map((m) => ({
      material: m.material,
      material_name: m.material_name,
      quantity: m.quantity,
      load: m.load_stop_order,
      unload: m.unload_stop_order,
    })),
  }
}

async function loadTransport() {
  const id = route.params.id
  loading.value = true
  loadError.value = null
  editing.value = false
  try {
    transport.value = await api.get(`/transports/${id}/`)
    // `project` est porté par la tournée elle-même depuis la migration 0028
    // (`show` est devenu optionnel — plus de détour par la fiche spectacle,
    // qui plantait sur une tournée « sans spectacle »).
    const projectId = transport.value.project
    const [venuesData, techniciansData, materialsData] = await Promise.all([
      api.get('/venues/', { project: projectId }),
      api.get('/technicians/', { project: projectId }),
      api.get('/materials/', { project: projectId }),
    ])
    venues.value = Array.isArray(venuesData) ? venuesData : (venuesData.results ?? [])
    technicians.value = Array.isArray(techniciansData) ? techniciansData : (techniciansData.results ?? [])
    materialsCatalog.value = Array.isArray(materialsData) ? materialsData : (materialsData.results ?? [])

    form.value = buildForm(transport.value)
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

// --- Manifeste par arrêt (2026-08-04, demande de Samuel) ---
// La vue chauffeur : à chaque arrêt, ce qu'on DÉPOSE (↓) puis ce qu'on PREND
// (↑) — décharger avant de charger, l'ordre physique des opérations. Dérivé
// des portions des lignes de matériel (load/unload_stop_order), rien de
// stocké en plus.
const stopManifest = computed(() => {
  const t = transport.value
  if (!t) return []
  const materials = t.materials ?? []
  return (t.stops ?? []).map((s, i) => ({
    stop: s,
    index: i,
    drop: materials.filter((m) => m.unload_stop_order === i),
    pick: materials.filter((m) => m.load_stop_order === i),
  }))
})

// --- Séquence d'arrêts (tournées multi-arrêts, 2026-08-04) ---

const venueNameById = computed(() => new Map(venues.value.map((v) => [v.id, v.name])))

function stopVenueName(venueId) {
  return venueNameById.value.get(venueId) ?? '?'
}

// Libellé du trajet complet (entête + lecture) : codes courts si disponibles,
// noms sinon — enchaîne TOUS les arrêts, pas seulement départ/arrivée.
const routeLabel = computed(() =>
  (transport.value?.stops ?? [])
    .map((s) => s.venue_code || s.venue_name)
    .join(' → '),
)

// Durée totale du brouillon = somme des segments renseignés. `null` si au
// moins un segment est laissé « à estimer » (on ne peut pas la calculer
// avant la réponse du serveur).
const draftTotalMinutes = computed(() => {
  if (!form.value) return null
  let total = 0
  for (let i = 1; i < form.value.stops.length; i += 1) {
    const t = form.value.stops[i].travel
    if (t === '' || t === null || t === undefined) return null
    total += Number(t) || 0
  }
  return total
})

// Heures d'arrivée dérivées en direct pendant l'édition : départ + cumul des
// segments. `null` dès qu'un segment amont est « à estimer » ou que l'heure
// de départ manque — l'affichage retombe sur « auto ».
const draftArrivals = computed(() => {
  if (!form.value?.scheduled_datetime) return form.value?.stops.map(() => null) ?? []
  let current = new Date(form.value.scheduled_datetime)
  let broken = false
  return form.value.stops.map((s, i) => {
    if (broken) return null
    if (i > 0) {
      const t = s.travel
      if (t === '' || t === null || t === undefined) {
        broken = true
        return null
      }
      current = new Date(current.getTime() + (Number(t) || 0) * 60000)
    }
    return new Date(current)
  })
})

// Après un retrait/réordonnancement d'arrêt, les indexes des lignes de
// matériel peuvent devenir invalides (hors bornes, chargement ≥
// déchargement) : on répare au défaut « tournée entière » plutôt que de
// bloquer — l'utilisateur voit les sélecteurs changer et peut ajuster.
function fixupLines() {
  const last = form.value.stops.length - 1
  form.value.materials.forEach((m) => {
    if (m.load == null || m.load < 0 || m.load > last) m.load = 0
    if (m.unload == null || m.unload < 0 || m.unload > last) m.unload = last
    if (m.load >= m.unload) {
      m.load = 0
      m.unload = last
    }
  })
}

function addStop() {
  // Nouveau segment sans durée : `''` = à estimer par le serveur (Routes ou
  // défaut des réglages) — cohérent avec la règle du backend.
  form.value.stops.push({ venue: '', travel: '' })
  fixupLines()
}

function removeStop(index) {
  if (form.value.stops.length <= 2) return
  form.value.stops.splice(index, 1)
  // Le segment qui suivait l'arrêt retiré relie maintenant deux lieux
  // différents : sa durée n'a plus de sens, on la remet « à estimer ».
  if (index < form.value.stops.length && index > 0) {
    form.value.stops[index].travel = ''
  }
  if (form.value.stops.length > 0) form.value.stops[0].travel = 0
  // Les lignes suivent leurs arrêts : tout index après l'arrêt retiré recule
  // d'une position ; une ligne qui pointait l'arrêt retiré lui-même sera
  // réparée par fixupLines().
  form.value.materials.forEach((m) => {
    if (m.load === index) m.load = -1
    else if (m.load > index) m.load -= 1
    if (m.unload === index) m.unload = -1
    else if (m.unload > index) m.unload -= 1
  })
  fixupLines()
}

function moveStop(index, delta) {
  const target = index + delta
  if (target < 0 || target >= form.value.stops.length) return
  const stops = form.value.stops
  ;[stops[index], stops[target]] = [stops[target], stops[index]]
  // Les durées de segment décrivent des COUPLES de lieux : après un échange,
  // les segments touchés (celui qui arrive à chacune des deux positions, et
  // celui qui suit) ne relient plus les mêmes lieux — remis « à estimer ».
  const touched = new Set([index, target, Math.max(index, target) + 1])
  touched.forEach((i) => {
    if (i > 0 && i < stops.length) stops[i].travel = ''
  })
  stops[0].travel = 0
  // Les lignes de matériel suivent leur arrêt déplacé.
  form.value.materials.forEach((m) => {
    if (m.load === index) m.load = target
    else if (m.load === target) m.load = index
    if (m.unload === index) m.unload = target
    else if (m.unload === target) m.unload = index
  })
  fixupLines()
}

// Options des sélecteurs de portion d'une ligne de matériel : chaque arrêt,
// numéroté dans l'ordre de la séquence.
const stopOptions = computed(() =>
  (form.value?.stops ?? []).map((s, i) => ({
    value: i,
    label: `${i + 1}. ${s.venue ? stopVenueName(s.venue) : '—'}`,
  })),
)

// Validation côté client avant l'envoi — les mêmes règles que le serveur,
// pour un message immédiat plutôt qu'un 400.
function validateStops() {
  if (form.value.stops.length < 2) {
    return 'Une tournée doit avoir au moins 2 arrêts.'
  }
  if (form.value.stops.some((s) => !s.venue)) {
    return 'Chaque arrêt doit avoir un lieu.'
  }
  for (let i = 1; i < form.value.stops.length; i += 1) {
    if (form.value.stops[i].venue === form.value.stops[i - 1].venue) {
      return `Deux arrêts consécutifs au même lieu (« ${stopVenueName(form.value.stops[i].venue)} ») — retire l'un des deux.`
    }
  }
  return null
}

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

// Objets complets (nom + spécialité) des techniciens assignés — pour
// l'affichage statique en mode lecture (2026-08-02, suite), qui montre la
// spécialité comme les puces interactives du mode édition.
const assignedTechnicianRows = computed(() => technicianRows.value.filter((t) => t.selected))

const materialStockById = computed(() => new Map(materialsCatalog.value.map((m) => [m.id, m.quantity])))

function updateMaterialQty(index, value) {
  const stock = materialStockById.value.get(form.value.materials[index].material) ?? 999
  const qty = Math.max(0, Math.min(Number(value) || 0, stock))
  form.value.materials[index].quantity = qty
}

function removeMaterialLine(index) {
  form.value.materials.splice(index, 1)
}

// --- Disponibilité par arrêt (2026-07-30 ; par arrêt depuis le 2026-08-04) ---
// On ne charge dans un camion que ce qui se trouve réellement au point de
// chargement à l'arrivée du camion. La position vient du backend
// (GET /transports/{id}/material-availability/?stop=<n>, qui réutilise le
// grand livre de transport_coherence.py) : `Material.venue` seul serait faux
// dès qu'un transport antérieur a déjà déplacé le matériel.

const availability = ref(null)
const availabilityLoading = ref(false)
// Arrêt de chargement piloté par la modale — les lignes chargées à un AUTRE
// arrêt ne sont pas touchées par elle (voir confirmAddMaterial).
const loadStopIndex = ref(0)

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

async function refreshAvailability() {
  availabilityLoading.value = true
  try {
    // La disponibilité se calcule sur l'état ENREGISTRÉ de la tournée (arrêts
    // en base) : si l'utilisateur vient d'ajouter un arrêt non enregistré, le
    // paramètre est borné à ce que le serveur connaît — le bandeau
    // `availabilityStale` explique déjà ce décalage pour l'heure.
    const savedStopCount = (transport.value.stops ?? []).length
    const stopParam = Math.min(loadStopIndex.value, Math.max(0, savedStopCount - 1))
    availability.value = await api.get(
      `/transports/${transport.value.id}/material-availability/`,
      { stop: stopParam },
    )
  } catch {
    // En cas d'échec on ne bloque rien : mieux vaut une modale sans grisé
    // qu'une modale inutilisable.
    availability.value = null
  } finally {
    availabilityLoading.value = false
  }
}

function seedCatalogQty() {
  // La modale ne pilote que les lignes chargées à l'arrêt sélectionné — le
  // matériel qui monte à un autre arrêt de la même tournée n'y apparaît pas
  // pré-coché et n'est pas modifié par elle.
  const seed = {}
  materialsCatalog.value.forEach((m) => {
    const existing = form.value.materials.find(
      (line) => line.material === m.id && line.load === loadStopIndex.value,
    )
    seed[m.id] = existing ? existing.quantity : 0
  })
  catalogQty.value = seed
}

async function openAddModal(stopIndex = 0) {
  showAddModal.value = true
  categoryFilter.selectAll()
  search.value = ''
  loadStopIndex.value = stopIndex
  await refreshAvailability()
  seedCatalogQty()
}

// Changer l'arrêt de chargement depuis la modale recharge la disponibilité
// ET la sélection (les quantités saisies pour l'arrêt quitté sont appliquées
// aux lignes ? Non — elles seraient perdues : on applique d'abord, même
// comportement qu'un « Appliquer » implicite, puis on repart sur le nouvel
// arrêt).
async function changeLoadStop(stopIndex) {
  applyCatalogToLines()
  loadStopIndex.value = Number(stopIndex)
  await refreshAvailability()
  seedCatalogQty()
}

function closeAddModal() {
  showAddModal.value = false
}

// Échap ferme la modale « Ajouter du matériel », même geste que le clic sur
// le fond ou le « × ». La confirmation de suppression a la sienne, portée
// par useSuppressionFiche.
useEscapeKey(() => {
  if (showAddModal.value) closeAddModal()
})

// Même arborescence que l'inventaire général et que la modale d'assignation
// du spectacle : chaque composant suit son kit, en retrait.
const visibleCatalog = computed(() =>
  materialsCatalog.value
    .filter((m) => categoryFilter.passes(m.category ?? 'none'))
    .filter((m) => !searchFilteredIds.value || searchFilteredIds.value.has(m.id)),
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

function applyCatalogToLines() {
  // La modale reflète l'état complet du chargement À CET ARRÊT : une ligne à
  // 0 (décochée) doit donc être RETIRÉE du camion, pas seulement ignorée —
  // sinon décocher n'aurait aucun effet (demande de Samuel, 2026-07-30).
  // Tournées (2026-08-04) : seules les lignes chargées à l'arrêt sélectionné
  // sont pilotées — celles des autres arrêts, et le matériel absent du
  // catalogue affiché (inactif, filtré hors projet), sont préservés tels
  // quels plutôt que perdus silencieusement. Tout reste local ici : c'est le
  // PATCH du transport qui applique la liste (`TransportSerializer.materials`).
  const lastIndex = form.value.stops.length - 1
  const catalogIds = new Set(materialsCatalog.value.map((m) => m.id))
  const merged = []
  materialsCatalog.value.forEach((m) => {
    const qty = catalogQty.value[m.id] || 0
    if (qty <= 0) return
    const existing = form.value.materials.find(
      (line) => line.material === m.id && line.load === loadStopIndex.value,
    )
    merged.push({
      material: m.id,
      material_name: existing?.material_name ?? m.name,
      quantity: qty,
      load: loadStopIndex.value,
      // Une ligne existante garde son arrêt de déchargement ; une nouvelle
      // descend au dernier arrêt (défaut « tournée entière » depuis ce
      // point), ajustable ensuite sur la ligne elle-même.
      unload: existing ? existing.unload : lastIndex,
    })
  })
  form.value.materials.forEach((line) => {
    if (!catalogIds.has(line.material) || line.load !== loadStopIndex.value) merged.push(line)
  })
  form.value.materials = merged
  fixupLines()
}

function confirmAddMaterial() {
  applyCatalogToLines()
  showAddModal.value = false
}

async function save({ confirm = false, force = false } = {}) {
  saveError.value = null
  conflictDetail.value = null
  const stopsError = validateStops()
  if (stopsError) {
    saveError.value = stopsError
    return
  }
  saving.value = true
  try {
    const payload = {
      scheduled_datetime: form.value.scheduled_datetime ? new Date(form.value.scheduled_datetime).toISOString() : null,
      // Séquence d'arrêts : l'ordre est la position dans la liste. Une durée
      // laissée vide n'envoie pas la clé — le serveur estime (Routes, repli
      // Settings) ; le premier arrêt n'a jamais de durée (segment inexistant).
      stops: form.value.stops.map((s, i) => {
        const stop = { venue: s.venue }
        if (i > 0 && s.travel !== '' && s.travel !== null && s.travel !== undefined) {
          stop.travel_minutes_from_previous = Math.max(0, Number(s.travel) || 0)
        }
        return stop
      }),
      technicians: form.value.technicians.map((id) => ({ technician: id })),
      notes: form.value.notes,
      materials: form.value.materials.map((m) => ({
        material: m.material,
        quantity: m.quantity,
        load_stop_order: m.load,
        unload_stop_order: m.unload,
      })),
      force,
    }
    if (confirm) payload.status = 'confirmed'
    transport.value = await api.patch(`/transports/${transport.value.id}/`, payload)
    form.value = buildForm(transport.value)
    // Succès : referme le mode édition, comme les autres fiches. En cas
    // d'erreur (catch ci-dessous), on reste en édition pour laisser voir le
    // message ou le bandeau « Forcer ».
    editing.value = false
    // Renvoyé pour le garde-fou de navigation (2026-08-05) : il n'enchaîne
    // vers la page demandée que si l'enregistrement a vraiment abouti.
    return true
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
        e.data?.stops?.[0] ??
        e.data?.materials?.[0] ??
        "Impossible d'enregistrer les changements."
    }
    return false
  } finally {
    saving.value = false
  }
}

const canConfirm = computed(() => isToApprove.value && !!form.value?.scheduled_datetime)

// --- Suppression (2026-07-30 ; déplacée dans le bloc édition le 2026-08-02,
// suite, en même temps que le passage au mode lecture/édition) ---
// Même emplacement que les trois autres fiches qui ont un bouton Supprimer
// (Lieu/Spectacle/Transport) : en bas du formulaire d'ÉDITION, pas visible
// en lecture. Supprimer un déplacement emporte ses lignes de matériel et de
// techniciens (tables de liaison en CASCADE) ; rien d'autre n'en dépend.
const {
  confirming, deleting, deleteError, askDelete, cancelDelete, confirmDelete,
} = useSuppressionFiche({ endpoint: '/transports', redirectTo: '/transports',
  beforeRedirect: () => cancelEdit(),
})
</script>

<template>
  <AppShell>
    <div v-if="loading" class="hint">Chargement…</div>
    <div v-else-if="loadError" class="hint hint--error">
      Impossible de charger ce transport. Es-tu connecté (session Django) ?
    </div>

    <div v-else-if="transport && form" class="page">
      <div class="breadcrumb"><RouterLink to="/transports">Transports</RouterLink> / {{ transport.show_title ?? 'Tournée sans spectacle' }}</div>

      <div class="header">
        <div class="header__title-row">
          <h1 class="header__title">Tournée — {{ routeLabel }}</h1>
          <div
            class="header__status"
            :style="isConfirmed
              ? { color: 'oklch(0.72 0.13 165)', background: 'oklch(0.72 0.13 165 / .16)' }
              : { color: 'oklch(0.78 0.13 85)', background: 'oklch(0.78 0.13 85 / .16)' }"
          >
            {{ isConfirmed ? 'Confirmé' : 'À approuver' }}
          </div>
        </div>
        <div class="fiche-actions">
          <button v-if="!editing" type="button" class="fiche-btn" @click="startEdit">
            Modifier la fiche
          </button>
          <template v-else>
            <button
              v-if="isToApprove"
              type="button"
              class="fiche-btn fiche-btn--primary"
              :disabled="saving || !canConfirm"
              @click="save({ confirm: true })"
            >
              {{ saving ? 'Enregistrement…' : 'Confirmer le transport' }}
            </button>
            <button
              v-else
              type="button"
              class="fiche-btn fiche-btn--primary"
              :disabled="saving"
              @click="save()"
            >
              {{ saving ? 'Enregistrement…' : 'Enregistrer' }}
            </button>
            <button type="button" class="fiche-btn" :disabled="saving" @click="cancelEdit">
              Annuler
            </button>
          </template>
        </div>
      </div>

      <!-- Mode lecture (2026-08-02, suite, demande de Samuel : mêmes règles
           visuelles que la fiche spectacle, sans boîte de champ) — voir la
           note de tête du module. -->
      <template v-if="!editing">
        <div class="card summary-grid">
          <div>
            <div class="summary-label">Heure de départ</div>
            <div class="summary-value summary-value--lines" :class="{ 'summary-value--accent': !transport.scheduled_datetime }">
              <template v-if="transport.scheduled_datetime">
                <div class="summary-value__sub">{{ fmtDate(transport.scheduled_datetime) }},</div>
                <div>{{ fmtTime(transport.scheduled_datetime) }}</div>
              </template>
              <template v-else>Non planifié</template>
            </div>
          </div>
          <div>
            <div class="summary-label">Durée totale</div>
            <div class="summary-value">{{ transport.estimated_duration_minutes }} min</div>
          </div>
        </div>

        <!-- Séquence d'arrêts (tournées 2026-08-04) : une ligne par arrêt,
             avec l'heure d'arrivée dérivée (fournie par l'API,
             `stops[].arrival_datetime`) et la durée du segment qui y mène.
             Depuis le 2026-08-05, chaque arrêt porte aussi les spectacles de
             son lieu (`touched_shows`) — Samuel les voulait ici plutôt que
             dans une carte séparée : c'est la même information, mais rattachée
             à l'arrêt qui la concerne. -->
        <div class="card">
          <div class="card-title" style="margin-bottom: 14px">Séquence du transport</div>
          <div class="stop-list">
            <div v-for="(s, i) in decoratedStops" :key="s.id" class="stop-row">
              <div class="stop-row__num">{{ i + 1 }}</div>
              <div class="stop-row__body">
                <div class="stop-row__name">{{ s.venue_name }}</div>
                <div class="stop-row__meta">
                  <template v-if="i === 0">Départ<template v-if="s.arrival_datetime"> · {{ fmtTime(s.arrival_datetime) }}</template></template>
                  <template v-else>
                    + {{ s.travel_minutes_from_previous }} min
                    <template v-if="s.arrival_datetime"> · arrivée {{ fmtTime(s.arrival_datetime) }}</template>
                  </template>
                </div>
                <div v-if="s.shows.length" class="touched-venue__shows">
                  <RouterLink
                    v-for="sh in s.shows"
                    :key="sh.id"
                    :to="`/spectacles/${sh.id}`"
                    class="touched-show"
                    :class="{ 'touched-show--linked': sh.id === transport.show }"
                  >{{ sh.title }} · {{ fmtShortDay(sh.start) }}</RouterLink>
                </div>
                <div v-else class="touched-venue__empty">Aucun spectacle à ce lieu</div>
              </div>
            </div>
          </div>
        </div>

        <div v-if="transport.departure_show || transport.arrival_show" class="card summary-grid">
          <div v-if="transport.departure_show">
            <div class="summary-label">Fin de l'événement au départ</div>
            <RouterLink
              :to="`/spectacles/${transport.departure_show.id}`"
              class="summary-value summary-value--lines summary-value--link"
            >
              <div>{{ transport.departure_show.title }} ·</div>
              <div class="summary-value__sub">{{ fmtReference(transport.departure_show.effective_end) }}</div>
            </RouterLink>
          </div>
          <div v-if="transport.arrival_show">
            <div class="summary-label">Début de l'événement à l'arrivée</div>
            <RouterLink
              :to="`/spectacles/${transport.arrival_show.id}`"
              class="summary-value summary-value--lines summary-value--link"
            >
              <div>{{ transport.arrival_show.title }} ·</div>
              <div class="summary-value__sub">{{ fmtReference(transport.arrival_show.engagement_start) }}</div>
            </RouterLink>
          </div>
        </div>

        <div v-if="transport.notes" class="card">
          <div class="card-title">Notes</div>
          <!-- eslint-disable-next-line vue/no-v-html -- assaini à l'écriture
               par `inventory/rich_text.py` (liste blanche de balises). -->
          <div class="rich-text" v-html="transport.notes" />
        </div>

        <div class="card">
          <div class="card-title" style="margin-bottom: 14px">Techniciens affectés</div>
          <div class="row-list">
            <div v-for="t in assignedTechnicianRows" :key="t.id" class="row">
              <div class="row__avatar">{{ initials(t.name) }}</div>
              <div class="row__body">
                <div class="row__title">{{ t.name }}</div>
                <div class="row__subtitle">{{ t.specialty || '—' }}</div>
              </div>
            </div>
            <div v-if="assignedTechnicianRows.length === 0" class="row-empty">Aucun technicien affecté.</div>
          </div>
          <div v-if="transport.has_technician_conflict" class="conflict-note">
            Au moins un des techniciens affectés est peut-être déjà engagé sur un autre
            spectacle ou déplacement durant cette fenêtre.
          </div>
        </div>

        <!-- Manifeste par arrêt (2026-08-04, demande de Samuel) : la liste de
             matériel est sectionnée par arrêt — le chauffeur voit d'un coup
             d'œil ce qu'il dépose (↓) puis ce qu'il prend (↑) à chaque
             arrêt, flèche à gauche de chaque ligne. -->
        <div class="card">
          <div class="card-title" style="margin-bottom: 14px">Matériel par arrêt</div>
          <div v-if="(transport.materials ?? []).length === 0" class="row-empty">
            Aucun matériel — camion vide.
          </div>
          <div v-else class="manifest">
            <div v-for="entry in stopManifest" :key="entry.stop.id" class="manifest__stop">
              <div class="manifest__header">
                <div class="stop-row__num">{{ entry.index + 1 }}</div>
                <div class="manifest__venue">{{ entry.stop.venue_name }}</div>
                <div v-if="entry.stop.arrival_datetime" class="manifest__time">
                  {{ fmtTime(entry.stop.arrival_datetime) }}
                </div>
              </div>
              <div class="row-list manifest__rows">
                <!-- Déposer d'abord, prendre ensuite : l'ordre physique des
                     opérations à un arrêt. -->
                <div v-for="m in entry.drop" :key="`d-${m.id}`" class="row">
                  <span class="manifest__arrow manifest__arrow--drop" title="Déposer">↓</span>
                  <span
                    class="row__dot"
                    :style="{ background: (materialCategoryById.get(m.material) ?? {}).color ?? 'rgba(var(--fg-rgb),.3)' }"
                  />
                  <div class="row__body">
                    <div class="row__title">
                      {{ m.material_name }}
                      <span class="row__cat">· {{ (materialCategoryById.get(m.material) ?? {}).label ?? 'Sans catégorie' }}</span>
                    </div>
                    <div class="row__subtitle">Déposer — pris à {{ m.load_stop_order + 1 }}. {{ m.load_venue_name }}</div>
                  </div>
                  <div class="row__qty">× {{ m.quantity }}</div>
                </div>
                <div v-for="m in entry.pick" :key="`p-${m.id}`" class="row">
                  <span class="manifest__arrow manifest__arrow--pick" title="Prendre">↑</span>
                  <span
                    class="row__dot"
                    :style="{ background: (materialCategoryById.get(m.material) ?? {}).color ?? 'rgba(var(--fg-rgb),.3)' }"
                  />
                  <div class="row__body">
                    <div class="row__title">
                      {{ m.material_name }}
                      <span class="row__cat">· {{ (materialCategoryById.get(m.material) ?? {}).label ?? 'Sans catégorie' }}</span>
                    </div>
                    <div class="row__subtitle">Prendre — à déposer à {{ m.unload_stop_order + 1 }}. {{ m.unload_venue_name }}</div>
                  </div>
                  <div class="row__qty">× {{ m.quantity }}</div>
                </div>
                <div v-if="entry.drop.length === 0 && entry.pick.length === 0" class="manifest__none">
                  Aucune manutention à cet arrêt.
                </div>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- Mode édition : formulaire inchangé, simplement déplacé sous
           `v-if="editing"` — voir la note de tête du module. -->
      <div v-else class="card">
        <div class="field-grid">
          <div class="field">
            <div class="field__label">Heure de départ</div>
            <!-- step en secondes : 300 = minutes par pas de 5 -->
            <input
              v-model="form.scheduled_datetime"
              type="datetime-local"
              step="300"
              class="field__input"
            />
          </div>
          <div class="field">
            <div class="field__label">Durée totale</div>
            <!-- Dérivée (somme des segments) : s'édite segment par segment
                 dans la séquence ci-dessous. « À estimer » dès qu'un segment
                 est laissé vide (le serveur le calculera). -->
            <div class="field__static">
              {{ draftTotalMinutes !== null ? `${draftTotalMinutes} min` : 'À estimer à l\'enregistrement' }}
            </div>
          </div>
        </div>
        <div v-if="isToApprove && !form.scheduled_datetime" class="fiche-hint">
          Ajoute une heure de départ pour pouvoir confirmer ce transport.
        </div>

        <div class="field">
          <div class="field__label">Spectacle desservi (arrivée)</div>
          <div class="field__static">{{ transport.show_title ?? 'Aucun spectacle' }}</div>
        </div>

        <!-- Séquence d'arrêts (tournées 2026-08-04) : l'ordre est la position
             dans la liste. La durée d'un segment laissée vide est estimée par
             le serveur (Google Routes, repli réglages). -->
        <div class="field">
          <div class="field__label">Séquence de la tournée</div>
          <div class="stop-editor">
            <div v-for="(s, i) in form.stops" :key="i" class="stop-editor__row">
              <div class="stop-row__num">{{ i + 1 }}</div>
              <select v-model="s.venue" class="field__input stop-editor__venue">
                <option value="" disabled>Lieu…</option>
                <option v-for="v in venues" :key="v.id" :value="v.id">{{ v.name }}</option>
              </select>
              <div v-if="i > 0" class="stop-editor__travel">
                <span class="stop-editor__travel-label">+</span>
                <input
                  v-model="s.travel"
                  type="number"
                  min="0"
                  step="5"
                  class="field__input stop-editor__travel-input"
                  placeholder="auto"
                />
                <span class="stop-editor__travel-label">min</span>
              </div>
              <div v-else class="stop-editor__travel stop-editor__travel--start">Départ</div>
              <div class="stop-editor__arrival">
                {{ draftArrivals[i] ? fmtTime(draftArrivals[i].toISOString()) : (i === 0 ? '' : 'auto') }}
              </div>
              <div class="stop-editor__actions">
                <button type="button" class="stop-editor__btn" :disabled="i === 0" title="Monter" @click="moveStop(i, -1)">↑</button>
                <button type="button" class="stop-editor__btn" :disabled="i === form.stops.length - 1" title="Descendre" @click="moveStop(i, 1)">↓</button>
                <button
                  type="button"
                  class="stop-editor__btn stop-editor__btn--danger"
                  :disabled="form.stops.length <= 2"
                  title="Retirer cet arrêt"
                  @click="removeStop(i)"
                >✕</button>
              </div>
            </div>
          </div>
          <div class="material-add" @click="addStop">+ Ajouter un arrêt</div>
        </div>

        <div v-if="transport.departure_show || transport.arrival_show" class="reference-times">
          <div v-if="transport.departure_show" class="reference-times__item">
            <span class="reference-times__label">Fin de l'événement au départ</span>
            <span class="reference-times__value">{{ transport.departure_show.title }} ·</span>
            <span class="reference-times__value">{{ fmtReference(transport.departure_show.effective_end) }}</span>
          </div>
          <div v-if="transport.arrival_show" class="reference-times__item">
            <span class="reference-times__label">Début de l'événement à l'arrivée</span>
            <span class="reference-times__value">{{ transport.arrival_show.title }} ·</span>
            <span class="reference-times__value">{{ fmtReference(transport.arrival_show.engagement_start) }}</span>
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
            <div v-for="(m, i) in form.materials" :key="`${m.material}-${m.load}-${m.unload}`" class="material-row material-row--stops">
              <div class="material-row__name">{{ m.material_name }}</div>
              <input
                type="number"
                min="0"
                class="material-row__qty"
                :value="m.quantity"
                @input="updateMaterialQty(i, $event.target.value)"
              />
              <div class="material-row__stock">/ {{ materialStockById.get(m.material) ?? '?' }} dispo.</div>
              <!-- Portion de la tournée (2026-08-04) : où cette ligne monte et
                   descend. Les options sont les arrêts de la séquence
                   ci-dessus, numérotés par position. -->
              <div class="material-row__portion">
                <select
                  class="field__input material-row__stop-select"
                  :value="m.load"
                  title="Arrêt de chargement"
                  @change="m.load = Number($event.target.value); fixupLines()"
                >
                  <option v-for="o in stopOptions" :key="o.value" :value="o.value" :disabled="o.value >= m.unload && o.value !== m.load">
                    {{ o.label }}
                  </option>
                </select>
                <span class="route-arrow" aria-hidden="true">→</span>
                <select
                  class="field__input material-row__stop-select"
                  :value="m.unload"
                  title="Arrêt de déchargement"
                  @change="m.unload = Number($event.target.value); fixupLines()"
                >
                  <option v-for="o in stopOptions" :key="o.value" :value="o.value" :disabled="o.value <= m.load && o.value !== m.unload">
                    {{ o.label }}
                  </option>
                </select>
              </div>
              <div class="material-row__remove" @click="removeMaterialLine(i)">✕</div>
            </div>
            <div v-if="form.materials.length === 0" class="row-empty">Aucun matériel — camion vide.</div>
          </div>
          <div class="material-add" @click="openAddModal(0)">+ Ajouter du matériel</div>
        </div>

        <div class="field">
          <div class="field__label">Notes</div>
          <RichTextEditor
            v-model="form.notes"
            placeholder="Consignes particulières, accès, code de porte — gras, listes et liens acceptés."
          />
        </div>

        <div v-if="saveError" class="fiche-error">{{ saveError }}</div>

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
        <!-- Arrêt de chargement (tournées 2026-08-04) : la disponibilité est
             recalculée pour l'arrêt choisi — on ne charge à un arrêt que ce
             qui s'y trouvera à l'arrivée du camion. -->
        <div class="modal__stop-picker">
          <span class="modal__stop-label">Chargement à l'arrêt</span>
          <select
            class="field__input modal__stop-select"
            :value="loadStopIndex"
            @change="changeLoadStop($event.target.value)"
          >
            <option v-for="o in stopOptions" :key="o.value" :value="o.value" :disabled="o.value === form.stops.length - 1">
              {{ o.label }}
            </option>
          </select>
        </div>
        <div v-if="availabilityLoading" class="modal__note">Vérification des emplacements…</div>
        <div v-else-if="availability && availability.at === null" class="modal__note">
          Ce déplacement n'a pas encore d'heure de départ : impossible de savoir ce
          qui se trouvera à {{ availability.origin_venue_name }}. Tout l'inventaire
          est proposé — saisis l'heure et enregistre pour filtrer sur le réel.
        </div>
        <div v-else-if="availability" class="modal__note">
          Seul le matériel présent à <strong>{{ availability.origin_venue_name }}</strong>
          à l'arrivée du camion est sélectionnable.
          <template v-if="unavailableCount > 0">
            {{ unavailableCount }} item(s) grisé(s) sont ailleurs.
          </template>
          <template v-if="availabilityStale">
            <br />L'heure saisie n'est pas encore enregistrée — la liste reflète
            l'heure actuellement en base.
          </template>
        </div>

        <input
          v-model="search"
          type="search"
          class="fiche-input"
          placeholder="Rechercher du matériel…"
        />

        <div class="filters">
          <div
            v-for="f in categoryChips"
            :key="f.key"
            class="chip"
            :class="{ 'chip--active': f.active }"
            @click="f.select($event)"
          >
            {{ f.label }}
          </div>
        </div>

        <div v-if="catalogRows.length === 0" class="hint">
          Aucun matériel ne correspond à ces filtres.
        </div>
        <div v-else class="modal__body">
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

    <LeaveEditPrompt
      :visible="leavePrompt"
      :saving="leaveSaving"
      :error="leaveError"
      @stay="stayOnPage"
      @save="saveAndLeave"
    />
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

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

/* Titre + pastille de statut sur une même ligne (2026-08-02, suite) — les
   deux étaient des enfants directs de `.header` (déjà flex) avant l'ajout
   du bouton « Modifier la fiche » ; regroupés dans un `<div>` pour laisser
   `.fiche-actions` prendre l'autre bord, ce `<div>` doit donc porter
   lui-même le flex qui alignait titre et statut. */
.header__title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
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

/* Mode lecture (2026-08-02, suite) : gabarit repris tel quel de
   SpectacleDetailView.vue — champs sans boîte (`.summary-*`), notes en
   texte simple (`.card-title`/`.card-text`), listes en lignes à fond doux
   sans bordure (`.row-list`/`.row__*`), à ne pas confondre avec les
   `.field__static` boîtées ci-dessous (mode ÉDITION uniquement). */
.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 18px;
}

/* Le trajet (lieu de départ → lieu d'arrivée) prend 2 colonnes de la grille
   plutôt qu'une seule, pour ne pas forcer de retour de ligne (2026-08-02,
   demande de Samuel). */
.summary-span-2 {
  grid-column: span 2;
}

.summary-label {
  font: 700 11px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: rgba(var(--fg-rgb), 0.53);
}

.summary-value {
  font: 600 14px system-ui;
  color: rgb(var(--fg-rgb));
  margin-top: 4px;
}

/* Valeur éclatée sur 2 lignes (2026-08-02, demande de Samuel) — conteneur
   générique, réutilisé pour le spectacle de référence (titre puis date/
   heure) ET pour « Heure prévue » (jour+date puis heure). `.summary-
   value__sub` marque explicitement la ligne secondaire — PAS `:last-child`,
   car cette ligne n'est pas toujours la même selon le champ (la date pour
   le spectacle de référence, mais le jour+date pour l'heure prévue, où
   l'heure elle-même reste la ligne principale). Même hiérarchie que
   `.row__title`/`.row__subtitle`. */
.summary-value--lines {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.summary-value__sub {
  font: 400 12.5px system-ui;
  color: rgba(var(--fg-rgb), 0.63);
}

.summary-value--accent {
  color: oklch(0.85 0.13 35);
}

/* Lieu de départ/arrivée fusionnés sur une seule ligne avec flèche de
   direction (2026-08-02, demande de Samuel) — `.route-arrow` est repris tel
   quel en mode édition (`.field-grid--route`), avec juste un padding-bottom
   pour retomber au niveau des `<select>` plutôt que des libellés. */
.route-value {
  display: flex;
  align-items: center;
  gap: 8px;
}

.route-arrow {
  color: rgba(var(--fg-rgb), 0.43);
  font-size: 15px;
}




/* Spectacle de référence cliquable (2026-08-05) — mode lecture seulement :
   en édition, le même bloc (`.reference-times`) reste du texte, un lien y
   ferait quitter un formulaire en cours. */
.summary-value--link {
  display: block;
  text-decoration: none;
  color: inherit;
}

.summary-value--link:hover {
  color: var(--link);
}

.touched-venue__shows {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
}

.touched-show {
  font: 500 12px system-ui;
  color: rgba(var(--fg-rgb), 0.78);
  background: var(--bg-row);
  padding: 3px 9px;
  border-radius: 0 6px 0 6px;
  text-decoration: none;
}

/* Le spectacle explicitement rattaché au déplacement (`Transport.show`) reste
   distingué des autres : c'est lui qui sert d'ancrage aux règles d'horaire. */
.touched-show--linked {
  background: rgba(var(--accent-rgb), 0.18);
  color: var(--accent);
}

.touched-venue__empty {
  font: 400 12px system-ui;
  color: rgba(var(--fg-rgb), 0.43);
  margin-top: 4px;
}

.card-text {
  margin-top: 8px;
  font: 400 13px/1.6 system-ui;
  color: rgba(var(--fg-rgb), 0.7);
  white-space: pre-wrap;
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

.row__dot {
  width: 8px;
  height: 8px;
  border-radius: 2px;
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
  color: rgba(var(--fg-rgb), 0.58);
}

.row__cat {
  font: 400 11.5px system-ui;
  color: rgba(var(--fg-rgb), 0.58);
}

.row__qty {
  flex: none;
  font: 600 12px system-ui;
  color: rgba(var(--fg-rgb), 0.68);
}

.field__label {
  font: 700 11px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: rgba(var(--fg-rgb), 0.53);
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
  background: var(--bg-row);
  border: 1px solid rgba(var(--fg-rgb), 0.1);
  font: 500 13.5px system-ui;
  color: rgb(var(--fg-rgb));
}

.field__input {
  width: 100%;
  box-sizing: border-box;
  padding: 11px 12px;
  border-radius: var(--radius-notch-sm);
  background: var(--bg-row);
  border: 1px solid rgba(var(--fg-rgb), 0.1);
  font: 500 13.5px system-ui;
  color: rgb(var(--fg-rgb));
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
  background: var(--bg-row);
  border: 1px solid rgba(var(--fg-rgb), 0.1);
  color: rgba(var(--fg-rgb), 0.68);
  font: 500 12.5px system-ui;
  cursor: pointer;
}

.tech-chip--on {
  border-color: rgba(var(--accent-rgb), 0.45);
  background: rgba(var(--accent-rgb), 0.14);
  color: rgb(var(--fg-rgb));
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
  color: rgba(var(--fg-rgb), 0.43);
}

.tech-empty,
.tech-hint {
  font: 400 11.5px system-ui;
  color: rgba(var(--fg-rgb), 0.43);
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

/* --- Séquence d'arrêts (tournées 2026-08-04) --- */

.stop-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.stop-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: var(--radius-notch-sm);
  background: var(--bg-row);
}

.stop-row__num {
  width: 24px;
  height: 24px;
  border-radius: 0 7px 0 7px;
  background: rgba(var(--accent-rgb), 0.16);
  color: var(--accent);
  display: flex;
  align-items: center;
  justify-content: center;
  font: 700 11.5px var(--font-mono);
  flex: none;
}

.stop-row__body {
  flex: 1;
  min-width: 0;
}

.stop-row__name {
  font: 600 13px system-ui;
  color: rgb(var(--fg-rgb));
}

.stop-row__meta {
  font: 400 11.5px system-ui;
  color: rgba(var(--fg-rgb), 0.58);
}

/* Manifeste par arrêt (2026-08-04) — la vue chauffeur du mode lecture. */
.manifest {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.manifest__header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.manifest__venue {
  font: 700 13px system-ui;
  color: rgb(var(--fg-rgb));
}

.manifest__time {
  font: 600 11.5px var(--font-mono);
  color: rgba(var(--fg-rgb), 0.58);
  margin-left: auto;
  white-space: nowrap;
}

/* Lignes en léger retrait sous l'entête d'arrêt, avec un trait de
   raccordement — même lecture visuelle que les composants d'un kit. */
.manifest__rows {
  margin-left: 11px;
  padding-left: 13px;
  border-left: 2px solid rgba(var(--fg-rgb), 0.1);
}

.manifest__arrow {
  width: 20px;
  height: 20px;
  border-radius: 0 6px 0 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  font: 700 12px system-ui;
  flex: none;
}

.manifest__arrow--pick {
  color: oklch(0.72 0.13 165);
  background: oklch(0.72 0.13 165 / 0.16);
}

.manifest__arrow--drop {
  color: oklch(0.7 0.11 255);
  background: oklch(0.7 0.11 255 / 0.16);
}

.manifest__none {
  font: 400 11.5px system-ui;
  color: rgba(var(--fg-rgb), 0.43);
  padding: 4px 2px;
}

.stop-editor {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.stop-editor__row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: var(--radius-notch-sm);
  background: var(--bg-row);
}

.stop-editor__venue {
  flex: 1;
  min-width: 0;
}

.stop-editor__travel {
  display: flex;
  align-items: center;
  gap: 5px;
  flex: none;
}

.stop-editor__travel--start {
  font: 700 10px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: rgba(var(--fg-rgb), 0.48);
  /* Même encombrement que « + [input] min » pour garder les colonnes
     alignées entre la ligne de départ et les segments. */
  width: 96px;
  justify-content: center;
}

.stop-editor__travel-label {
  font: 500 11.5px system-ui;
  color: rgba(var(--fg-rgb), 0.48);
}

.stop-editor__travel-input {
  width: 58px;
  padding: 7px 8px;
  text-align: center;
}

.stop-editor__arrival {
  font: 600 11.5px var(--font-mono);
  color: rgba(var(--fg-rgb), 0.63);
  width: 62px;
  text-align: right;
  flex: none;
  white-space: nowrap;
}

.stop-editor__actions {
  display: flex;
  gap: 4px;
  flex: none;
}

.stop-editor__btn {
  width: 24px;
  height: 24px;
  border-radius: 0 6px 0 6px;
  background: var(--bg-deep);
  border: 1px solid rgba(var(--fg-rgb), 0.12);
  color: rgba(var(--fg-rgb), 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font: 700 12px system-ui;
  padding: 0;
}

.stop-editor__btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.stop-editor__btn--danger {
  color: oklch(0.78 0.16 35);
}

.reference-times {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 24px;
  padding: 10px 12px;
  border-radius: var(--radius-notch-sm);
  background: var(--bg-row);
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
  color: rgba(var(--fg-rgb), 0.48);
}

.reference-times__value {
  font: 500 12.5px system-ui;
  color: rgba(var(--fg-rgb), 0.8);
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
  background: var(--bg-row);
}

.material-row__name {
  flex: 1 1 110px;
  min-width: 0;
  font: 500 12.5px system-ui;
  color: rgb(var(--fg-rgb));
}

.material-row__qty {
  width: 56px;
  box-sizing: border-box;
  padding: 6px 8px;
  border-radius: 0 6px 0 6px;
  background: var(--bg-deep);
  border: 1px solid rgba(var(--fg-rgb), 0.12);
  font: 600 12px system-ui;
  color: rgb(var(--fg-rgb));
  text-align: center;
}

.material-row__stock {
  font: 400 11px system-ui;
  color: rgba(var(--fg-rgb), 0.43);
  white-space: nowrap;
}

.material-row__remove {
  font: 700 12px system-ui;
  color: rgba(var(--fg-rgb), 0.43);
  cursor: pointer;
  padding: 2px 6px;
}

/* Ligne de matériel avec sa portion de tournée (2026-08-04) : les deux
   sélecteurs d'arrêts passent sous le nom sur les écrans étroits. */
.material-row--stops {
  flex-wrap: wrap;
}

.material-row__portion {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: none;
}

.material-row__stop-select {
  width: auto;
  padding: 6px 8px;
  font: 500 12px system-ui;
}

.modal__stop-picker {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 20px 0;
}

.modal__stop-label {
  font: 700 10.5px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: rgba(var(--fg-rgb), 0.53);
  flex: none;
}

.modal__stop-select {
  width: auto;
  min-width: 200px;
  padding: 8px 10px;
}

.material-add {
  margin-top: 8px;
  padding: 9px 12px;
  border-radius: var(--radius-notch-sm);
  border: 1px dashed rgba(var(--fg-rgb), 0.18);
  font: 600 12px system-ui;
  color: rgba(var(--fg-rgb), 0.58);
  cursor: pointer;
  text-align: center;
}

.row-empty {
  font: 500 12.5px system-ui;
  color: rgba(var(--fg-rgb), 0.48);
  padding: 10px 12px;
}

/* `.save-btn`/`--force` : seul le bouton « Forcer malgré le conflit » les
   utilise encore (2026-08-02, suite — le bouton d'enregistrement principal
   est passé dans l'entête avec `.fiche-btn`, voir `.fiche-actions`). */
.save-btn {
  padding: 10px 20px;
  border-radius: var(--radius-notch-sm);
  font: 600 13px system-ui;
  color: #0b0d10;
  background: var(--accent);
  cursor: pointer;
  white-space: nowrap;
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
  border: 1px solid rgba(var(--fg-rgb), 0.1);
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
  color: rgb(var(--fg-rgb));
}

.modal__close {
  font: 400 18px system-ui;
  color: rgba(var(--fg-rgb), 0.48);
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
  background: var(--bg-row);
  border: 1px solid rgba(var(--fg-rgb), 0.08);
}

.catalog-row--selected {
  border-color: rgba(var(--accent-rgb), 0.35);
}

/* Composant affiché en retrait sous son kit, avec le trait de raccordement —
   même lecture que l'arborescence de l'inventaire général (MaterielView). */
.catalog-row--nested {
  position: relative;
  margin-left: 26px;
  border-left: 2px solid rgba(var(--accent-rgb), 0.25);
}

.catalog-row--nested::before {
  content: '';
  position: absolute;
  left: -14px;
  top: 50%;
  width: 14px;
  height: 2px;
  background: rgba(var(--accent-rgb), 0.25);
}

/* Matériel absent du lieu de départ : gris moyen (contre le blanc du
   disponible) et non sélectionnable — voir la note de la modale. */
.catalog-row--disabled {
  opacity: 0.55;
}

.catalog-row--disabled .catalog-row__name {
  color: rgba(var(--fg-rgb), 0.53);
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
  color: rgba(var(--fg-rgb), 0.58);
}

.modal__note strong {
  color: rgba(var(--fg-rgb), 0.8);
}

.catalog-row__check {
  width: 18px;
  height: 18px;
  border-radius: 0 4px 0 4px;
  border: 1.5px solid rgba(var(--fg-rgb), 0.3);
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
  color: rgb(var(--fg-rgb));
}

.catalog-row__stock {
  font: 400 11px system-ui;
  color: rgba(var(--fg-rgb), 0.48);
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
  background: var(--bg-deep);
  border: 1px solid rgba(var(--fg-rgb), 0.12);
  color: rgb(var(--fg-rgb));
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
  background: var(--bg-deep);
  border: 1px solid rgba(var(--fg-rgb), 0.12);
  font: 600 12px system-ui;
  color: rgb(var(--fg-rgb));
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
  color: rgba(var(--fg-rgb), 0.48);
  margin-right: auto;
}

.modal__cancel {
  padding: 9px 16px;
  border-radius: var(--radius-notch-sm);
  font: 600 13px system-ui;
  color: rgba(var(--fg-rgb), 0.68);
  border: 1px solid rgba(var(--fg-rgb), 0.15);
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

<script setup>
import { ref, computed, onMounted } from 'vue'
import AppShell from '../components/AppShell.vue'
import ColorField from '../components/ColorField.vue'
import { EVENT_TYPE_ORDER } from '../constants/eventTypeMeta'
import { api } from '../api/client'
import { useActiveProject } from '../composables/useActiveProject'
import { useEventDisplay } from '../composables/useEventDisplay'

/**
 * Écran « Réglages » — port de Reglages.dc.html.
 *
 * Branché sur le singleton GET/PATCH /api/settings/ (voir Settings,
 * models.py — une seule ligne, pk=1). La section « Projets » du mockup
 * (liste + création) réutilise `useActiveProject` plutôt que de refaire un
 * fetch séparé, et appelle `refreshProjects()` après création pour que le
 * sélecteur de projet dans AppShell voie la nouvelle entrée sans refresh.
 *
 * Contrairement au mockup (état local, jamais persisté), ici « Enregistrer »
 * fait un vrai PATCH — les erreurs de validation viennent du backend
 * (PositiveIntegerField) plutôt que d'une validation dupliquée côté Vue.
 *
 * Chaque ligne de la liste renvoie vers `ProjetDetailView.vue` (2026-08-02,
 * gestion des accès par projet) — c'est là que vivent maintenant le
 * renommage, les dates de projet (retiré d'ici, voir `git log` pour
 * l'ancienne édition en ligne `draftDates`/`saveProjectDates`) et la gestion
 * des membres. Cette vue ne garde que la création de projet et les réglages
 * globaux (buffers, format).
 *
 * Section « Couleurs » (2026-08-02, demande de Samuel : « les couleurs des
 * bandes qui ne sont pas gérées dans une fiche [matériel, lieux]. Je pense
 * surtout aux transports », étendu aux types de spectacle après confirmation)
 * — transport + les 5 types de `Show.EVENT_TYPE_CHOICES`, seules couleurs de
 * l'app qui n'ont pas déjà une fiche éditable dédiée (`Venue.color`,
 * `MaterialCategory.color`). Volontairement absentes : les couleurs
 * sémantiques (conflit rouge, à-approuver orange, statut OK vert) — les
 * rendre personnalisables risquerait de casser la lisibilité plutôt que
 * d'aider (décision actée avec Samuel avant implémentation). `ColorField`
 * (nouveau composant partagé) évite une 3e copie du sélecteur déjà dupliqué
 * sur `LieuDetailView.vue`/`CategoriesMaterielView.vue`. `refreshEventDisplay()`
 * (`useEventDisplay.js`) est appelée après le PATCH pour que les CSS vars
 * (`--transport`, `--event-*`) se mettent à jour partout dans l'app sans
 * recharger la page.
 */

const { projects, refreshProjects } = useActiveProject()
const { refreshEventDisplay } = useEventDisplay()

const COLOR_DEFAULTS = {
  transport_color: 'oklch(0.64 0.21 340)',
  event_color_rehearsal: 'oklch(0.8 0.13 85)',
  event_color_performance: 'oklch(0.75 0.13 320)',
  event_color_storage: 'rgba(var(--fg-rgb),.6)',
  event_color_setup: 'oklch(0.75 0.13 165)',
  event_color_teardown: 'oklch(0.7 0.11 255)',
}

// Ordre demandé par Samuel (2026-08-02, suite) : la séquence Montage →
// Répétition/Représentation → Démontage d'abord (les 4 types de spectacle,
// dans l'ordre où ils se succèdent le plus souvent sur une fiche), puis un
// séparateur, puis Transport/Entreposage (les deux qui n'ont pas de
// contrepartie « bloc »).
// Cette section est la référence VISUELLE de l'ordre des types dans l'app :
// les puces de filtre du Tableau de bord et de Spectacles suivent la même
// suite (2026-08-02, demande de Samuel). L'ordre lui-même vit dans
// `EVENT_TYPE_ORDER` pour que les trois écrans ne puissent pas diverger — ne
// pas le réécrire à la main ici.
const COLOR_KEYS = {
  rehearsal: { type: 'rehearsal', key: 'event_color_rehearsal', label: 'Répétition' },
  setup: { type: 'setup', key: 'event_color_setup', label: 'Montage' },
  performance: { type: 'performance', key: 'event_color_performance', label: 'Représentation' },
  teardown: { type: 'teardown', key: 'event_color_teardown', label: 'Démontage' },
  transport: { type: 'transport', key: 'transport_color', label: 'Transport (déplacements confirmés)' },
  storage: { type: 'storage', key: 'event_color_storage', label: 'Entreposage' },
}

// L'ordre affiché est celui enregistré dans Settings (`event_type_order`),
// réordonnable par glisser-déposer ci-dessous — plus la constante figée. Tant
// que Settings n'a pas répondu, `useEventDisplay` retombe sur
// `EVENT_TYPE_ORDER`, donc la liste n'est jamais vide.
//
// Le séparateur « moments de plateau / le reste » qui existait ici a été
// retiré avec ce changement : il annonçait un regroupement que Samuel peut
// maintenant défaire d'un glisser, il aurait donc menti dès le premier
// réordonnancement.
const colorFields = computed(() => typeOrder.value.map((type) => COLOR_KEYS[type]))

const loading = ref(false)
const loadError = ref(null)
const form = ref(null)

// --- Ordre des types (2026-08-02, demande de Samuel) ---
//
// Brouillon local : réordonner ne part en base qu'au clic sur Enregistrer,
// comme les couleurs juste à côté. Seedé au chargement, puis piloté par le
// glisser-déposer.
const typeOrder = ref([...EVENT_TYPE_ORDER])
const draggedType = ref(null)
const dropTargetType = ref(null)

function onTypeDragStart(type, event) {
  draggedType.value = type
  // `effectAllowed`/`setData` : sans eux, Firefox refuse de démarrer le
  // glisser. La donnée elle-même ne sert pas (on garde l'état dans `ref`),
  // mais il faut en poser une.
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('text/plain', type)
}

function onTypeDragOver(type) {
  if (draggedType.value && draggedType.value !== type) dropTargetType.value = type
}

function onTypeDrop(type) {
  const source = draggedType.value
  dropTargetType.value = null
  draggedType.value = null
  if (!source || source === type) return
  const liste = [...typeOrder.value]
  const depuis = liste.indexOf(source)
  const vers = liste.indexOf(type)
  if (depuis === -1 || vers === -1) return
  liste.splice(depuis, 1)
  liste.splice(vers, 0, source)
  typeOrder.value = liste
}

function onTypeDragEnd() {
  draggedType.value = null
  dropTargetType.value = null
}

const saving = ref(false)
const saveError = ref(null)
const showSaved = ref(false)

const dateFormats = [
  { value: 'DMY', label: 'JJ/MM/AAAA' },
  { value: 'MDY', label: 'MM/DD/YYYY' },
]
const timeFormats = [
  { value: '24h', label: '24h' },
  { value: '12h', label: '12h' },
]

async function loadSettings() {
  loading.value = true
  loadError.value = null
  try {
    form.value = await api.get('/settings/')
    // Le backend garantit une liste complète et sans doublon — voir
    // `Settings.event_type_order_list`.
    typeOrder.value = [...form.value.event_type_order]
  } catch (e) {
    loadError.value = e
  } finally {
    loading.value = false
  }
}

onMounted(loadSettings)

async function save() {
  saveError.value = null
  showSaved.value = false
  saving.value = true
  try {
    form.value = await api.patch('/settings/', {
      default_buffer_before_minutes: Number(form.value.default_buffer_before_minutes),
      default_buffer_after_minutes: Number(form.value.default_buffer_after_minutes),
      default_transport_duration_minutes: Number(form.value.default_transport_duration_minutes),
      date_format: form.value.date_format,
      time_format: form.value.time_format,
      transport_color: form.value.transport_color,
      event_color_rehearsal: form.value.event_color_rehearsal,
      event_color_performance: form.value.event_color_performance,
      event_color_storage: form.value.event_color_storage,
      event_color_setup: form.value.event_color_setup,
      event_color_teardown: form.value.event_color_teardown,
      event_type_order: typeOrder.value,
    })
    // Re-seed depuis la réponse plutôt que de garder le brouillon : c'est
    // l'ordre assaini par le backend qui fait foi.
    typeOrder.value = [...form.value.event_type_order]
    showSaved.value = true
    // Reflète les nouvelles couleurs immédiatement partout dans l'app (CSS
    // vars sur <html>) sans attendre un rechargement de page.
    await refreshEventDisplay()
  } catch (e) {
    saveError.value =
      e.data?.default_buffer_before_minutes?.[0] ??
      e.data?.default_buffer_after_minutes?.[0] ??
      e.data?.default_transport_duration_minutes?.[0] ??
      e.data?.detail ??
      "Impossible d'enregistrer les réglages."
  } finally {
    saving.value = false
  }
}

// --- Projets ---

const newProjectName = ref('')
const newProjectError = ref(null)
const creatingProject = ref(false)

const dateFmt = new Intl.DateTimeFormat('fr-CA', { day: 'numeric', month: 'short', year: 'numeric' })
const projectColors = ['oklch(0.65 0.15 290)', 'oklch(0.7 0.15 165)', 'oklch(0.75 0.15 60)', 'oklch(0.7 0.16 35)']

const decoratedProjects = computed(() =>
  projects.value.map((p, i) => ({
    ...p,
    color: projectColors[i % projectColors.length],
    createdAtLabel: p.created_at ? dateFmt.format(new Date(p.created_at)) : '—',
  })),
)

const canAddProject = computed(() => newProjectName.value.trim().length > 0)

async function addProject() {
  const name = newProjectName.value.trim()
  if (!name) {
    newProjectError.value = 'Nom requis.'
    return
  }
  newProjectError.value = null
  creatingProject.value = true
  try {
    await api.post('/projects/', { name })
    newProjectName.value = ''
    await refreshProjects()
  } catch (e) {
    newProjectError.value = e.data?.name?.[0] ?? e.data?.detail ?? 'Impossible de créer le projet.'
  } finally {
    creatingProject.value = false
  }
}
</script>

<template>
  <AppShell>
    <div class="page">
      <h1 class="page-title">Réglages</h1>

      <div v-if="loading" class="hint">Chargement…</div>
      <div v-else-if="loadError" class="hint hint--error">
        Impossible de charger les réglages. Es-tu connecté (session Django) ?
      </div>

      <template v-else-if="form">
        <section class="section">
          <div class="section-title">Projets</div>
          <div class="project-list">
            <RouterLink v-for="p in decoratedProjects" :key="p.id" :to="`/projets/${p.id}`" class="project-row">
              <span class="project-dot" :style="{ background: p.color }" />
              <div class="project-body">
                <div class="project-top">
                  <div class="project-name">{{ p.name }}</div>
                  <div class="project-date">Créé le {{ p.createdAtLabel }}</div>
                </div>
              </div>
            </RouterLink>
            <div v-if="decoratedProjects.length === 0" class="row-empty">Aucun projet actif.</div>
          </div>
          <div class="create-card">
            <div class="create-title">Créer un projet</div>
            <div class="create-row">
              <input v-model="newProjectName" placeholder="Nom du projet" class="input input--wide" @keyup.enter="addProject" />
              <div
                class="btn"
                :class="canAddProject && !creatingProject ? 'btn--enabled' : 'btn--disabled'"
                @click="canAddProject && !creatingProject && addProject()"
              >
                + Créer
              </div>
            </div>
            <div v-if="newProjectError" class="error">{{ newProjectError }}</div>
            <div class="create-hint">
              Chaque projet a son propre matériel, spectacles, lieux et techniciens — les réglages ci-dessous s'appliquent globalement.
              La date de fin sert de repère pour vérifier que tout le matériel est
              revenu à son lieu d'origine (écran Cohérence) ; sans elle, l'app
              retient la fin du dernier événement.
            </div>
          </div>
        </section>

        <section class="section">
          <div class="section-title">Fenêtres effectives</div>
          <div class="card">
            <div class="field-row">
              <div class="field">
                <label class="label">Buffer avant (minutes)</label>
                <input v-model.number="form.default_buffer_before_minutes" type="number" min="0" class="input" />
              </div>
              <div class="field">
                <label class="label">Buffer après (minutes)</label>
                <input v-model.number="form.default_buffer_after_minutes" type="number" min="0" class="input" />
              </div>
            </div>
            <div class="hint-text">
              Marge appliquée automatiquement avant/après chaque spectacle pour couvrir transport et installation — s'applique aux nouvelles fiches seulement, pas rétroactif.
            </div>
          </div>
        </section>

        <section class="section">
          <div class="section-title">Transport</div>
          <div class="card">
            <div class="field field--narrow">
              <label class="label">Durée de transport par défaut (minutes)</label>
              <input v-model.number="form.default_transport_duration_minutes" type="number" min="0" class="input" />
            </div>
            <div class="hint-text">Utilisée si le calcul automatique du trajet échoue ou n'est pas configuré.</div>
          </div>
        </section>

        <section class="section">
          <div class="section-title">Affichage</div>
          <div class="card">
            <div class="field">
              <label class="label">Format de date</label>
              <div class="chips">
                <div
                  v-for="f in dateFormats"
                  :key="f.value"
                  class="chip"
                  :class="{ 'chip--active': form.date_format === f.value }"
                  @click="form.date_format = f.value"
                >
                  {{ f.label }}
                </div>
              </div>
            </div>
            <div class="field">
              <label class="label">Format d'heure</label>
              <div class="chips">
                <div
                  v-for="f in timeFormats"
                  :key="f.value"
                  class="chip"
                  :class="{ 'chip--active': form.time_format === f.value }"
                  @click="form.time_format = f.value"
                >
                  {{ f.label }}
                </div>
              </div>
            </div>
          </div>
        </section>

        <section class="section">
          <div class="section-title">Couleurs</div>
          <div class="card">
            <div class="hint-text">
              Couvre les bandes qui ne sont pas déjà réglables depuis une fiche
              (contrairement aux lieux et aux catégories de matériel) — les
              5 types de spectacle/bloc et les déplacements confirmés. Glisse
              une ligne pour changer l'ordre : les puces de filtre du Tableau
              de bord et de Spectacles suivront le même.
            </div>
            <div
              v-for="f in colorFields"
              :key="f.key"
              class="color-field"
              :class="{
                'color-field--dragging': draggedType === f.type,
                'color-field--drop': dropTargetType === f.type,
              }"
              draggable="true"
              @dragstart="onTypeDragStart(f.type, $event)"
              @dragover.prevent="onTypeDragOver(f.type)"
              @drop.prevent="onTypeDrop(f.type)"
              @dragend="onTypeDragEnd"
            >
              <label class="label">{{ f.label }}</label>
              <ColorField
                v-model="form[f.key]"
                :default-value="COLOR_DEFAULTS[f.key]"
              />
              <!-- Poignée à 4 points en carré (demande de Samuel) : c'est le
                   seul indice que la ligne se déplace. Toute la ligne est
                   `draggable`, la poignée ne fait que l'annoncer. -->
              <span class="drag-handle" title="Glisser pour changer l'ordre">
                <span v-for="n in 4" :key="n" class="drag-handle__dot" />
              </span>
            </div>
          </div>
        </section>

        <div class="save-row">
          <div class="btn btn--enabled" :class="{ 'btn--disabled': saving }" @click="!saving && save()">Enregistrer</div>
          <div v-if="showSaved" class="saved">
            <span class="saved__dot" />Réglages enregistrés
          </div>
          <div v-if="saveError" class="error">{{ saveError }}</div>
        </div>
      </template>
    </div>
  </AppShell>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 28px;
  max-width: 680px;
}

.hint {
  padding: 32px 40px;
  font: 500 13px system-ui;
  color: rgba(var(--fg-rgb), 0.5);
}

.hint--error {
  color: oklch(0.78 0.16 35);
}

.section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.section-title {
  font: 700 12px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: rgba(var(--fg-rgb), 0.45);
}

.card {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-notch-lg);
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.project-list {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-notch-lg);
  padding: 8px;
}

.project-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 10px;
  border-bottom: 1px solid rgba(var(--fg-rgb), 0.05);
  text-decoration: none;
  color: inherit;
  cursor: pointer;
}

.project-row:hover {
  background: rgba(var(--fg-rgb), 0.04);
  border-radius: var(--radius-notch-sm);
}

.project-row:last-child {
  border-bottom: none;
}

.project-dot {
  margin-top: 5px;
  width: 8px;
  height: 8px;
  border-radius: 2px;
  flex: none;
}

.project-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.project-top {
  display: flex;
  align-items: center;
  gap: 12px;
}

.project-name {
  flex: 1;
  font: 600 13px system-ui;
  color: rgb(var(--fg-rgb));
}

.project-date {
  font: 400 11.5px system-ui;
  color: rgba(var(--fg-rgb), 0.35);
}

.row-empty {
  font: 500 12.5px system-ui;
  color: rgba(var(--fg-rgb), 0.4);
  padding: 10px;
}

.create-card {
  background: var(--bg-card);
  border: 1px dashed rgba(var(--fg-rgb), 0.15);
  border-radius: var(--radius-notch-lg);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.create-title {
  font: 700 10.5px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: rgba(var(--fg-rgb), 0.4);
}

.create-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
}

.create-hint {
  font: 400 12px system-ui;
  color: rgba(var(--fg-rgb), 0.4);
  line-height: 1.5;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1;
  min-width: 200px;
}

.field--narrow {
  max-width: 260px;
}

.field-row {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
}

.label {
  font: 500 12px system-ui;
  color: rgba(var(--fg-rgb), 0.5);
}

.input {
  box-sizing: border-box;
  padding: 10px 12px;
  border-radius: var(--radius-notch-sm);
  background: var(--bg-row);
  border: 1px solid rgba(var(--fg-rgb), 0.1);
  font: 500 13px system-ui;
  color: rgb(var(--fg-rgb));
}

.input--wide {
  flex: 2;
  min-width: 200px;
}

.hint-text {
  font: 400 12px system-ui;
  color: rgba(var(--fg-rgb), 0.4);
  line-height: 1.5;
}

.chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

/* Ligne réordonnable (2026-08-02) : deux colonnes — le libellé et son
   sélecteur de couleur à gauche, la poignée à droite. */
.color-field {
  display: grid;
  grid-template-columns: 1fr auto;
  grid-template-areas:
    'label handle'
    'field handle';
  align-items: center;
  gap: 8px 12px;
  cursor: grab;
}

.color-field .label {
  grid-area: label;
}

.color-field > :not(.label):not(.drag-handle) {
  grid-area: field;
}

.color-field + .color-field {
  padding-top: 12px;
  border-top: 1px solid rgba(var(--fg-rgb), 0.05);
}

.color-field--dragging {
  opacity: 0.45;
  cursor: grabbing;
}

/* Trait d'insertion sur la ligne survolée pendant un glisser — plus lisible
   qu'un simple changement de fond, on voit OÙ la ligne va atterrir. */
.color-field--drop {
  box-shadow: inset 0 2px 0 0 var(--accent);
}

/* Poignée à 4 points en carré (demande de Samuel) : une grille 2×2, pas une
   image ni un caractère — ça suit la couleur du texte et reste net à
   n'importe quelle densité d'écran. */
.drag-handle {
  grid-area: handle;
  display: grid;
  grid-template-columns: repeat(2, 4px);
  gap: 3px;
  padding: 6px;
  border-radius: 4px;
  cursor: grab;
}

.drag-handle:hover {
  background: rgba(var(--fg-rgb), 0.06);
}

.drag-handle__dot {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: rgba(var(--fg-rgb), 0.35);
}

.color-field:hover .drag-handle__dot {
  background: rgba(var(--fg-rgb), 0.55);
}

.save-row {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.btn {
  font: 600 13px system-ui;
  color: #0b0d10;
  background: var(--accent);
  padding: 12px 22px;
  border-radius: var(--radius-notch-sm);
  cursor: pointer;
  white-space: nowrap;
}

.btn--enabled {
  color: rgb(var(--fg-rgb));
  background: oklch(0.65 0.15 290 / 0.3);
}

.btn--disabled {
  color: rgba(var(--fg-rgb), 0.3);
  background: rgba(var(--fg-rgb), 0.06);
  cursor: default;
}

.saved {
  display: flex;
  align-items: center;
  gap: 6px;
  font: 600 12.5px system-ui;
  color: oklch(0.72 0.13 165);
}

.saved__dot {
  width: 7px;
  height: 7px;
  border-radius: 2px;
  background: oklch(0.72 0.13 165);
}

.error {
  font: 500 11.5px system-ui;
  color: oklch(0.78 0.16 35);
}
</style>

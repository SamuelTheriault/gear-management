<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
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
 *
 * Section « Import / Export » (2026-08-04/05, demande de Samuel — export
 * complet JSON/XML d'un projet + export CSV par section + import CSV,
 * regroupés ici : « on va faire une section avec tout les import/export »).
 * Le backend (portability.py/csv_export.py/csv_import.py, views.py) a été
 * construit par une autre session en parallèle — cette section frontend
 * s'y branche mais n'a pas encore été câblée nulle part, d'où son ajout ici.
 * Un seul sélecteur de projet (`ioProjectId`, indépendant du projet actif
 * global) pilote l'export complet (JSON réimportable / XML lecture seule),
 * les 4 exports CSV par section et le SÉLECTEUR de liste pour l'import CSV.
 *
 * Import CSV par section (« on ajoute l'option d'importer un csv. On
 * vérifie que les entetes correspondent avant d'importer. On demande à
 * l'utilisateur si on ajoute à la suite de la liste ou si on écrasse tout
 * le contenu pour cette liste ») : contrairement à l'import de projet
 * (toujours un NOUVEAU projet), celui-ci écrit dans le projet SÉLECTIONNÉ
 * (`ioProjectId`). Le choix append/remplace se fait dans une confirmation
 * modale (`showCsvModeDialog`, gabarit `.fiche-confirm` déjà utilisé pour
 * le retrait d'accès sur `ProjetDetailView.vue`) — jamais d'écrasement
 * silencieux. La validation des en-têtes se fait côté backend, avant toute
 * écriture (voir `csv_export.parse_csv_rows`).
 */

const router = useRouter()
const { projects, allProjects, activeProjectId, refreshProjects } = useActiveProject()
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

// --- Projets archivés (2026-08-04) ---
//
// `projects` (useActiveProject) ne garde que les projets actifs — un projet
// archivé disparaissait donc complètement de l'app, y compris de cet écran,
// sans aucun moyen de le réafficher ou de le réactiver (bug trouvé par
// Samuel). `allProjects` (tous statuts) permet de les lister ici ; la
// réactivation elle-même n'est qu'un PATCH `status: 'active'` — même
// endpoint que ProjetDetailView.vue, juste sans passer par le formulaire
// d'édition complet.
const decoratedArchivedProjects = computed(() =>
  allProjects.value
    .filter((p) => p.status === 'archived')
    .map((p) => ({
      ...p,
      createdAtLabel: p.created_at ? dateFmt.format(new Date(p.created_at)) : '—',
    })),
)

const reactivatingId = ref(null)
const reactivateError = ref(null)

async function reactivateProject(p) {
  reactivateError.value = null
  reactivatingId.value = p.id
  try {
    await api.patch(`/projects/${p.id}/`, { status: 'active' })
    await refreshProjects()
  } catch (e) {
    reactivateError.value = e.data?.detail ?? 'Impossible de réactiver ce projet.'
  } finally {
    reactivatingId.value = null
  }
}

// --- Import / Export (2026-08-04/05) ---
//
// `ioProjectId` : sélecteur dédié, tous statuts confondus (`allProjects` —
// exporter un projet archivé doit rester possible), plutôt que de dépendre
// du projet actif global (`activeProjectId`) qu'on ne veut pas forcer à
// changer juste pour exporter/importer. Initialisé sur le projet actif s'il
// y en a un, sinon le premier projet de la liste.
const ioProjectId = ref(activeProjectId.value || null)
const ioProjects = computed(() => allProjects.value)

function ensureIoProjectSelected() {
  if (ioProjectId.value) return
  ioProjectId.value = activeProjectId.value || ioProjects.value[0]?.id || null
}

const importFileInput = ref(null)
const importFile = ref(null)
const importError = ref(null)
const importing = ref(false)

function onImportFileChange(event) {
  importFile.value = event.target.files?.[0] ?? null
  importError.value = null
}

async function importProject() {
  if (!importFile.value) {
    importError.value = 'Choisis un fichier .json exporté depuis un projet.'
    return
  }
  importError.value = null
  importing.value = true
  try {
    const text = await importFile.value.text()
    let parsed
    try {
      parsed = JSON.parse(text)
    } catch {
      importError.value = "Ce fichier n'est pas un JSON valide."
      return
    }
    const created = await api.post('/projects/import/', parsed)
    importFile.value = null
    if (importFileInput.value) importFileInput.value.value = ''
    await refreshProjects()
    router.push(`/projets/${created.project.id}`)
  } catch (e) {
    importError.value = e.data?.detail ?? "Impossible d'importer ce fichier."
  } finally {
    importing.value = false
  }
}

// --- Import CSV par section (2026-08-04/05) ---
//
// `replaceWarning` alimente le texte de la confirmation modale — spécifique
// à chaque liste puisque la cascade de suppression diffère (voir
// csv_import.py) : Lieux est en réalité REFUSÉ plutôt que supprimé si des
// références existent encore, les trois autres suppriment réellement et
// entraînent la perte des assignations/déplacements liés.
const CSV_SECTIONS = [
  {
    key: 'materials', label: 'Matériel', path: '/materials/import-csv/',
    replaceWarning:
      "supprime tout le matériel existant de ce projet — y compris ses assignations aux spectacles et déplacements.",
  },
  {
    key: 'venues', label: 'Lieux', path: '/venues/import-csv/',
    replaceWarning:
      "supprime tous les lieux existants de ce projet — refusé (sans rien supprimer) si un lieu est encore utilisé par un spectacle, un déplacement ou du matériel qui en fait son lieu d'origine.",
  },
  {
    key: 'technicians', label: 'Techniciens', path: '/technicians/import-csv/',
    replaceWarning:
      "supprime tous les techniciens existants de ce projet — y compris leurs assignations aux spectacles et déplacements.",
  },
  {
    key: 'shows', label: 'Spectacles', path: '/shows/import-csv/',
    replaceWarning:
      "supprime tous les spectacles existants de ce projet — y compris leur matériel, techniciens et déplacements assignés.",
  },
]

const csvSectionKey = ref('materials')
const csvSection = computed(() => CSV_SECTIONS.find((s) => s.key === csvSectionKey.value))

const csvFileInput = ref(null)
const csvFile = ref(null)
const csvError = ref(null)
const csvImporting = ref(false)
const csvResult = ref(null)
const showCsvModeDialog = ref(false)

function onCsvFileChange(event) {
  csvFile.value = event.target.files?.[0] ?? null
  csvError.value = null
  csvResult.value = null
}

function askCsvMode() {
  if (!csvFile.value) {
    csvError.value = 'Choisis un fichier .csv exporté depuis cette même liste.'
    return
  }
  if (!ioProjectId.value) {
    csvError.value = 'Choisis un projet.'
    return
  }
  csvError.value = null
  csvResult.value = null
  showCsvModeDialog.value = true
}

function cancelCsvImport() {
  showCsvModeDialog.value = false
}

async function confirmCsvImport(mode) {
  showCsvModeDialog.value = false
  csvImporting.value = true
  csvError.value = null
  try {
    const text = await csvFile.value.text()
    const result = await api.post(csvSection.value.path, {
      project: ioProjectId.value,
      mode,
      csv: text,
    })
    const count = Object.values(result.imported ?? {})[0] ?? 0
    csvResult.value =
      `${count} ligne(s) importée(s) dans « ${csvSection.value.label} »` +
      (mode === 'replace' ? ' (contenu existant remplacé).' : ' (ajoutées à la suite).')
    csvFile.value = null
    if (csvFileInput.value) csvFileInput.value.value = ''
  } catch (e) {
    csvError.value = e.data?.detail ?? "Impossible d'importer ce fichier."
  } finally {
    csvImporting.value = false
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

          <div v-if="decoratedArchivedProjects.length > 0" class="project-list project-list--archived">
            <div class="project-list__label">Archivés</div>
            <div v-for="p in decoratedArchivedProjects" :key="p.id" class="project-row project-row--archived">
              <span class="project-dot project-dot--archived" />
              <RouterLink :to="`/projets/${p.id}`" class="project-body">
                <div class="project-top">
                  <div class="project-name">{{ p.name }}</div>
                  <div class="project-date">Créé le {{ p.createdAtLabel }}</div>
                </div>
              </RouterLink>
              <div
                class="btn btn--small"
                :class="{ 'btn--disabled': reactivatingId === p.id }"
                @click="reactivatingId !== p.id && reactivateProject(p)"
              >
                {{ reactivatingId === p.id ? 'Réactivation…' : 'Réactiver' }}
              </div>
            </div>
            <div v-if="reactivateError" class="error">{{ reactivateError }}</div>
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

        <!-- Import / Export (2026-08-04/05) : export complet JSON/XML d'un
             projet, exports CSV par section (Excel), import de projet (crée
             toujours un nouveau projet) et import CSV par section (append/
             remplace, confirmé via une modale). -->
        <section class="section">
          <div class="section-title">Import / Export</div>
          <div class="card">
            <div class="field">
              <label class="label">Projet</label>
              <select v-model.number="ioProjectId" class="input" @focus="ensureIoProjectSelected">
                <option v-if="!ioProjects.length" :value="null" disabled>Aucun projet</option>
                <option v-for="p in ioProjects" :key="p.id" :value="p.id">
                  {{ p.name }}{{ p.status === 'archived' ? ' (archivé)' : '' }}
                </option>
              </select>
            </div>

            <div class="io-group">
              <div class="io-group__title">Exporter le projet</div>
              <div class="io-actions">
                <a
                  class="fiche-btn"
                  :class="{ 'fiche-btn--disabled': !ioProjectId }"
                  :href="ioProjectId ? api.downloadUrl(`/projects/${ioProjectId}/export/`, { format: 'json' }) : undefined"
                  download
                >Exporter en JSON</a>
                <a
                  class="fiche-btn"
                  :class="{ 'fiche-btn--disabled': !ioProjectId }"
                  :href="ioProjectId ? api.downloadUrl(`/projects/${ioProjectId}/export/`, { format: 'xml' }) : undefined"
                  download
                >Exporter en XML</a>
              </div>
              <div class="hint-text">
                Le projet en entier — lieux, matériel, techniciens, spectacles,
                assignations et déplacements. Le JSON peut être réimporté comme
                nouveau projet (voir « Importer un projet » ci-dessous) ; le
                XML est pour consultation dans un autre outil seulement.
              </div>
            </div>

            <div class="io-group">
              <div class="io-group__title">Exporter en CSV (pour Excel)</div>
              <div class="io-actions">
                <a
                  class="fiche-btn"
                  :class="{ 'fiche-btn--disabled': !ioProjectId }"
                  :href="ioProjectId ? api.downloadUrl('/materials/export-csv/', { project: ioProjectId }) : undefined"
                  download
                >Matériel</a>
                <a
                  class="fiche-btn"
                  :class="{ 'fiche-btn--disabled': !ioProjectId }"
                  :href="ioProjectId ? api.downloadUrl('/venues/export-csv/', { project: ioProjectId }) : undefined"
                  download
                >Lieux</a>
                <a
                  class="fiche-btn"
                  :class="{ 'fiche-btn--disabled': !ioProjectId }"
                  :href="ioProjectId ? api.downloadUrl('/technicians/export-csv/', { project: ioProjectId }) : undefined"
                  download
                >Techniciens</a>
                <a
                  class="fiche-btn"
                  :class="{ 'fiche-btn--disabled': !ioProjectId }"
                  :href="ioProjectId ? api.downloadUrl('/shows/export-csv/', { project: ioProjectId }) : undefined"
                  download
                >Spectacles</a>
              </div>
              <div class="hint-text">Une section à la fois, pour un passage vers un tableur.</div>
            </div>

            <div class="io-group">
              <div class="io-group__title">Importer un projet</div>
              <div class="create-row">
                <input
                  ref="importFileInput"
                  type="file"
                  accept="application/json"
                  class="input input--wide"
                  @change="onImportFileChange"
                />
                <div
                  class="btn"
                  :class="importFile && !importing ? 'btn--enabled' : 'btn--disabled'"
                  @click="importFile && !importing && importProject()"
                >
                  {{ importing ? 'Import…' : '↑ Importer' }}
                </div>
              </div>
              <div v-if="importError" class="error">{{ importError }}</div>
              <div class="hint-text">
                À partir d'un fichier JSON exporté ci-dessus — crée toujours un
                nouveau projet, n'écrase jamais un projet existant.
              </div>
            </div>

            <div class="io-group">
              <div class="io-group__title">Importer un CSV (Excel)</div>
              <div class="field">
                <label class="label">Liste visée</label>
                <div class="chips">
                  <div
                    v-for="s in CSV_SECTIONS"
                    :key="s.key"
                    class="chip"
                    :class="{ 'chip--active': csvSectionKey === s.key }"
                    @click="csvSectionKey = s.key"
                  >
                    {{ s.label }}
                  </div>
                </div>
              </div>
              <div class="create-row">
                <input
                  ref="csvFileInput"
                  type="file"
                  accept=".csv,text/csv"
                  class="input input--wide"
                  @change="onCsvFileChange"
                />
                <div
                  class="btn"
                  :class="csvFile && !csvImporting ? 'btn--enabled' : 'btn--disabled'"
                  @click="csvFile && !csvImporting && askCsvMode()"
                >
                  {{ csvImporting ? 'Import…' : '↑ Importer' }}
                </div>
              </div>
              <div v-if="csvError" class="error">{{ csvError }}</div>
              <div v-if="csvResult" class="saved"><span class="saved__dot" />{{ csvResult }}</div>
              <div class="hint-text">
                À partir d'un export généré ci-dessus, pour la même liste — les
                en-têtes de colonnes doivent correspondre (ordre libre,
                colonnes en trop ignorées). On te demandera ensuite si les
                lignes s'ajoutent à la suite ou remplacent tout le contenu
                existant de cette liste, pour ce projet.
              </div>
            </div>
          </div>
        </section>

        <div v-if="showCsvModeDialog" class="fiche-confirm-backdrop" @click.self="cancelCsvImport">
          <div class="fiche-confirm">
            <div class="fiche-confirm__title">Importer « {{ csvSection.label }} » — {{ csvFile?.name }}</div>
            <p class="fiche-confirm__text">
              À la suite : les lignes du fichier s'ajoutent au contenu existant, sans rien supprimer.<br />
              Remplacer tout : {{ csvSection.replaceWarning }}
            </p>
            <div v-if="csvError" class="fiche-error">{{ csvError }}</div>
            <div class="fiche-confirm__actions">
              <button type="button" class="fiche-btn" :disabled="csvImporting" @click="cancelCsvImport">
                Annuler
              </button>
              <button type="button" class="fiche-btn" :disabled="csvImporting" @click="confirmCsvImport('append')">
                À la suite
              </button>
              <button
                type="button"
                class="fiche-btn fiche-btn--danger"
                :disabled="csvImporting"
                @click="confirmCsvImport('replace')"
              >
                Remplacer tout
              </button>
            </div>
          </div>
        </div>

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

/* Projets archivés (2026-08-04) : même carte que la liste
   active, ligne grisée plutôt qu'un lien plein-largeur (le nom reste
   cliquable vers la fiche, « Réactiver » agit directement depuis ici sans y
   entrer). */
.project-list--archived {
  margin-top: 10px;
}

.project-list__label {
  font: 700 10.5px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: rgba(var(--fg-rgb), 0.4);
  padding: 6px 10px 8px;
}

.project-row--archived {
  align-items: center;
  opacity: 0.75;
}

.project-row--archived .project-body {
  text-decoration: none;
  color: inherit;
  cursor: pointer;
  display: block;
}

.project-dot--archived {
  background: rgba(var(--fg-rgb), 0.3);
}

.btn--small {
  padding: 6px 12px;
  font: 600 11.5px system-ui;
  flex: none;
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

/* Import / Export (2026-08-04/05) : chaque sous-groupe (export complet, CSV,
   import projet, import CSV) partage la même trame que .create-card
   ci-dessus, sans la bordure pointillée — ce ne sont pas des zones de saisie
   « brouillon », juste des regroupements dans la même carte. */
.io-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.io-group + .io-group {
  padding-top: 12px;
  border-top: 1px solid rgba(var(--fg-rgb), 0.05);
}

.io-group__title {
  font: 700 10.5px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: rgba(var(--fg-rgb), 0.4);
}

.io-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.fiche-btn--disabled {
  opacity: 0.4;
  pointer-events: none;
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

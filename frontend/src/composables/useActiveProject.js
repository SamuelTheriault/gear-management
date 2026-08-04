import { ref, computed } from 'vue'
import { api } from '../api/client'

/**
 * Bascule entre productions (voir architecture.md, section 4quater et
 * workflow 7) : entièrement côté frontend, sans recharger/exporter de
 * fichier. Le projet actif est mémorisé dans localStorage et ajouté en
 * `?project=<id>` sur les appels API qui isolent leurs données par projet
 * (venues, materials, technicians, shows — pas settings/users, communs à
 * tous les projets).
 */

const STORAGE_KEY = 'gmp_active_project_id'

const projects = ref([])
// Liste brute, tous statuts confondus (2026-08-04) — `projects` ci-dessus
// reste filtrée aux projets actifs (sélecteur, garde d'onboarding), mais un
// écran comme ReglagesView a besoin de voir aussi les projets ARCHIVÉS pour
// pouvoir les réafficher et les réactiver (sans quoi un projet archivé
// devient invisible et donc irrécupérable depuis l'interface).
const allProjects = ref([])
const activeProjectId = ref(Number(localStorage.getItem(STORAGE_KEY)) || null)
const loaded = ref(false)
const loading = ref(false)
const error = ref(null)

// Promesse du chargement en cours, s'il y en a un — permet à un appelant
// (le garde de route, notamment, voir router/index.js) d'ATTENDRE que la
// liste soit connue avant de décider d'une redirection, plutôt que de lire
// `projects.value` pendant qu'il est encore vide par défaut. `loadProjects`
// reste par ailleurs appelable « fire-and-forget » comme avant (AppShell,
// ReglagesView, ...) : elle retourne toujours la même promesse partagée.
let inFlight = null

async function loadProjects() {
  if (loaded.value) return
  if (inFlight) return inFlight
  loading.value = true
  error.value = null
  inFlight = (async () => {
    try {
      // ProjectViewSet n'a pas de filtre `?status=` côté serveur (queryset brut,
      // pas de ProjectFilteredMixin) — on filtre les projets archivés côté client.
      const data = await api.get('/projects/')
      const all = Array.isArray(data) ? data : (data.results ?? [])
      allProjects.value = all
      projects.value = all.filter((p) => p.status === 'active')

      const stillValid = projects.value.some((p) => p.id === activeProjectId.value)
      if (!stillValid) {
        activeProjectId.value = projects.value[0]?.id ?? null
      }
      loaded.value = true
    } catch (e) {
      error.value = e
    } finally {
      loading.value = false
      inFlight = null
    }
  })()
  return inFlight
}

function setActiveProject(id) {
  activeProjectId.value = id
  localStorage.setItem(STORAGE_KEY, String(id))
}

// Force un rechargement de la liste (ex. après création d'un projet depuis
// ReglagesView.vue) — contourne le garde `loaded` qui limite normalement à un
// seul fetch par session SPA (voir note du module ci-dessus).
async function refreshProjects() {
  loaded.value = false
  await loadProjects()
}

const activeProject = computed(
  () => projects.value.find((p) => p.id === activeProjectId.value) ?? null,
)

export function useActiveProject() {
  loadProjects()
  return {
    projects,
    allProjects,
    activeProjectId,
    activeProject,
    setActiveProject,
    refreshProjects,
    // Exposée pour router/index.js (garde d'onboarding) : `await
    // ensureProjectsLoaded()` avant de lire `projects.value` pour décider
    // d'une redirection. Sans effet si déjà chargée (voir `loaded` ci-dessus).
    ensureProjectsLoaded: loadProjects,
    loading,
    error,
  }
}

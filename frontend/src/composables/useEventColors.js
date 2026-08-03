import { ref } from 'vue'
import { api } from '../api/client'

/**
 * Couleurs des bandes qui ne sont rattachées à aucune fiche éditable
 * (contrairement à `Venue.color`/`MaterialCategory.color`) — ajoutées le
 * 2026-08-02 à la demande de Samuel : « les options pour changer les couleur
 * des bandes qui ne sont pas gérées dans une fiche. Je pense surtout aux
 * transports », étendu aux types de spectacle (`Show.EVENT_TYPE_CHOICES`,
 * jusqu'ici dupliqués en dur dans 4 fichiers Vue distincts) après confirmation
 * de Samuel.
 *
 * Singleton comme `useTheme.js`/`useActiveProject.js` : un seul chargement
 * de `Settings` partagé par toute l'app. Les 6 couleurs (transport + 5 types)
 * sont posées comme des CSS custom properties sur `<html>`
 * (`--transport`/`--event-rehearsal`/`--event-performance`/
 * `--event-storage`/`--event-setup`/`--event-teardown`) — même technique que
 * `useTheme.js` pour `data-theme`, plutôt que de les passer en props/computed
 * à chaque composant. `style.css` porte des valeurs de repli statiques
 * identiques aux défauts de `Settings` (voir `models.py`), donc rien ne
 * « saute » avant que ce module ait fini de charger : au pire, un très bref
 * instant à la valeur par défaut si Samuel a personnalisé une couleur.
 *
 * Les 4 vues qui affichaient ces couleurs en dur (`SpectaclesView.vue`,
 * `SpectacleDetailView.vue`, `MaterielDetailView.vue`, `DashboardView.vue`)
 * référencent maintenant ces variables via `constants/eventTypeMeta.js` —
 * elles n'ont plus besoin d'importer ce composable directement, seul
 * `ReglagesView.vue` (édition) et ce module (chargement + application) le
 * font. `DashboardView.vue` déclinait déjà Montage/Démontage dans une teinte
 * plus foncée sur sa timeline (pour les distinguer du spectacle qu'ils
 * encadrent) — cette nuance reste une déclinaison CALCULÉE
 * (`color-mix(in oklch, var(--event-setup) 70%, black)`) à partir de cette
 * même couleur de base, pas une deuxième valeur stockée : une seule source
 * par type, comme demandé.
 */

const CSS_VAR_BY_FIELD = {
  transport_color: '--transport',
  event_color_rehearsal: '--event-rehearsal',
  event_color_performance: '--event-performance',
  event_color_storage: '--event-storage',
  event_color_setup: '--event-setup',
  event_color_teardown: '--event-teardown',
}

const settings = ref(null)
const loaded = ref(false)

function apply(values) {
  const root = document.documentElement
  for (const [field, cssVar] of Object.entries(CSS_VAR_BY_FIELD)) {
    if (values[field]) root.style.setProperty(cssVar, values[field])
  }
}

async function loadEventColors() {
  const data = await api.get('/settings/')
  settings.value = data
  apply(data)
  loaded.value = true
  return data
}

// Chargement dès le premier import (même pattern que l'application du thème
// dans useTheme.js) — AppShell.vue (mis en place uniquement après
// connexion) importe ce module au montage, donc ce fetch ne part jamais
// avant qu'une session existe.
let loadPromise = null
function ensureLoaded() {
  if (!loadPromise) loadPromise = loadEventColors()
  return loadPromise
}

/** Appelé après un PATCH réussi sur /api/settings/ (ReglagesView) pour que
 * les couleurs se reflètent immédiatement partout, sans recharger la page. */
function refreshEventColors() {
  loadPromise = loadEventColors()
  return loadPromise
}

export function useEventColors() {
  ensureLoaded()
  return { settings, loaded, refreshEventColors }
}

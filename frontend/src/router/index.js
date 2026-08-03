import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '../composables/useAuth'
import DashboardView from '../views/DashboardView.vue'
import LoginView from '../views/LoginView.vue'
import ReglagesView from '../views/ReglagesView.vue'
import UtilisateursView from '../views/UtilisateursView.vue'
import SpectaclesView from '../views/SpectaclesView.vue'
import SpectacleDetailView from '../views/SpectacleDetailView.vue'
import MaterielView from '../views/MaterielView.vue'
import MaterielDetailView from '../views/MaterielDetailView.vue'
import CategoriesMaterielView from '../views/CategoriesMaterielView.vue'
import ParcoursMaterielView from '../views/ParcoursMaterielView.vue'
import ParcoursTechniciensView from '../views/ParcoursTechniciensView.vue'
import LieuxView from '../views/LieuxView.vue'
import LieuDetailView from '../views/LieuDetailView.vue'
import TechniciensView from '../views/TechniciensView.vue'
import TechnicienDetailView from '../views/TechnicienDetailView.vue'
import TransportsView from '../views/TransportsView.vue'
import TransportDetailView from '../views/TransportDetailView.vue'
import ConflitsView from '../views/ConflitsView.vue'
import CoherenceEmplacementsView from '../views/CoherenceEmplacementsView.vue'
import ProjetDetailView from '../views/ProjetDetailView.vue'

const routes = [
  { path: '/', name: 'dashboard', component: DashboardView },
  { path: '/spectacles', name: 'spectacles', component: SpectaclesView },
  { path: '/spectacles/:id', name: 'spectacle-detail', component: SpectacleDetailView },
  { path: '/materiel', name: 'materiel', component: MaterielView },
  // Déclarée AVANT /materiel/:id — vue-router privilégie déjà un segment
  // statique sur un paramètre, mais l'ordre rend l'intention explicite.
  { path: '/materiel/categories', name: 'materiel-categories', component: CategoriesMaterielView },
  { path: '/materiel/:id', name: 'materiel-detail', component: MaterielDetailView },
  { path: '/lieux', name: 'lieux', component: LieuxView },
  { path: '/lieux/:id', name: 'lieu-detail', component: LieuDetailView },
  { path: '/techniciens', name: 'techniciens', component: TechniciensView },
  { path: '/techniciens/:id', name: 'technicien-detail', component: TechnicienDetailView },
  { path: '/transports', name: 'transports', component: TransportsView },
  { path: '/transports/:id', name: 'transport-detail', component: TransportDetailView },
  // Parcours : rattachés au Tableau de bord dans la sidebar depuis le
  // 2026-07-30, d'où leur propre préfixe `/parcours/` plutôt que
  // `/materiel/...` et `/techniciens/...`. Les anciens chemins redirigent,
  // pour ne pas casser un signet.
  { path: '/parcours/materiel', name: 'parcours-materiel', component: ParcoursMaterielView },
  { path: '/parcours/techniciens', name: 'parcours-techniciens', component: ParcoursTechniciensView },
  { path: '/materiel/parcours', redirect: '/parcours/materiel' },
  { path: '/techniciens/parcours', redirect: '/parcours/techniciens' },
  { path: '/conflits', name: 'conflits', component: ConflitsView },
  { path: '/coherence', name: 'coherence', component: CoherenceEmplacementsView },
  { path: '/reglages', name: 'reglages', component: ReglagesView },
  { path: '/projets/:id', name: 'projet-detail', component: ProjetDetailView },
  { path: '/utilisateurs', name: 'utilisateurs', component: UtilisateursView },
  { path: '/login', name: 'login', component: LoginView },
  // Départements retiré le 2026-07-29 (modèle Department abandonné, voir
  // CLAUDE.md / recapitulatif_projet.md).
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

// Garde d'authentification (voir useAuth.js et security.md) : toutes les
// routes exigent une session Django établie (login Google via
// django-allauth), sauf /login elle-même. Un seul GET /api/auth/user/ par
// session SPA (singleton, mis en cache par useAuth) — les navigations
// suivantes réutilisent le résultat déjà connu sans reappeler l'API.
router.beforeEach(async (to) => {
  if (to.path === '/login') return true
  const { currentUser, checkAuth } = useAuth()
  await checkAuth()
  if (!currentUser.value) {
    return { path: '/login' }
  }
  return true
})

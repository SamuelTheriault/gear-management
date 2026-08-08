import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '../composables/useAuth'
import { useActiveProject } from '../composables/useActiveProject'
import DashboardView from '../views/DashboardView.vue'
import LoginView from '../views/LoginView.vue'
import OnboardingView from '../views/OnboardingView.vue'
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
import CamionsView from '../views/CamionsView.vue'
import CamionDetailView from '../views/CamionDetailView.vue'
import TransportsView from '../views/TransportsView.vue'
import TransportDetailView from '../views/TransportDetailView.vue'
import ConflitsView from '../views/ConflitsView.vue'
import CoherenceEmplacementsView from '../views/CoherenceEmplacementsView.vue'
import ProjetDetailView from '../views/ProjetDetailView.vue'
import PublicReportView from '../views/PublicReportView.vue'

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
  { path: '/camions', name: 'camions', component: CamionsView },
  { path: '/camions/:id', name: 'camion-detail', component: CamionDetailView },
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
  // Onboarding (2026-08-04) : voir garde ci-dessous — atteinte uniquement
  // par redirection quand le compte connecté n'a encore aucun projet actif.
  { path: '/bienvenue', name: 'onboarding', component: OnboardingView },
  // Page PUBLIQUE d'une sortie de rapport (2026-08-08) — destination du code
  // QR imprimé en pied de feuille. SEULE route de l'app exemptée de la garde
  // ci-dessous : la personne qui scanne (technicien pigiste, DT d'une salle
  // partenaire) n'a pas de compte, et c'est précisément l'intérêt. Le jeton
  // dans l'URL tient lieu d'authentification — voir PublicReportView.vue et
  // backend/inventory/public_views.py pour le modèle de menace.
  { path: '/p/:token', name: 'rapport-public', component: PublicReportView },
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
//
// Garde d'onboarding (2026-08-04, remplace l'ancien bandeau prévu au
// backlog par un écran bloquant — décision de Samuel) : un compte connecté
// SANS AUCUN projet actif (`ProjectMembership` actif nulle part, ou
// installation flambant neuve) est redirigé vers /bienvenue quel que soit
// l'écran visé — sans ça, Lieu/Technicien/... échouaient en 400 en silence
// (`project` envoyé `null`, voir suivi_projet.md). Symétriquement, un
// compte qui a déjà au moins un projet actif ne doit plus voir /bienvenue
// (retour arrière, lien direct, ...) — renvoyé au tableau de bord.
// `ensureProjectsLoaded()` réutilise le chargement mis en cache par
// useActiveProject (AppShell, ReglagesView, ...) : un seul GET /api/projects/
// par session SPA, pas un par navigation.
//
// Exemption /reglages + /projets/:id (2026-08-04, bug trouvé par Samuel) :
// sans elle, archiver son SEUL projet actif (Project.status='archived',
// donc absent de `projects` — voir useActiveProject.js) renvoyait vers
// /bienvenue, qui bloquait à son tour l'accès à Réglages/la fiche du
// projet — plus aucun moyen de le réactiver depuis l'interface. Ces deux
// écrans sont de la gestion de projet (créer/lister/réactiver), pas des
// écrans de saisie qui ont besoin d'un projet actif pour fonctionner —
// contrairement à Matériel/Lieux/etc., toujours bloqués sans projet actif.
//
// Exemption /utilisateurs (2026-08-04, revue code-reviewer) : même famille
// de piège — c'est un écran de gestion PLATEFORME (comptes/pré-provisioning,
// réservé staff, voir UserViewSet côté API), pas une production, il n'a donc
// aucune raison de dépendre d'un projet actif. Un compte staff qu'on vient de
// créer et qui n'a encore été ajouté à aucun projet (voir la note de Samuel :
// dès qu'un compte est ajouté à un projet, `hasActiveProject` suffit déjà à
// lui éviter l'onboarding — ce cas-ci ne couvre que l'entre-deux) doit
// pouvoir aller y inviter/gérer des comptes sans être bloqué par l'écran
// d'onboarding.
router.beforeEach(async (to) => {
  // Exemption /p/:token (2026-08-08) : page publique de rapport. Placée AVANT
  // `checkAuth()` pour qu'aucun GET /api/auth/user/ ne parte — un appel
  // authentifié depuis une page publique n'a pas de sens, et le 403 attendu
  // polluerait la console de la personne qui vient de scanner le code.
  if (to.path === '/login' || to.path.startsWith('/p/')) return true
  const { currentUser, checkAuth } = useAuth()
  await checkAuth()
  if (!currentUser.value) {
    return { path: '/login' }
  }

  const { projects, ensureProjectsLoaded } = useActiveProject()
  await ensureProjectsLoaded()
  const hasActiveProject = projects.value.length > 0
  const isProjectManagementRoute = (
    to.path === '/reglages' || to.path.startsWith('/projets/') || to.path === '/utilisateurs'
  )

  if (!hasActiveProject && to.path !== '/bienvenue' && !isProjectManagementRoute) {
    return { path: '/bienvenue' }
  }
  if (hasActiveProject && to.path === '/bienvenue') {
    return { path: '/' }
  }
  return true
})

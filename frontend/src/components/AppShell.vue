<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'
import { useActiveProject } from '../composables/useActiveProject'
import { useAuth } from '../composables/useAuth'
import { useEscapeKey } from '../composables/useEscapeKey'
import { useEventColors } from '../composables/useEventColors'
import { useTheme } from '../composables/useTheme'

/**
 * Coquille commune à tout RégiStock : sidebar desktop, qui devient un tiroir
 * (drawer) sous 860px plutôt que de disparaître complètement (2026-07-31,
 * remplace l'ancienne tabbar à 4 raccourcis — celle-ci ne couvrait qu'une
 * fraction des sections et masquait tout le reste sur mobile).
 * L'entrée « Départements » (sous-item de Matériel) a été retirée le
 * 2026-07-29 avec le modèle `Department`, abandonné au profit de
 * `Material.category` — voir décision dans recapitulatif_projet.md.
 *
 * Le pied de sidebar (2026-07-30) affiche le courriel de la session active
 * (`GET /api/auth/user/`, voir useAuth.js) et un lien de déconnexion — cette
 * page n'est jamais atteinte tant que le garde de route (router/index.js)
 * n'a pas confirmé une session valide, donc `currentUser` y est toujours
 * renseigné en pratique.
 *
 * Toggle Dark/Bright (2026-08-02, demande de Samuel) : ajouté juste au-dessus
 * de ce bloc compte, dans le même pied de sidebar — voir useTheme.js pour la
 * persistance et l'anti-flash. Un seul bouton bascule vers l'AUTRE mode (pas
 * deux boutons séparés) : plus compact, cohérent avec les `zoom-btn` déjà en
 * place ailleurs dans l'app.
 */

const route = useRoute()
const router = useRouter()
const { projects, activeProjectId, setActiveProject, loading: projectsLoading } =
  useActiveProject()
const { currentUser, logout } = useAuth()
const { theme, toggleTheme } = useTheme()
// Charge Settings et pose les CSS vars de couleur (--transport, --event-*)
// dès l'entrée dans l'app — voir useEventColors.js. Rien d'autre à faire ici,
// le composable applique lui-même les variables sur <html>.
useEventColors()

// Tiroir mobile (<860px) : même contenu que la sidebar desktop, pas de liste
// séparée. Fermé par défaut, ouvert via le bouton ☰ flottant, refermé au
// clic sur l'overlay ou dès qu'on navigue (sinon il resterait ouvert
// par-dessus la nouvelle page après un clic sur un lien).
const drawerOpen = ref(false)

function toggleDrawer() {
  drawerOpen.value = !drawerOpen.value
}

function closeDrawer() {
  drawerOpen.value = false
}

watch(
  () => route.path,
  () => {
    drawerOpen.value = false
  },
)

// Échap referme le tiroir, même geste que le clic sur l'overlay.
useEscapeKey(() => {
  if (drawerOpen.value) closeDrawer()
})

async function handleLogout() {
  await logout()
  router.push('/login')
}

// `children` : sous-menu affiché seulement quand la section parente est
// active. Deux sections en ont un — Tableau de bord (vue d'ensemble,
// les deux parcours, Conflits et Cohérence : tous des rapports
// transversaux au projet, plutôt que des entités qu'on liste/édite comme un
// spectacle ou un lieu — Conflits/Cohérence rejoignent le sous-menu le
// 2026-07-31, à la demande de Samuel, suite à l'audit ergonomie) et
// Matériel (Inventaire / Catégories). Le tiroir mobile reprend cette même
// structure telle quelle (voir plus bas).
//
// `activeMatch` : prédicat d'activation du parent, quand `startsWith` ne
// suffit pas. Le Tableau de bord pointe sur `/`, qui préfixe tout — et ses
// enfants vivent sous `/parcours/`, `/conflits` et `/coherence`, hors de son
// propre chemin.
const navItems = [
  {
    label: 'Tableau de bord',
    to: '/',
    activeMatch: (p) =>
      p === '/' || p.startsWith('/parcours') || p.startsWith('/conflits') || p.startsWith('/coherence'),
    children: [
      { label: 'Vue d\'ensemble', to: '/', match: (p) => p === '/' },
      { label: 'Parcours Matériel', to: '/parcours/materiel' },
      { label: 'Parcours Technicien', to: '/parcours/techniciens' },
      { label: 'Conflits', to: '/conflits' },
      { label: 'Cohérence', to: '/coherence' },
    ],
  },
  {
    label: 'Matériel',
    to: '/materiel',
    children: [
      // « Inventaire » couvre /materiel et /materiel/{id} (la fiche), mais
      // pas /materiel/categories — d'où le prédicat explicite plutôt qu'un
      // simple `startsWith`.
      { label: 'Inventaire', to: '/materiel', match: (p) => p === '/materiel' || /^\/materiel\/\d+/.test(p) },
      { label: 'Catégories', to: '/materiel/categories' },
    ],
  },
  { label: 'Spectacles', to: '/spectacles' },
  { label: 'Lieux', to: '/lieux' },
  { label: 'Techniciens', to: '/techniciens' },
  { label: 'Transports', to: '/transports' },
]

const bottomNavItems = [
  { label: 'Réglages', to: '/reglages' },
  { label: 'Utilisateurs', to: '/utilisateurs' },
]

function isActive(item) {
  // Accepte un item de menu ou un simple chemin (bottomNavItems passe un chemin).
  const to = typeof item === 'string' ? item : item.to
  const match = typeof item === 'string' ? null : item.activeMatch
  if (match) return match(route.path)
  if (to === '/') return route.path === '/'
  return route.path.startsWith(to)
}

function isSubActive(item) {
  return item.match ? item.match(route.path) : route.path.startsWith(item.to)
}

const activeProjectIdModel = computed({
  get: () => activeProjectId.value ?? '',
  set: (val) => setActiveProject(Number(val)),
})
</script>

<template>
  <div class="shell">
    <button
      type="button"
      class="shell-menu-btn"
      :class="{ 'shell-menu-btn--open': drawerOpen }"
      aria-label="Ouvrir le menu"
      :aria-expanded="drawerOpen"
      @click="toggleDrawer"
    >
      <span />
      <span />
      <span />
    </button>

    <div v-if="drawerOpen" class="shell-nav-overlay" @click="closeDrawer" />

    <nav class="shell-nav" :class="{ 'shell-nav--open': drawerOpen }">
      <div class="shell-nav__label">RégiStock</div>

      <select
        v-if="!projectsLoading && projects.length > 0"
        v-model="activeProjectIdModel"
        class="shell-nav__project"
      >
        <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select>

      <template v-for="item in navItems" :key="item.label">
        <RouterLink
          :to="item.to"
          class="shell-nav__item"
          :class="{ 'shell-nav__item--active': isActive(item) }"
        >
          <span class="shell-nav__dot" />{{ item.label }}
        </RouterLink>
        <div v-if="item.children && isActive(item)" class="shell-nav__sub">
          <RouterLink
            v-for="child in item.children"
            :key="child.label"
            :to="child.to"
            class="shell-nav__subitem"
            :class="{ 'shell-nav__subitem--active': isSubActive(child) }"
          >
            {{ child.label }}
          </RouterLink>
        </div>
      </template>

      <RouterLink
        v-for="item in bottomNavItems"
        :key="item.label"
        :to="item.to"
        class="shell-nav__item shell-nav__item--linkstyle"
        :class="{ 'shell-nav__item--active': isActive(item.to) }"
      >
        {{ item.label }}
      </RouterLink>

      <div class="shell-nav__footer">
        <button type="button" class="shell-nav__theme" @click="toggleTheme">
          <span class="shell-nav__theme-icon">{{ theme === 'light' ? '☀' : '☾' }}</span>
          Passer en {{ theme === 'light' ? 'sombre' : 'clair' }}
        </button>

        <div class="shell-nav__account" v-if="currentUser">
          <div class="shell-nav__email" :title="currentUser.email">{{ currentUser.email }}</div>
          <div class="shell-nav__logout" @click="handleLogout">Se déconnecter</div>
        </div>
      </div>
    </nav>

    <div class="shell-main">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  min-height: 100vh;
  background:
    var(--bg-page) radial-gradient(rgba(var(--fg-rgb), 0.09) 1px, transparent 1.5px) 0 0 / 22px 22px;
  color: rgb(var(--fg-rgb));
  font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
}

.shell-nav {
  flex: none;
  width: 220px;
  background: var(--bg-deep);
  border-right: 1px solid rgba(var(--fg-rgb), 0.08);
  padding: 24px 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.shell-nav__label {
  font: 700 15px/1 var(--font-mono);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgb(var(--fg-rgb));
  padding: 0 8px 12px;
}

.shell-nav__project {
  margin-bottom: 12px;
  padding: 8px 10px;
  border-radius: var(--radius-notch-sm);
  background: var(--bg-row);
  border: 1px solid rgba(var(--fg-rgb), 0.1);
  color: rgb(var(--fg-rgb));
  font: 500 12px system-ui;
}

.shell-nav__item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 8px;
  border-radius: 8px;
  color: rgba(var(--fg-rgb), 0.55);
  font: 500 13px system-ui;
  text-decoration: none;
}

.shell-nav__item--linkstyle {
  display: block;
}

.shell-nav__item--active {
  border-radius: 8px 8px 0 0;
  background: rgba(var(--accent-rgb), 0.18);
  color: var(--accent);
  font-weight: 600;
}

.shell-nav__sub {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px 0 4px 26px;
}

.shell-nav__subitem {
  padding: 7px 8px;
  border-radius: 8px;
  color: rgba(var(--fg-rgb), 0.45);
  font: 500 12.5px system-ui;
  text-decoration: none;
}

.shell-nav__subitem--active {
  color: var(--accent);
  background: rgba(var(--accent-rgb), 0.12);
  font-weight: 600;
}

.shell-nav__dot {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  background: currentColor;
  flex: none;
  opacity: 0.7;
}

.shell-nav__item--active .shell-nav__dot {
  background: rgb(var(--accent-rgb));
  opacity: 1;
}

.shell-nav__footer {
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px solid rgba(var(--fg-rgb), 0.06);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.shell-nav__theme {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  margin: 0;
  width: fit-content;
  border: 1px solid var(--border-card);
  border-radius: var(--radius-notch-sm);
  background: rgba(var(--fg-rgb), 0.04);
  color: rgba(var(--fg-rgb), 0.55);
  font: 600 11px system-ui;
  cursor: pointer;
}

.shell-nav__theme:hover {
  background: rgba(var(--accent-rgb), 0.16);
  color: var(--accent);
  border-color: rgba(var(--accent-rgb), 0.4);
}

.shell-nav__theme-icon {
  font-size: 12px;
}

.shell-nav__account {
  padding: 0 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.shell-nav__email {
  font: 500 11px system-ui;
  color: rgba(var(--fg-rgb), 0.4);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.shell-nav__logout {
  font: 600 11.5px system-ui;
  color: var(--link);
  cursor: pointer;
  width: fit-content;
}

.shell-main {
  flex: 1;
  min-width: 0;
  padding: 32px 40px 96px;
  box-sizing: border-box;
}

/* Bouton d'ouverture du tiroir : caché par défaut, n'apparaît que sous
   860px (voir media query plus bas). Flottant plutôt qu'intégré à une
   barre d'en-tête — il n'y en a pas sur mobile, en ajouter une aurait été
   un changement structurel plus lourd que nécessaire ici. */
.shell-menu-btn {
  display: none;
  position: fixed;
  top: 16px;
  left: 16px;
  z-index: 210;
  width: 40px;
  height: 40px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  border: 1px solid rgba(var(--fg-rgb), 0.1);
  border-radius: var(--radius-notch-sm);
  background: #14171c;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.4);
  cursor: pointer;
  padding: 0;
}

.shell-menu-btn span {
  width: 18px;
  height: 2px;
  background: rgb(var(--fg-rgb));
  border-radius: 1px;
  transition: transform 0.15s ease, opacity 0.15s ease;
}

.shell-menu-btn--open span:nth-child(1) {
  transform: translateY(6px) rotate(45deg);
}

.shell-menu-btn--open span:nth-child(2) {
  opacity: 0;
}

.shell-menu-btn--open span:nth-child(3) {
  transform: translateY(-6px) rotate(-45deg);
}

.shell-nav-overlay {
  display: none;
}

@media (max-width: 860px) {
  .shell-menu-btn {
    display: flex;
  }

  .shell-nav-overlay {
    display: block;
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.55);
    z-index: 199;
  }

  .shell-nav {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    z-index: 200;
    width: min(280px, 82vw);
    transform: translateX(-100%);
    transition: transform 0.2s ease;
    overflow-y: auto;
    box-shadow: 4px 0 24px rgba(0, 0, 0, 0.5);
  }

  .shell-nav--open {
    transform: translateX(0);
  }

  .shell-main {
    padding: 76px 20px 32px;
  }
}
</style>

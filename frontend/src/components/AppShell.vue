<script setup>
import { computed } from 'vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'
import { useActiveProject } from '../composables/useActiveProject'
import { useAuth } from '../composables/useAuth'

/**
 * Coquille commune à tout RégiStock : sidebar desktop + tabbar mobile.
 * L'entrée « Départements » (sous-item de Matériel) a été retirée le
 * 2026-07-29 avec le modèle `Department`, abandonné au profit de
 * `Material.category` — voir décision dans recapitulatif_projet.md.
 *
 * Le pied de sidebar (2026-07-30) affiche le courriel de la session active
 * (`GET /api/auth/user/`, voir useAuth.js) et un lien de déconnexion — cette
 * page n'est jamais atteinte tant que le garde de route (router/index.js)
 * n'a pas confirmé une session valide, donc `currentUser` y est toujours
 * renseigné en pratique.
 */

const route = useRoute()
const router = useRouter()
const { projects, activeProjectId, setActiveProject, loading: projectsLoading } =
  useActiveProject()
const { currentUser, logout } = useAuth()

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
// Matériel (Inventaire / Catégories). La tabbar mobile reste à plat.
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

const tabbarItems = [
  { label: 'Accueil', to: '/' },
  { label: 'Spectacles', to: '/spectacles' },
  { label: 'Matériel', to: '/materiel' },
  { label: 'Techniciens', to: '/techniciens' },
]

function isActive(item) {
  // Accepte un item de menu ou un simple chemin (la tabbar passe un chemin).
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
    <nav class="shell-nav">
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

      <div class="shell-nav__account" v-if="currentUser">
        <div class="shell-nav__email" :title="currentUser.email">{{ currentUser.email }}</div>
        <div class="shell-nav__logout" @click="handleLogout">Se déconnecter</div>
      </div>
      <div class="shell-nav__version">v0.1 · JD</div>
    </nav>

    <div class="shell-main">
      <slot />
    </div>

    <nav class="shell-tabbar">
      <RouterLink
        v-for="item in tabbarItems"
        :key="item.label"
        :to="item.to"
        class="shell-tabbar__item"
        :class="{ 'shell-tabbar__item--active': isActive(item.to) }"
      >
        <span class="shell-tabbar__icon" :class="{ 'shell-tabbar__icon--active': isActive(item.to) }" />
        <span>{{ item.label }}</span>
      </RouterLink>
    </nav>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  min-height: 100vh;
  background:
    #0b0d10 radial-gradient(rgba(255, 255, 255, 0.09) 1px, transparent 1.5px) 0 0 / 22px 22px;
  color: #fff;
  font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
}

.shell-nav {
  flex: none;
  width: 220px;
  background: #0e1013;
  border-right: 1px solid rgba(255, 255, 255, 0.08);
  padding: 24px 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.shell-nav__label {
  font: 700 15px/1 var(--font-mono);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #fff;
  padding: 0 8px 12px;
}

.shell-nav__project {
  margin-bottom: 12px;
  padding: 8px 10px;
  border-radius: var(--radius-notch-sm);
  background: #1b1f25;
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #fff;
  font: 500 12px system-ui;
}

.shell-nav__item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 8px;
  border-radius: 8px;
  color: rgba(255, 255, 255, 0.55);
  font: 500 13px system-ui;
  text-decoration: none;
}

.shell-nav__item--linkstyle {
  display: block;
}

.shell-nav__item--active {
  border-radius: 8px 8px 0 0;
  background: rgba(155, 138, 239, 0.18);
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
  color: rgba(255, 255, 255, 0.45);
  font: 500 12.5px system-ui;
  text-decoration: none;
}

.shell-nav__subitem--active {
  color: var(--accent);
  background: rgba(155, 138, 239, 0.12);
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
  background: #9b8aef;
  opacity: 1;
}

.shell-nav__account {
  margin-top: auto;
  padding: 10px 8px 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.shell-nav__email {
  font: 500 11px system-ui;
  color: rgba(255, 255, 255, 0.4);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.shell-nav__logout {
  font: 600 11.5px system-ui;
  color: #a5b4fc;
  cursor: pointer;
  width: fit-content;
}

.shell-nav__version {
  margin-top: auto;
  padding: 10px 8px 0;
  color: rgba(255, 255, 255, 0.3);
  font: 500 11px system-ui;
}

.shell-nav__account + .shell-nav__version {
  margin-top: 0;
}

.shell-main {
  flex: 1;
  min-width: 0;
  padding: 32px 40px 96px;
  box-sizing: border-box;
}

.shell-tabbar {
  display: none;
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  background: #0e1013;
}

.shell-tabbar__item {
  flex: 1;
  padding: 10px 0 12px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  color: rgba(255, 255, 255, 0.4);
  font: 500 10px system-ui;
  text-decoration: none;
}

.shell-tabbar__item--active {
  color: var(--accent);
  font-weight: 600;
}

.shell-tabbar__icon {
  width: 20px;
  height: 20px;
  border-radius: 5px;
  background: rgba(255, 255, 255, 0.15);
}

.shell-tabbar__icon--active {
  background: oklch(0.65 0.15 290);
}

@media (max-width: 860px) {
  .shell-nav {
    display: none;
  }
  .shell-tabbar {
    display: flex;
  }
  .shell-main {
    padding: 20px;
  }
}
</style>

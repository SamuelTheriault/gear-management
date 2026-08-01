import { ref } from 'vue'
import { api } from '../api/client'

/**
 * Authentification — session Django établie via Google OAuth (django-allauth
 * + dj-rest-auth, voir config/settings.py et security.md). Singleton comme
 * useActiveProject.js : un seul GET /api/auth/user/ par session SPA, dont le
 * résultat est réutilisé par le garde de route (router/index.js) ET par
 * AppShell.vue (affichage + bouton déconnexion).
 *
 * Le login lui-même n'est PAS un appel API — `/accounts/google/login/` est
 * une redirection pleine page (le flux OAuth "classique" décrit dans
 * config/settings.py : navigateur → Google → callback allauth → session
 * Django établie → redirection vers FRONTEND_URL). D'où `googleLoginUrl`,
 * un simple lien <a href>, pas un appel `api.*`.
 */

const currentUser = ref(null)
const loading = ref(false)
const checked = ref(false)

let checkPromise = null

async function checkAuth() {
  if (checkPromise) return checkPromise
  loading.value = true
  checkPromise = (async () => {
    try {
      currentUser.value = await api.get('/auth/user/')
    } catch {
      // 401/403 attendu si personne n'est connecté — pas une erreur à afficher.
      currentUser.value = null
    } finally {
      checked.value = true
      loading.value = false
    }
  })()
  return checkPromise
}

async function refreshAuth() {
  checkPromise = null
  checked.value = false
  await checkAuth()
}

async function logout() {
  try {
    await api.post('/auth/logout/', {})
  } catch {
    // Session déjà expirée côté serveur : pas bloquant, on nettoie quand même l'état local.
  }
  currentUser.value = null
  checked.value = true
  checkPromise = Promise.resolve()
}

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api'
// `/accounts/google/login/` (django-allauth) est monté à la racine Django,
// PAS sous `/api` — on retire donc ce suffixe de VITE_API_BASE_URL.
const ROOT_BASE = API_BASE.replace(/\/api\/?$/, '')
const googleLoginUrl = `${ROOT_BASE}/accounts/google/login/`

export function useAuth() {
  checkAuth()
  return { currentUser, loading, checked, checkAuth, refreshAuth, logout, googleLoginUrl }
}

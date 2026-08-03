import { ref, watch } from 'vue'

/**
 * Thème clair/sombre (2026-08-02, demande de Samuel : « une version claire du
 * visuel » + toggle en pied de sidebar). Singleton comme useAuth.js : un seul
 * état partagé par toute l'app, pas de ré-init par composant.
 *
 * Le thème n'est qu'un attribut `data-theme` sur `<html>` — tous les tokens
 * de couleur (`--accent`, `--bg-page`, `--fg-rgb`, etc., voir style.css)
 * changent de valeur via le sélecteur `:root[data-theme='light']`, aucune
 * classe ni style à gérer côté composants. Persisté dans localStorage ;
 * `index.html` porte un script anti-flash qui lit la même clé AVANT le
 * premier rendu Vue, pour ne jamais afficher un sombre-qui-devient-clair au
 * chargement.
 */

const STORAGE_KEY = 'registock-theme'

function readStored() {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    return v === 'light' || v === 'dark' ? v : null
  } catch {
    // localStorage indisponible (navigation privée stricte, etc.) — pas bloquant.
    return null
  }
}

const theme = ref(readStored() ?? 'dark')

function apply(value) {
  document.documentElement.setAttribute('data-theme', value)
}

apply(theme.value)

watch(theme, (value) => {
  apply(value)
  try {
    localStorage.setItem(STORAGE_KEY, value)
  } catch {
    // Idem : échec silencieux, le thème reste actif pour la session en cours.
  }
})

function setTheme(value) {
  theme.value = value === 'light' ? 'light' : 'dark'
}

function toggleTheme() {
  theme.value = theme.value === 'light' ? 'dark' : 'light'
}

export function useTheme() {
  return { theme, setTheme, toggleTheme }
}

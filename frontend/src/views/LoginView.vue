<script setup>
import { watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '../composables/useAuth'

/**
 * Écran de connexion — port de Login.dc.html.
 *
 * Le mockup montrait un simple bouton statique ; ici il pointe vers
 * `googleLoginUrl` (`/accounts/google/login/`, django-allauth — voir
 * useAuth.js), une redirection pleine page, pas un appel API. Si la personne
 * est déjà connectée (session existante) et atterrit ici quand même, on la
 * renvoie directement au tableau de bord plutôt que de lui remontrer ce
 * formulaire.
 *
 * Config requise côté backend pour que le bouton fonctionne réellement :
 * `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` dans `backend/.env` (vides par
 * défaut — voir CLAUDE.md, « reste à faire »). Sans ça, le clic redirige vers
 * Google mais échoue côté Google Cloud (identifiants manquants).
 */

const { currentUser, checked, googleLoginUrl } = useAuth()
const router = useRouter()

watch(
  [currentUser, checked],
  ([user, isChecked]) => {
    if (isChecked && user) router.replace('/')
  },
  { immediate: true },
)
</script>

<template>
  <div class="page">
    <div class="card">
      <div class="brand">
        <div class="brand__logo"><span class="brand__dot" /></div>
        <div class="brand__name">RégiStock</div>
        <div class="brand__tagline">Gestion de matériel de production</div>
      </div>

      <div class="panel">
        <div class="panel__prompt">Connecte-toi pour accéder à ton inventaire</div>
        <a :href="googleLoginUrl" class="google-btn">
          <svg width="18" height="18" viewBox="0 0 18 18"><circle cx="9" cy="9" r="9" fill="#4285F4" /></svg>
          Continuer avec Google
        </a>
        <div class="panel__footer">Accès réservé à l'équipe · usage interne</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background:
    var(--bg-page) radial-gradient(var(--border-card) 1px, transparent 1.5px) 0 0 / 22px 22px;
  font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
}

.card {
  width: 380px;
  max-width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 28px;
}

.brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.brand__logo {
  width: 48px;
  height: 48px;
  border-radius: var(--radius-notch-lg);
  background: oklch(0.65 0.15 290 / 0.25);
  display: flex;
  align-items: center;
  justify-content: center;
}

.brand__dot {
  width: 16px;
  height: 16px;
  border-radius: 2px;
  background: rgb(var(--accent-rgb));
  display: block;
}

.brand__name {
  font: 700 20px var(--font-mono);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgb(var(--fg-rgb));
}

.brand__tagline {
  font: 400 13px system-ui;
  color: rgba(var(--fg-rgb), 0.53);
  text-align: center;
}

.panel {
  width: 100%;
  box-sizing: border-box;
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: 0 14px 0 14px;
  padding: 28px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.panel__prompt {
  font: 600 13px system-ui;
  color: rgba(var(--fg-rgb), 0.68);
  text-align: center;
}

.google-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 12px 16px;
  border-radius: var(--radius-notch-sm);
  background: #fff;
  color: #1f1f1f;
  font: 600 13.5px system-ui;
  cursor: pointer;
  text-decoration: none;
}

.panel__footer {
  font: 400 11px system-ui;
  color: rgba(var(--fg-rgb), 0.38);
  text-align: center;
}
</style>

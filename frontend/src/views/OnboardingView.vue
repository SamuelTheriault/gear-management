<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api/client'
import { useActiveProject } from '../composables/useActiveProject'
import { useAuth } from '../composables/useAuth'

/**
 * Écran de bienvenue / onboarding (2026-08-04).
 *
 * Répond au bug (non-code) noté au backlog le 2026-08-03 : un compte
 * flambant neuf (aucun `Project`, donc aucun `ProjectMembership`) atterrissait
 * sur le Tableau de bord vide, et les formulaires d'ajout (Lieu, Technicien,
 * ...) échouaient en 400 en silence (`project` envoyé `null`) sans qu'aucun
 * indice explique pourquoi. Le backlog envisageait un simple bandeau ; après
 * discussion avec Samuel, décision d'un écran BLOQUANT à la place (voir le
 * garde `router/index.js` : toute route redirige ici tant qu'aucun projet
 * actif n'existe, et cette route redirige elle-même vers `/` dès qu'un
 * projet existe) — cohérent avec le ton « on lui pose les questions
 * nécessaires » de la demande initiale.
 *
 * Formulaire volontairement COMPLET dès cette première création (les 5
 * champs de `Project` — voir `ProjectSerializer`) plutôt que juste un nom :
 * mêmes champs, mêmes conversions (`toPayload`) que l'édition de fiche dans
 * `ProjetDetailView.vue`, pour ne pas inventer une deuxième logique de
 * validation qui pourrait diverger. Pas de composant partagé pour l'instant
 * (décision de Samuel, 2026-08-04) : Réglages garde sa création rapide
 * nom-seul telle quelle, ce formulaire-ci reste propre à l'onboarding — à
 * factoriser plus tard si un troisième endroit en a besoin.
 *
 * Pas d'AppShell ici : la sidebar pointe vers des écrans que le garde de
 * route renverrait de toute façon ici (aucun projet actif) — un aller-retour
 * déroutant plutôt qu'utile. Layout autonome façon LoginView.vue, avec juste
 * un pied de page compte/déconnexion pour ne pas piéger la personne.
 */

const router = useRouter()
const { refreshProjects, setActiveProject } = useActiveProject()
const { currentUser, logout } = useAuth()

const FIELDS = ['name', 'client_name', 'start_date', 'end_date', 'notes']

const draft = ref({ name: '', client_name: '', start_date: '', end_date: '', notes: '' })
const saving = ref(false)
const saveError = ref(null)
const fieldErrors = ref({})

const canSave = computed(() => draft.value.name.trim().length > 0 && !saving.value)

function applyApiError(e) {
  const data = e?.data
  if (data && typeof data === 'object' && !Array.isArray(data)) {
    const perField = {}
    for (const field of FIELDS) {
      if (data[field]) perField[field] = [].concat(data[field])[0]
    }
    fieldErrors.value = perField
    const global = data.detail ?? (data.non_field_errors ? [].concat(data.non_field_errors)[0] : null)
    saveError.value = global ?? (Object.keys(perField).length ? null : 'Impossible de créer le projet.')
  } else {
    fieldErrors.value = {}
    saveError.value = 'Impossible de créer le projet.'
  }
}

async function createProject() {
  if (!canSave.value) return
  saving.value = true
  saveError.value = null
  fieldErrors.value = {}
  try {
    const project = await api.post('/projects/', {
      name: draft.value.name.trim(),
      client_name: draft.value.client_name.trim(),
      // Champ vidé = pas de date, donc `null` et non la chaîne vide (même
      // convention que ProjetDetailView.vue).
      start_date: draft.value.start_date || null,
      end_date: draft.value.end_date || null,
      notes: draft.value.notes.trim(),
    })
    // Recharge la liste (voir useActiveProject.js) puis bascule dessus
    // explicitement : sinon le sélecteur resterait sur l'ancien
    // `activeProjectId` (null) jusqu'à la prochaine visite de AppShell.
    await refreshProjects()
    setActiveProject(project.id)
    router.push('/')
  } catch (e) {
    applyApiError(e)
  } finally {
    saving.value = false
  }
}

async function handleLogout() {
  await logout()
  router.push('/login')
}
</script>

<template>
  <div class="page">
    <div class="wrap">
      <div class="brand">
        <div class="brand__logo"><span class="brand__dot" /></div>
        <div class="brand__name">RégiStock</div>
        <div class="brand__tagline">Bienvenue — crée ton premier projet pour commencer</div>
      </div>

      <div class="panel">
        <p class="panel__intro">
          Un projet regroupe le matériel, les lieux, les techniciens et les
          spectacles d'une production précise (une compagnie, un musée, une
          biennale...) — rien n'est partagé entre deux projets. Tu pourras en
          créer d'autres plus tard depuis Réglages.
        </p>

        <div class="fiche-grid">
          <label class="fiche-field fiche-field--wide">
            <span class="fiche-label">Nom du projet</span>
            <input
              v-model="draft.name"
              class="fiche-input"
              :class="{ 'fiche-input--error': fieldErrors.name }"
              placeholder="ex. Furies 2026, Tournée Compagnie X…"
              @keyup.enter="createProject"
            />
            <span v-if="fieldErrors.name" class="fiche-error">{{ fieldErrors.name }}</span>
          </label>

          <label class="fiche-field">
            <span class="fiche-label">Client / compagnie</span>
            <input
              v-model="draft.client_name"
              class="fiche-input"
              :class="{ 'fiche-input--error': fieldErrors.client_name }"
              placeholder="Optionnel"
            />
            <span v-if="fieldErrors.client_name" class="fiche-error">{{ fieldErrors.client_name }}</span>
          </label>

          <div class="fiche-field" />

          <label class="fiche-field">
            <span class="fiche-label">Début</span>
            <input
              v-model="draft.start_date"
              type="date"
              class="fiche-input"
              :class="{ 'fiche-input--error': fieldErrors.start_date }"
            />
            <span v-if="fieldErrors.start_date" class="fiche-error">{{ fieldErrors.start_date }}</span>
          </label>

          <label class="fiche-field">
            <span class="fiche-label">Fin</span>
            <input
              v-model="draft.end_date"
              type="date"
              class="fiche-input"
              :class="{ 'fiche-input--error': fieldErrors.end_date }"
            />
            <span v-if="fieldErrors.end_date" class="fiche-error">{{ fieldErrors.end_date }}</span>
          </label>

          <label class="fiche-field fiche-field--full">
            <span class="fiche-label">Notes</span>
            <textarea v-model="draft.notes" rows="3" class="fiche-input fiche-input--area" placeholder="Optionnel" />
          </label>
        </div>

        <div class="fiche-hint">
          La date de fin sert de repère au contrôle de retour du matériel
          (écran Cohérence) une fois le projet en cours ; sans elle, l'app
          retient la fin du dernier événement.
        </div>
        <div v-if="saveError" class="fiche-error">{{ saveError }}</div>

        <button
          type="button"
          class="submit-btn"
          :class="{ 'submit-btn--disabled': !canSave }"
          @click="createProject"
        >
          {{ saving ? 'Création…' : 'Créer mon projet' }}
        </button>
      </div>

      <div v-if="currentUser" class="account">
        <span>Connecté comme {{ currentUser.email }}</span>
        <span class="account__sep">·</span>
        <span class="account__logout" @click="handleLogout">Se déconnecter</span>
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

.wrap {
  width: 560px;
  max-width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 24px;
}

.brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  text-align: center;
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
  color: rgba(var(--fg-rgb), 0.5);
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

.panel__intro {
  margin: 0;
  font: 400 13px/1.6 system-ui;
  color: rgba(var(--fg-rgb), 0.6);
}

.submit-btn {
  border: 0;
  padding: 12px 22px;
  border-radius: var(--radius-notch-sm);
  background: var(--accent);
  color: #0b0d10;
  font: 600 13.5px system-ui;
  cursor: pointer;
}

.submit-btn--disabled {
  background: rgba(var(--fg-rgb), 0.08);
  color: rgba(var(--fg-rgb), 0.3);
  cursor: not-allowed;
}

.account {
  font: 500 11.5px system-ui;
  color: rgba(var(--fg-rgb), 0.4);
  display: flex;
  align-items: center;
  gap: 6px;
}

.account__sep {
  opacity: 0.5;
}

.account__logout {
  color: var(--link);
  cursor: pointer;
}
</style>

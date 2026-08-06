<script setup>
import { ref, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppShell from '../components/AppShell.vue'
import { api } from '../api/client'
import { useFicheEdition } from '../composables/useFicheEdition'
import { useSuppressionFiche } from '../composables/useSuppressionFiche'
import { useActiveProject } from '../composables/useActiveProject'
import { useAuth } from '../composables/useAuth'
import { useEscapeKey } from '../composables/useEscapeKey'

/**
 * Fiche projet — nouvelle vue (2026-08-02, gestion des accès par projet),
 * même structure que LieuDetailView.vue : entête + bouton « Modifier la
 * fiche » (useFicheEdition), mode lecture en `.info-grid`, mode édition en
 * un seul PATCH.
 *
 * Remplace l'édition de dates EN LIGNE que faisait ReglagesView.vue
 * (`draftDates`/`saveProjectDates`, retirée à cette occasion) — elle vit
 * maintenant ici, aux côtés du nom/client/statut/notes, plutôt qu'à deux
 * endroits.
 *
 * Carte « Membres » : consomme /api/project-memberships/?project=<id>
 * (voir ProjectMembershipViewSet, backend/inventory/views.py). Lecture
 * accessible à tout membre actif ; gestion (inviter/changer un rôle/
 * retirer) réservée à `canManage` — staff global (`currentUser.
 * is_staff_global`, exposé par CurrentUserDetailsSerializer depuis le
 * 2026-08-02) ou owner actif de CE projet. Le backend refuse (400) de
 * retirer/rétrograder le dernier owner actif — le message d'erreur brut du
 * serveur est affiché tel quel, pas deviné côté Vue.
 *
 * Suppression de projet (2026-08-04, demande de Samuel) : autorisée en
 * cascade — supprimer un projet efface toute la production (lieux, matériel,
 * techniciens, spectacles, transports ; voir `Project.deletion_impact` et la
 * note dédiée dans `models.py`, migration `0025_project_cascade_delete`).
 * Friction volontairement plus élevée que Lieu/Spectacle/Transport/Matériel/
 * Technicien (choix explicite de Samuel, `AskUserQuestion`) : il faut taper
 * le nom exact du projet pour activer le bouton « Supprimer », comme la
 * suppression d'un dépôt GitHub — pas le simple 2-bouton `useSuppressionFiche`
 * partagé ailleurs. `askDelete`/`cancelDelete`/`confirmDelete` restent
 * réutilisés tels quels (état async + appel API), seule la validation
 * d'activation du bouton est locale à cette fiche.
 *
 * Bug corrigé le jour même (signalé par Samuel) : le nom à retaper était
 * affiché via `.fiche-label`, qui force `text-transform: uppercase` — le
 * texte à l'écran ne correspondait donc plus à `project.name` (comparaison
 * sensible à la casse), impossible à retaper correctement. Le nom exact vit
 * maintenant dans `.fiche-confirm__literal` (style.css), sans transformation
 * de casse et en `white-space: pre-wrap` pour que des espaces internes
 * multiples (ex. « Projet  test », deux espaces) restent visibles au lieu
 * d'être fondus par le rendu HTML par défaut — ce que l'écran montre est
 * maintenant exactement ce qu'il faut taper.
 */

const route = useRoute()
const { refreshProjects } = useActiveProject()
const { currentUser } = useAuth()

const project = ref(null)
const memberships = ref([])
const loading = ref(false)
const loadError = ref(null)

const dateFmt = new Intl.DateTimeFormat('fr-CA', { day: 'numeric', month: 'short', year: 'numeric' })

async function loadAll() {
  const id = route.params.id
  loading.value = true
  loadError.value = null
  try {
    const [proj, memRaw] = await Promise.all([
      api.get(`/projects/${id}/`),
      api.get('/project-memberships/', { project: id }),
    ])
    project.value = proj
    memberships.value = Array.isArray(memRaw) ? memRaw : (memRaw.results ?? [])
  } catch (e) {
    loadError.value = e
  } finally {
    loading.value = false
  }
}

watch(() => route.params.id, loadAll, { immediate: true })

const statusLabel = computed(() => (project.value?.status === 'archived' ? 'Archivé' : 'Actif'))

// --- Édition de la fiche ---
// `client_name`/`status`/`start_date`/`end_date`/`notes` correspondent
// exactement aux champs exposés par ProjectSerializer (voir serializers.py).

const {
  editing, draft, saving, saveError, fieldErrors, canSave,
  startEdit, cancelEdit, save: saveProject,
} = useFicheEdition({
  entity: project,
  endpoint: '/projects',
  fields: ['name', 'client_name', 'status', 'start_date', 'end_date', 'notes'],
  errorMessage: 'Impossible d’enregistrer le projet.',
  toDraft: (p) => ({
    name: p.name ?? '',
    client_name: p.client_name ?? '',
    status: p.status ?? 'active',
    start_date: p.start_date ?? '',
    end_date: p.end_date ?? '',
    notes: p.notes ?? '',
  }),
  isValid: (d) => d.name.trim().length > 0,
  toPayload: (d) => ({
    name: d.name.trim(),
    client_name: d.client_name.trim(),
    status: d.status,
    // Champ vidé = pas de date, donc `null` et non la chaîne vide.
    start_date: d.start_date || null,
    end_date: d.end_date || null,
    notes: d.notes.trim(),
  }),
})

async function save() {
  const ok = await saveProject()
  // Le sélecteur de projet (AppShell.vue) doit refléter un renommage ou un
  // archivage immédiatement — useActiveProject.projects ne filtre que les
  // projets 'active', un passage à 'archived' doit donc le faire disparaître.
  if (ok) await refreshProjects()
}

// Changer de projet sans quitter la vue ne doit pas garder un formulaire à
// moitié rempli sur le projet précédent.
watch(() => route.params.id, cancelEdit)

// --- Suppression (2026-08-04) ---
// Friction élevée, volontaire : le bouton « Supprimer » ne s'active qu'une
// fois le nom du projet retapé exactement (même geste que la suppression
// d'un dépôt GitHub) — supprimer un projet efface toute la production, pas
// seulement une fiche. `deletion_impact` (voir ProjectSerializer) est
// toujours annoncé, cascade ou non : contrairement à Matériel/Technicien, il
// n'y a jamais rien à « ne pas casser », donc pas de `hasCascade` à calculer.
const {
  confirming, deleting, deleteError, askDelete: askDeleteProject, cancelDelete: cancelDeleteProject, confirmDelete,
} = useSuppressionFiche({ endpoint: '/projects', redirectTo: '/reglages' })

const deleteConfirmText = ref('')

function askDelete() {
  deleteConfirmText.value = ''
  askDeleteProject()
}

function cancelDelete() {
  deleteConfirmText.value = ''
  cancelDeleteProject()
}

const deletionImpact = computed(() => project.value?.deletion_impact ?? null)
const canConfirmDelete = computed(
  () => !!project.value && deleteConfirmText.value.trim() === project.value.name,
)

// `confirmDelete` navigue déjà vers `/reglages` en cas de succès — mais le
// sélecteur de projet actif (AppShell.vue) doit aussi être averti, exactement
// comme après un archivage (`save()` ci-dessus) : `refreshProjects()`
// revalide `activeProjectId` et bascule sur un autre projet actif si celui
// qu'on vient de supprimer était sélectionné. `deleteError` reste `null`
// seulement en cas de succès (voir useSuppressionFiche), d'où le test après
// l'attente plutôt qu'une valeur de retour.
async function deleteProject() {
  await confirmDelete(project.value.id)
  if (!deleteError.value) await refreshProjects()
}

// --- Membres (accès par projet) ---

const roleLabels = { owner: 'Propriétaire', editor: 'Éditeur', viewer: 'Lecteur' }

const canManage = computed(() => {
  if (!currentUser.value) return false
  if (currentUser.value.is_staff_global) return true
  const email = currentUser.value.email
  return memberships.value.some(
    (m) => m.user_email === email && m.role === 'owner' && m.status === 'active',
  )
})

const decoratedMemberships = computed(() =>
  memberships.value.map((m) => ({
    ...m,
    roleLabel: roleLabels[m.role] ?? m.role,
  })),
)

const roleErrors = ref({})

async function changeRole(m, role) {
  if (m.role === role) return
  roleErrors.value = { ...roleErrors.value, [m.id]: null }
  try {
    const updated = await api.patch(`/project-memberships/${m.id}/`, { role })
    const idx = memberships.value.findIndex((x) => x.id === m.id)
    if (idx !== -1) memberships.value[idx] = updated
  } catch (e) {
    roleErrors.value = { ...roleErrors.value, [m.id]: e.data?.detail ?? 'Impossible de changer le rôle.' }
  }
}

// Retrait d'accès — confirmation inline, même gabarit que la suppression de
// fiche (`.fiche-confirm-backdrop`/`.fiche-confirm`, déjà globales).
const removeTarget = ref(null)
const removing = ref(false)
const removeError = ref(null)

function askRemove(m) {
  removeTarget.value = m
  removeError.value = null
}

function cancelRemove() {
  removeTarget.value = null
  removeError.value = null
}

useEscapeKey(() => {
  if (removeTarget.value) cancelRemove()
})

async function confirmRemove() {
  if (!removeTarget.value) return
  removing.value = true
  removeError.value = null
  try {
    await api.delete(`/project-memberships/${removeTarget.value.id}/`)
    memberships.value = memberships.value.filter((m) => m.id !== removeTarget.value.id)
    removeTarget.value = null
  } catch (e) {
    removeError.value = e.data?.detail ?? "Impossible de retirer cet accès."
  } finally {
    removing.value = false
  }
}

// --- Invitation ---

const inviteEmail = ref('')
const inviteRole = ref('viewer')
const inviteError = ref(null)
const inviting = ref(false)

const canInvite = computed(() => inviteEmail.value.trim().length > 0)

async function invite() {
  const email = inviteEmail.value.trim()
  if (!email) {
    inviteError.value = 'Courriel requis.'
    return
  }
  inviteError.value = null
  inviting.value = true
  try {
    const created = await api.post('/project-memberships/', {
      project: project.value.id,
      email,
      role: inviteRole.value,
    })
    memberships.value = [...memberships.value, created]
    inviteEmail.value = ''
    inviteRole.value = 'viewer'
  } catch (e) {
    inviteError.value = e.data?.email?.[0] ?? e.data?.detail ?? "Impossible d'inviter cette personne."
  } finally {
    inviting.value = false
  }
}
</script>

<template>
  <AppShell>
    <div v-if="loading" class="hint">Chargement…</div>
    <div v-else-if="loadError" class="hint hint--error">
      Impossible de charger ce projet. Es-tu connecté (session Django) ?
    </div>

    <div v-else-if="project" class="page">
      <div class="breadcrumb"><RouterLink to="/reglages">Réglages</RouterLink> / {{ project.name }}</div>

      <div class="header">
        <h1 class="header__title">{{ project.name }}</h1>
        <div class="header__tag" :style="project.status === 'archived'
          ? { color: 'rgba(var(--fg-rgb),.6)', background: 'rgba(var(--fg-rgb),.08)' }
          : { color: 'oklch(0.72 0.13 165)', background: 'oklch(0.72 0.13 165 / .16)' }">
          {{ statusLabel }}
        </div>
        <div class="fiche-actions">
          <button v-if="!editing" type="button" class="fiche-btn" @click="startEdit">
            Modifier la fiche
          </button>
          <template v-else>
            <button
              type="button"
              class="fiche-btn fiche-btn--primary"
              :disabled="!canSave"
              @click="save()"
            >
              {{ saving ? 'Enregistrement…' : 'Enregistrer' }}
            </button>
            <button type="button" class="fiche-btn" :disabled="saving" @click="cancelEdit">
              Annuler
            </button>
          </template>
        </div>
      </div>

      <!-- Mode lecture -->
      <div v-if="!editing" class="card info-grid">
        <div>
          <div class="info-label">Client</div>
          <div class="info-value">{{ project.client_name || '—' }}</div>
        </div>
        <div>
          <div class="info-label">Statut</div>
          <div class="info-value">{{ statusLabel }}</div>
        </div>
        <div>
          <div class="info-label">Début</div>
          <div class="info-value">{{ project.start_date ? dateFmt.format(new Date(`${project.start_date}T00:00:00`)) : '—' }}</div>
        </div>
        <div>
          <div class="info-label">Fin</div>
          <div class="info-value">{{ project.end_date ? dateFmt.format(new Date(`${project.end_date}T00:00:00`)) : '—' }}</div>
        </div>
        <div>
          <div class="info-label">Créé le</div>
          <div class="info-value">{{ project.created_at ? dateFmt.format(new Date(project.created_at)) : '—' }}</div>
        </div>
      </div>

      <!-- Mode édition : un seul PATCH à l'enregistrement -->
      <div v-else class="fiche-edit-card">
        <div class="fiche-grid">
          <label class="fiche-field fiche-field--wide">
            <span class="fiche-label">Nom du projet</span>
            <input v-model="draft.name" class="fiche-input" :class="{ 'fiche-input--error': fieldErrors.name }" />
            <span v-if="fieldErrors.name" class="fiche-error">{{ fieldErrors.name }}</span>
          </label>

          <label class="fiche-field">
            <span class="fiche-label">Client</span>
            <input v-model="draft.client_name" class="fiche-input" :class="{ 'fiche-input--error': fieldErrors.client_name }" />
            <span v-if="fieldErrors.client_name" class="fiche-error">{{ fieldErrors.client_name }}</span>
          </label>

          <label class="fiche-field">
            <span class="fiche-label">Statut</span>
            <select v-model="draft.status" class="fiche-input">
              <option value="active">Actif</option>
              <option value="archived">Archivé</option>
            </select>
          </label>

          <label class="fiche-field">
            <span class="fiche-label">Début</span>
            <input v-model="draft.start_date" type="date" class="fiche-input" :class="{ 'fiche-input--error': fieldErrors.start_date }" />
            <span v-if="fieldErrors.start_date" class="fiche-error">{{ fieldErrors.start_date }}</span>
          </label>

          <label class="fiche-field">
            <span class="fiche-label">Fin</span>
            <input v-model="draft.end_date" type="date" class="fiche-input" :class="{ 'fiche-input--error': fieldErrors.end_date }" />
            <span v-if="fieldErrors.end_date" class="fiche-error">{{ fieldErrors.end_date }}</span>
          </label>

          <label class="fiche-field fiche-field--full">
            <span class="fiche-label">Notes</span>
            <textarea v-model="draft.notes" rows="3" class="fiche-input fiche-input--area" />
          </label>
        </div>

        <div class="fiche-hint">
          La date de fin sert de repère au contrôle de retour du matériel
          (écran Cohérence) ; sans elle, l'app retient la fin du dernier
          événement. Archiver un projet le retire du sélecteur de projet actif.
        </div>
        <div v-if="!draft.name.trim()" class="fiche-error">Le nom du projet est requis.</div>
        <div v-if="saveError" class="fiche-error">{{ saveError }}</div>

        <div class="fiche-danger">
          <div class="fiche-danger__hint">
            Supprimer ce projet efface aussi tout ce qui lui appartient — lieux,
            matériel, techniciens, spectacles, transports. Irréversible.
          </div>
          <button type="button" class="fiche-btn fiche-btn--danger" @click="askDelete">
            Supprimer ce projet
          </button>
        </div>
      </div>

      <div v-if="confirming" class="fiche-confirm-backdrop" @click.self="cancelDelete">
        <div class="fiche-confirm">
          <div class="fiche-confirm__title">Supprimer « {{ project.name }} » ?</div>
          <p class="fiche-confirm__text">
            Cette action est définitive et efface toute la production.
          </p>
          <ul v-if="deletionImpact" class="fiche-confirm__list">
            <li v-if="deletionImpact.venues > 0">{{ deletionImpact.venues }} lieu(x)</li>
            <li v-if="deletionImpact.materials > 0">{{ deletionImpact.materials }} matériel(s)</li>
            <li v-if="deletionImpact.technicians > 0">{{ deletionImpact.technicians }} technicien(s)</li>
            <li v-if="deletionImpact.shows > 0">{{ deletionImpact.shows }} spectacle(s)</li>
            <li v-if="deletionImpact.transports > 0">{{ deletionImpact.transports }} transport(s)</li>
          </ul>
          <div class="fiche-field fiche-field--full">
            <p class="fiche-confirm__text">
              Pour confirmer, tape exactement :
              <span class="fiche-confirm__literal">{{ project.name }}</span>
            </p>
            <input
              v-model="deleteConfirmText"
              class="fiche-input"
              autocomplete="off"
              spellcheck="false"
              :aria-label="`Retape « ${project.name} » pour confirmer`"
              @keyup.enter="canConfirmDelete && !deleting && deleteProject()"
            />
          </div>
          <div v-if="deleteError" class="fiche-error">{{ deleteError }}</div>
          <div class="fiche-confirm__actions">
            <button type="button" class="fiche-btn" :disabled="deleting" @click="cancelDelete">
              Annuler
            </button>
            <button
              type="button"
              class="fiche-btn fiche-btn--danger"
              :disabled="deleting || !canConfirmDelete"
              @click="deleteProject"
            >
              {{ deleting ? 'Suppression…' : 'Supprimer' }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="!editing && project.notes" class="card">
        <div class="card-title">Notes</div>
        <div class="card-text">{{ project.notes }}</div>
      </div>

      <!-- Membres (accès par projet, 2026-08-02) -->
      <div class="card">
        <div class="card-title" style="margin-bottom: 14px">Membres</div>

        <div v-if="decoratedMemberships.length > 0" class="row-list">
          <div v-for="m in decoratedMemberships" :key="m.id" class="row">
            <div class="row__body">
              <div class="row__title">{{ m.user_name || m.user_email }}</div>
              <div class="row__subtitle">{{ m.user_email }}</div>
              <div v-if="roleErrors[m.id]" class="fiche-error">{{ roleErrors[m.id] }}</div>
            </div>
            <div v-if="m.status === 'pending'" class="pending-badge">
              En attente — s'active à la prochaine connexion Google de cette personne
            </div>
            <template v-if="canManage">
              <select class="fiche-input role-select" :value="m.role" @change="changeRole(m, $event.target.value)">
                <option value="owner">Propriétaire</option>
                <option value="editor">Éditeur</option>
                <option value="viewer">Lecteur</option>
              </select>
              <button type="button" class="fiche-btn fiche-btn--danger" @click="askRemove(m)">
                Retirer l'accès
              </button>
            </template>
            <div v-else class="role-badge">{{ m.roleLabel }}</div>
          </div>
        </div>
        <div v-else class="row-empty">Aucun membre pour l'instant.</div>

        <div v-if="canManage" class="invite-card">
          <div class="invite-title">Inviter</div>
          <div class="invite-row">
            <input v-model="inviteEmail" placeholder="Courriel" class="fiche-input invite-input" @keyup.enter="canInvite && !inviting && invite()" />
            <select v-model="inviteRole" class="fiche-input invite-role">
              <option value="viewer">Lecteur</option>
              <option value="editor">Éditeur</option>
              <option value="owner">Propriétaire</option>
            </select>
            <button
              type="button"
              class="fiche-btn fiche-btn--primary"
              :disabled="!canInvite || inviting"
              @click="invite"
            >
              {{ inviting ? 'Envoi…' : '+ Inviter' }}
            </button>
          </div>
          <div v-if="inviteError" class="fiche-error">{{ inviteError }}</div>
        </div>
      </div>

      <div v-if="removeTarget" class="fiche-confirm-backdrop" @click.self="cancelRemove">
        <div class="fiche-confirm">
          <div class="fiche-confirm__title">Retirer l'accès de « {{ removeTarget.user_name || removeTarget.user_email }} » ?</div>
          <p class="fiche-confirm__text">
            Cette personne perdra immédiatement l'accès à ce projet.
          </p>
          <div v-if="removeError" class="fiche-error">{{ removeError }}</div>
          <div class="fiche-confirm__actions">
            <button type="button" class="fiche-btn" :disabled="removing" @click="cancelRemove">
              Annuler
            </button>
            <button
              type="button"
              class="fiche-btn fiche-btn--danger"
              :disabled="removing"
              @click="confirmRemove"
            >
              {{ removing ? 'Retrait…' : 'Retirer' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </AppShell>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 20px;
  max-width: 820px;
}

.hint {
  padding: 32px 40px;
  font: 500 13px system-ui;
  color: rgba(var(--fg-rgb), 0.58);
}

.hint--error {
  color: oklch(0.78 0.16 35);
}

.breadcrumb {
  font: 500 12px system-ui;
  color: rgba(var(--fg-rgb), 0.48);
}

.breadcrumb :deep(a) {
  color: var(--link);
  text-decoration: none;
}

.header {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.header__tag {
  font: 700 10px system-ui;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 3px 9px;
  border-radius: 0 6px 0 6px;
}

.card {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-notch-lg);
  padding: 20px;
}

.info-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
}

@media (max-width: 640px) {
  .info-grid {
    grid-template-columns: 1fr;
  }
}

.info-label {
  font: 700 11px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: rgba(var(--fg-rgb), 0.53);
}

.info-value {
  font: 500 14px system-ui;
  color: rgb(var(--fg-rgb));
  margin-top: 4px;
}


.card-text {
  font: 400 13.5px/1.6 system-ui;
  color: rgba(var(--fg-rgb), 0.75);
  margin-top: 14px;
}

.row-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: var(--radius-notch-sm);
  background: var(--bg-row);
  flex-wrap: wrap;
}

.row__body {
  flex: 1;
  min-width: 160px;
}

.row__title {
  font: 600 13px system-ui;
  color: rgb(var(--fg-rgb));
}

.row__subtitle {
  font: 400 11.5px system-ui;
  color: rgba(var(--fg-rgb), 0.58);
}

.row-empty {
  font: 500 12.5px system-ui;
  color: rgba(var(--fg-rgb), 0.48);
  padding: 10px 12px;
}

.pending-badge {
  font: 600 10.5px system-ui;
  color: oklch(0.78 0.14 75);
  background: oklch(0.5 0.14 75 / 0.18);
  padding: 4px 9px;
  border-radius: 0 8px 0 8px;
  max-width: 240px;
  line-height: 1.4;
}

.role-select {
  width: auto;
  min-width: 140px;
  flex: none;
}

.role-badge {
  font: 700 10px system-ui;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 4px 9px;
  border-radius: 0 6px 0 6px;
  color: rgba(var(--fg-rgb), 0.68);
  background: rgba(var(--fg-rgb), 0.08);
  flex: none;
}

.invite-card {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--border-card);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.invite-title {
  font: 700 10.5px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: rgba(var(--fg-rgb), 0.48);
}

.invite-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
}

.invite-input {
  flex: 2;
  min-width: 200px;
  width: auto;
}

.invite-role {
  flex: 1;
  min-width: 140px;
  width: auto;
}
</style>

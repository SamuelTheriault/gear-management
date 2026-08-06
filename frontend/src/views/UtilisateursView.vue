<script setup>
import { ref, computed, onMounted } from 'vue'
import AppShell from '../components/AppShell.vue'
import { api } from '../api/client'
import { useEscapeKey } from '../composables/useEscapeKey'

/**
 * Écran « Utilisateurs » — port de Utilisateurs.dc.html.
 *
 * Branché sur GET/POST/PATCH/DELETE /api/users/ (voir UserSerializer,
 * serializers.py — champs id/email/name/role/created_at ; `role` réel côté
 * backend est 'admin'/'viewer', le mockup utilisait 'lecture' en interne —
 * on garde 'viewer' pour matcher l'API, seul le libellé affiché change).
 *
 * Le formulaire « Ajouter un utilisateur » n'est pas cosmétique : il
 * correspond à un vrai flux de pré-provisioning (voir signals.py,
 * `provisionner_utilisateur_inventory`) — créer un `User` par email ici
 * AVANT que la personne se connecte via Google fait qu'à son premier login,
 * le compte allauth se lie à cette fiche existante et conserve le rôle déjà
 * assigné, au lieu d'être créé avec le rôle par défaut (`viewer`).
 */

const loading = ref(false)
const loadError = ref(null)
const users = ref([])

const roleMeta = {
  admin: { label: 'Admin', color: 'oklch(0.65 0.15 290)', bg: 'oklch(0.65 0.15 290 / .2)' },
  viewer: { label: 'Lecture seule', color: 'rgba(var(--fg-rgb),.6)', bg: 'rgba(var(--fg-rgb),.08)' },
}

async function loadUsers() {
  loading.value = true
  loadError.value = null
  try {
    const data = await api.get('/users/')
    users.value = Array.isArray(data) ? data : (data.results ?? [])
  } catch (e) {
    loadError.value = e
  } finally {
    loading.value = false
  }
}

onMounted(loadUsers)

const dateFmt = new Intl.DateTimeFormat('fr-CA', { day: 'numeric', month: 'short', year: 'numeric' })

function initials(name) {
  return (name || '?')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join('')
}

const decoratedUsers = computed(() =>
  users.value.map((u) => ({
    ...u,
    initials: initials(u.name),
    createdAtLabel: u.created_at ? dateFmt.format(new Date(u.created_at)) : '—',
    roleLabel: roleMeta[u.role]?.label ?? u.role,
    roleColor: roleMeta[u.role]?.color ?? 'rgba(var(--fg-rgb),.6)',
    roleBg: roleMeta[u.role]?.bg ?? 'rgba(var(--fg-rgb),.08)',
  })),
)

async function setRole(user, role) {
  if (user.role === role) return
  try {
    const updated = await api.patch(`/users/${user.id}/`, { role })
    const idx = users.value.findIndex((u) => u.id === user.id)
    if (idx !== -1) users.value[idx] = updated
  } catch {
    // Pas de retour visuel dédié pour l'instant — un échec ici (ex. perte de
    // session) sera de toute façon visible au prochain rechargement de page.
  }
}

// --- Retrait d'accès (modale de confirmation) ---

const confirmTarget = ref(null)

function askRemove(user) {
  confirmTarget.value = user
}

function cancelRemove() {
  confirmTarget.value = null
}

// Échap ferme la confirmation, même geste que le clic sur le fond.
useEscapeKey(() => {
  if (confirmTarget.value) cancelRemove()
})

async function confirmRemove() {
  if (!confirmTarget.value) return
  try {
    await api.delete(`/users/${confirmTarget.value.id}/`)
    users.value = users.value.filter((u) => u.id !== confirmTarget.value.id)
  } finally {
    confirmTarget.value = null
  }
}

// --- Ajout (pré-provisioning) ---

const newName = ref('')
const newEmail = ref('')
const newRole = ref('viewer')
const newUserError = ref(null)
const adding = ref(false)

const canAdd = computed(() => newName.value.trim().length > 0 && newEmail.value.trim().length > 0)

async function addUser() {
  const name = newName.value.trim()
  const email = newEmail.value.trim()
  if (!name || !email) {
    newUserError.value = 'Nom et courriel requis.'
    return
  }
  if (!email.includes('@')) {
    newUserError.value = 'Courriel invalide.'
    return
  }
  newUserError.value = null
  adding.value = true
  try {
    const created = await api.post('/users/', { name, email, role: newRole.value })
    users.value = [...users.value, created]
    newName.value = ''
    newEmail.value = ''
    newRole.value = 'viewer'
  } catch (e) {
    newUserError.value = e.data?.email?.[0] ?? e.data?.detail ?? "Impossible d'ajouter cet utilisateur."
  } finally {
    adding.value = false
  }
}
</script>

<template>
  <AppShell>
    <div class="page">
      <div class="header">
        <h1 class="page-title">Utilisateurs</h1>
        <div class="count" v-if="!loading">{{ users.length }} compte{{ users.length > 1 ? 's' : '' }}</div>
      </div>

      <div class="banner">
        Les comptes sont créés automatiquement à la première connexion Google. Cette page sert à gérer leurs droits d'accès.
      </div>

      <div v-if="loading" class="hint">Chargement…</div>
      <div v-else-if="loadError" class="hint hint--error">
        Impossible de charger les utilisateurs. Es-tu connecté (session Django) ?
      </div>

      <template v-else>
        <div v-if="decoratedUsers.length" class="user-list">
          <div v-for="u in decoratedUsers" :key="u.id" class="user-row">
            <div class="avatar">{{ u.initials }}</div>
            <div class="identity">
              <div class="name">{{ u.name }}</div>
              <div class="email">{{ u.email }}</div>
            </div>
            <div class="since">Depuis {{ u.createdAtLabel }}</div>
            <div class="role-badge" :style="{ color: u.roleColor, background: u.roleBg }">{{ u.roleLabel }}</div>
            <div class="role-toggle">
              <div
                class="role-toggle__opt"
                :class="{ 'role-toggle__opt--active-admin': u.role === 'admin' }"
                @click="setRole(u, 'admin')"
              >
                Admin
              </div>
              <div
                class="role-toggle__opt"
                :class="{ 'role-toggle__opt--active-viewer': u.role === 'viewer' }"
                @click="setRole(u, 'viewer')"
              >
                Lecture seule
              </div>
            </div>
            <div class="remove" @click="askRemove(u)">Retirer l'accès</div>
          </div>
        </div>

        <div v-else class="empty-card">
          <div class="empty-title">Aucun utilisateur pour l'instant</div>
          <div class="empty-subtitle">Les comptes apparaîtront ici dès qu'une personne se connecte avec Google.</div>
        </div>

        <div class="create-card">
          <div class="create-title">Ajouter un utilisateur</div>
          <div class="create-row">
            <input v-model="newName" placeholder="Nom complet" class="input input--wide" />
            <input v-model="newEmail" placeholder="Courriel" class="input input--wide" />
            <select v-model="newRole" class="input input--role">
              <option value="viewer">Lecture seule</option>
              <option value="admin">Admin</option>
            </select>
            <div class="btn" :class="canAdd && !adding ? 'btn--enabled' : 'btn--disabled'" @click="canAdd && !adding && addUser()">
              + Ajouter
            </div>
          </div>
          <div v-if="newUserError" class="error">{{ newUserError }}</div>
        </div>
      </template>
    </div>

    <div v-if="confirmTarget" class="modal-overlay" @click.self="cancelRemove">
      <div class="modal">
        <div class="modal__title">Retirer l'accès ?</div>
        <div class="modal__body">{{ confirmTarget.name }} ({{ confirmTarget.email }}) perdra immédiatement l'accès à l'application.</div>
        <div class="modal__footer">
          <div class="modal__cancel" @click="cancelRemove">Annuler</div>
          <div class="modal__confirm" @click="confirmRemove">Retirer l'accès</div>
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
  max-width: 920px;
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.count {
  font: 500 12px system-ui;
  color: rgba(var(--fg-rgb), 0.48);
}

.banner {
  background: rgba(var(--accent-rgb), 0.1);
  border: 1px solid rgba(var(--accent-rgb), 0.25);
  border-radius: 0 10px 0 10px;
  padding: 12px 16px;
  font: 400 12.5px system-ui;
  color: rgba(var(--fg-rgb), 0.68);
  line-height: 1.5;
}

.hint {
  padding: 32px 40px;
  font: 500 13px system-ui;
  color: rgba(var(--fg-rgb), 0.58);
}

.hint--error {
  color: oklch(0.78 0.16 35);
}

.user-list {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-notch-lg);
  padding: 8px;
}

.user-row {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 12px;
  border-bottom: 1px solid rgba(var(--fg-rgb), 0.05);
  flex-wrap: wrap;
}

.user-row:last-child {
  border-bottom: none;
}

.avatar {
  width: 34px;
  height: 34px;
  border-radius: var(--radius-notch-sm);
  background: oklch(0.65 0.15 290 / 0.2);
  color: var(--accent);
  display: flex;
  align-items: center;
  justify-content: center;
  font: 700 12px system-ui;
  flex: none;
}

.identity {
  flex: 1 1 220px;
  min-width: 220px;
}

.name {
  font: 600 13.5px system-ui;
  color: rgb(var(--fg-rgb));
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.email {
  font: 400 11.5px system-ui;
  color: rgba(var(--fg-rgb), 0.48);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.since {
  font: 400 11.5px system-ui;
  color: rgba(var(--fg-rgb), 0.43);
  white-space: nowrap;
  flex: none;
}

.role-badge {
  font: 700 10px system-ui;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 3px 9px;
  border-radius: 0 6px 0 6px;
  flex: none;
}

.role-toggle {
  display: flex;
  border: 1px solid rgba(var(--fg-rgb), 0.1);
  border-radius: var(--radius-notch-sm);
  overflow: hidden;
  flex: none;
}

.role-toggle__opt {
  padding: 7px 12px;
  font: 600 11.5px system-ui;
  cursor: pointer;
  color: rgba(var(--fg-rgb), 0.53);
  background: transparent;
}

.role-toggle__opt--active-admin {
  background: rgba(var(--accent-rgb), 0.22);
  color: var(--accent);
}

.role-toggle__opt--active-viewer {
  background: rgba(var(--fg-rgb), 0.14);
  color: rgb(var(--fg-rgb));
}

.remove {
  font: 600 11px system-ui;
  color: oklch(0.75 0.16 35);
  cursor: pointer;
  white-space: nowrap;
  flex: none;
}

.empty-card {
  background: var(--bg-card);
  border: 1px dashed rgba(var(--fg-rgb), 0.15);
  border-radius: var(--radius-notch-lg);
  padding: 40px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  text-align: center;
}

.empty-title {
  font: 600 14px system-ui;
  color: rgba(var(--fg-rgb), 0.68);
}

.empty-subtitle {
  font: 400 12.5px system-ui;
  color: rgba(var(--fg-rgb), 0.48);
  max-width: 340px;
}

.create-card {
  background: var(--bg-card);
  border: 1px dashed rgba(var(--fg-rgb), 0.15);
  border-radius: var(--radius-notch-lg);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.create-title {
  font: 700 10.5px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: rgba(var(--fg-rgb), 0.48);
}

.create-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
}

.input {
  box-sizing: border-box;
  padding: 10px 12px;
  border-radius: var(--radius-notch-sm);
  background: var(--bg-row);
  border: 1px solid rgba(var(--fg-rgb), 0.1);
  color: rgb(var(--fg-rgb));
  font: 500 13px system-ui;
}

.input--wide {
  flex: 2;
  min-width: 180px;
}

.input--role {
  flex: 1;
  min-width: 140px;
}

.btn {
  font: 600 12px system-ui;
  padding: 10px 18px;
  border-radius: var(--radius-notch-sm);
  cursor: pointer;
  white-space: nowrap;
}

.btn--enabled {
  color: rgb(var(--fg-rgb));
  background: oklch(0.65 0.15 290 / 0.3);
}

.btn--disabled {
  color: rgba(var(--fg-rgb), 0.38);
  background: rgba(var(--fg-rgb), 0.06);
  cursor: default;
}

.error {
  font: 500 11.5px system-ui;
  color: oklch(0.75 0.16 35);
}

.modal {
  width: 380px;
  max-width: 100%;
  background: var(--bg-card);
  border: 1px solid rgba(var(--fg-rgb), 0.1);
  border-radius: 0 14px 0 14px;
  padding: 22px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.modal__title {
  font: 700 15px system-ui;
  color: rgb(var(--fg-rgb));
}

.modal__body {
  font: 400 13px system-ui;
  color: rgba(var(--fg-rgb), 0.63);
  line-height: 1.5;
}

.modal__footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.modal__cancel {
  font: 600 12.5px system-ui;
  color: rgba(var(--fg-rgb), 0.68);
  padding: 10px 16px;
  border-radius: var(--radius-notch-sm);
  cursor: pointer;
}

.modal__confirm {
  font: 600 12.5px system-ui;
  color: rgb(var(--fg-rgb));
  background: oklch(0.6 0.18 30);
  padding: 10px 16px;
  border-radius: var(--radius-notch-sm);
  cursor: pointer;
}
</style>

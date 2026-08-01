<script setup>
import { ref, computed, watch } from 'vue'
import { api } from '../api/client'
import AppShell from '../components/AppShell.vue'
import { useActiveProject } from '../composables/useActiveProject'

/**
 * Écran « Cohérence des emplacements » — port de CoherenceEmplacements.dc.html.
 *
 * Rapport non bloquant (≠ des conflits, qui sont bloquants) — voir
 * transport_coherence.py. Données : GET /api/projects/{id}/transport-coherence/,
 * qui retourne {'issues': [...], 'issue_count': n} pour tout le projet
 * (déjà existant depuis le 2026-07-24, pas un nouvel endpoint).
 *
 * Le mockup traitait « manquant » et « proposé » comme deux types de premier
 * niveau distincts ; côté backend ce sont en réalité un seul type
 * (`materiel_non_livre`) distingué par le champ `etat` (`manquant`/`propose`).
 *
 * `retour_manquant` (2026-07-30) : à la fin du projet — `Project.end_date` si
 * renseignée, sinon la fin du dernier événement — chaque matériel doit être
 * revenu à son lieu d'origine. Non bloquant comme le reste du rapport.
 * On reconstitue les 4 groupes visuels du mockup à partir de ça. Le texte de
 * contexte de chaque ligne utilise directement `issue.detail`, déjà généré
 * côté backend (une seule source de vérité pour la phrase, plutôt que de la
 * reconstruire côté frontend).
 */

const { activeProjectId } = useActiveProject()

const loading = ref(false)
const loadError = ref(null)
const issues = ref([])

const severity = ref('tous')

async function loadCoherence() {
  if (!activeProjectId.value) return
  loading.value = true
  loadError.value = null
  try {
    const data = await api.get(`/projects/${activeProjectId.value}/transport-coherence/`)
    issues.value = data.issues ?? []
  } catch (e) {
    loadError.value = e
  } finally {
    loading.value = false
  }
}

watch(activeProjectId, loadCoherence, { immediate: true })

function issueSeverity(issue) {
  if (issue.type === 'materiel_non_livre') return issue.etat // 'manquant' | 'propose'
  return issue.type // 'origine_incoherente' | 'origine_inconnue' | 'retour_manquant'
}

const severityMeta = {
  manquant: { badge: 'MANQUANT', color: 'oklch(0.72 0.16 25)', bg: 'oklch(0.72 0.16 25 / .18)', title: 'Matériel requis nulle part amené' },
  propose: { badge: 'PROPOSÉ', color: 'oklch(0.78 0.13 85)', bg: 'oklch(0.78 0.13 85 / .18)', title: 'Couvert par une proposition à approuver' },
  origine_incoherente: { badge: 'ORIGINE INCOHÉRENTE', color: 'oklch(0.78 0.13 85)', bg: 'oklch(0.78 0.13 85 / .18)', title: "Matériel indisponible au lieu de départ prévu" },
  origine_inconnue: { badge: 'ORIGINE INCONNUE', color: 'rgba(255,255,255,.5)', bg: 'rgba(255,255,255,.08)', title: "Matériel sans lieu d'entreposage connu" },
  // Ajouté le 2026-07-30 : à la fin du projet, tout doit être rentré au
  // bercail (voir transport_coherence.get_material_return_issue).
  retour_manquant: { badge: 'NON RETOURNÉ', color: 'oklch(0.75 0.15 300)', bg: 'oklch(0.75 0.15 300 / .18)', title: "Matériel non revenu à son lieu d'origine en fin de projet" },
}

const severityOrder = ['manquant', 'propose', 'retour_manquant', 'origine_incoherente', 'origine_inconnue']

const chips = computed(() => [
  { value: 'tous', label: 'Tous' },
  { value: 'manquant', label: 'Manquant' },
  { value: 'propose', label: 'Proposé' },
  { value: 'retour_manquant', label: 'Non retourné' },
  { value: 'origine_incoherente', label: 'Origine incohérente' },
  { value: 'origine_inconnue', label: 'Origine inconnue' },
])

const filtered = computed(() =>
  severity.value === 'tous' ? issues.value : issues.value.filter((it) => issueSeverity(it) === severity.value),
)

const groups = computed(() =>
  severityOrder
    .map((sev) => ({ sev, items: filtered.value.filter((it) => issueSeverity(it) === sev) }))
    .filter((g) => g.items.length > 0)
    .map((g) => ({ ...severityMeta[g.sev], sev: g.sev, items: g.items, count: g.items.length })),
)

function actionFor(issue) {
  if (issue.type === 'origine_inconnue') {
    return { label: 'Voir le matériel', to: `/materiel/${issue.material_id}` }
  }
  if (issue.type === 'origine_incoherente') {
    return { label: 'Voir le transport', to: `/transports/${issue.transport_id}` }
  }
  if (issue.type === 'retour_manquant') {
    return { label: 'Voir le matériel', to: `/materiel/${issue.material_id}` }
  }
  // materiel_non_livre
  if (issue.etat === 'propose') {
    return { label: 'Voir le transport', to: `/transports/${issue.proposal_transport_id}` }
  }
  return { label: 'Voir le spectacle', to: `/spectacles/${issue.show_id}` }
}
</script>

<template>
  <AppShell>
    <div class="page">
      <div class="header">
        <h1 class="header__title">Cohérence des emplacements</h1>
        <div class="header__subtitle" v-if="!loading">Rapport non bloquant — {{ issues.length }} incohérence{{ issues.length > 1 ? 's' : '' }} détectée{{ issues.length > 1 ? 's' : '' }}</div>
      </div>

      <div class="chips">
        <div
          v-for="c in chips"
          :key="c.value"
          class="chip"
          :class="{ 'chip--active': severity === c.value }"
          @click="severity = c.value"
        >
          {{ c.label }}
        </div>
      </div>

      <div v-if="loading" class="hint">Chargement…</div>
      <div v-else-if="loadError" class="hint hint--error">
        Impossible de charger le rapport. Es-tu connecté (session Django) ?
      </div>

      <template v-else>
        <div v-if="groups.length === 0" class="empty-card">
          <div class="empty-card__dot" />
          <div class="empty-card__label">Aucune incohérence dans cette catégorie</div>
        </div>

        <div v-for="group in groups" :key="group.sev" class="group">
          <div class="group-header">
            <div class="group-badge" :style="{ color: group.color, background: group.bg }">{{ group.badge }}</div>
            <div class="group-title">{{ group.title }}</div>
            <div class="group-count">({{ group.count }})</div>
          </div>

          <div v-for="(issue, idx) in group.items" :key="idx" class="issue">
            <span class="issue__dot" :style="{ background: group.color }" />
            <div class="issue__body">
              <div class="issue__title">{{ issue.material_name }}</div>
              <div class="issue__context">{{ issue.detail }}</div>
            </div>
            <RouterLink :to="actionFor(issue).to" class="issue__action">{{ actionFor(issue).label }}</RouterLink>
          </div>
        </div>
      </template>
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

.header__subtitle {
  font: 400 12.5px system-ui;
  color: rgba(255, 255, 255, 0.45);
  margin-top: 6px;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.hint {
  padding: 32px 40px;
  font: 500 13px system-ui;
  color: rgba(255, 255, 255, 0.5);
}

.hint--error {
  color: oklch(0.78 0.16 35);
}

.empty-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 64px 20px;
  background: var(--bg-card);
  border: 1px dashed rgba(255, 255, 255, 0.15);
  border-radius: var(--radius-notch-lg);
}

.empty-card__dot {
  width: 40px;
  height: 40px;
  border-radius: 0 10px 0 10px;
  background: oklch(0.72 0.13 165 / 0.16);
}

.empty-card__label {
  font: 600 13px system-ui;
  color: rgba(255, 255, 255, 0.6);
}

.group {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.group-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.group-badge {
  font: 700 10px system-ui;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 4px 10px;
  border-radius: 0 6px 0 6px;
}

.group-title {
  font: 700 11px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: rgba(255, 255, 255, 0.5);
}

.group-count {
  font: 500 11.5px system-ui;
  color: rgba(255, 255, 255, 0.3);
}

.issue {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-notch-lg);
  padding: 15px 18px;
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.issue__dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex: none;
}

.issue__body {
  min-width: 190px;
  flex: 1;
}

.issue__title {
  font: 600 14px var(--font-mono);
  color: #fff;
}

.issue__context {
  font: 400 11.5px system-ui;
  color: rgba(255, 255, 255, 0.45);
  margin-top: 2px;
}

.issue__action {
  font: 600 12px system-ui;
  color: #0b0d10;
  background: var(--accent);
  padding: 8px 14px;
  border-radius: 0 7px 0 7px;
  cursor: pointer;
  white-space: nowrap;
  flex: none;
  text-decoration: none;
}
</style>

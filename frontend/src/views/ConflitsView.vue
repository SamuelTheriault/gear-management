<script setup>
import { ref, computed, watch } from 'vue'
import { api } from '../api/client'
import AppShell from '../components/AppShell.vue'
import { useActiveProject } from '../composables/useActiveProject'

/**
 * Écran « Conflits » — port de ConflitDetail.dc.html, généralisé en vue
 * d'ensemble project-wide plutôt qu'un seul chevauchement mis en scène.
 *
 * Le mockup montrait un unique conflit (2 spectacles) avec des boutons
 * « Réassigner le matériel » / « Forcer les deux assignations ». En réalité,
 * les conflits listés ici sont déjà en place dans la base (créés via
 * `force: true`, ou apparus après coup suite à une modification d'horaire
 * elle-même forcée) — il n'y a rien à forcer à nouveau. La résolution passe
 * par une réassignation ou une suppression manuelle sur la fiche du
 * spectacle concerné, d'où des liens « Voir le spectacle » plutôt qu'un
 * bouton de résolution automatique.
 *
 * Données : GET /api/projects/{id}/conflicts/ (voir `get_project_conflicts`,
 * backend/inventory/conflicts.py, ajouté le 2026-07-30) — dédupliqué, une
 * seule entrée par paire en conflit peu importe de quel côté elle est
 * détectée.
 */

const { activeProjectId } = useActiveProject()

const loading = ref(false)
const loadError = ref(null)
const report = ref({ venue_conflicts: [], material_conflicts: [], technician_conflicts: [] })

const dateTimeFmt = new Intl.DateTimeFormat('fr-CA', {
  weekday: 'short',
  day: 'numeric',
  month: 'short',
})
const timeFmt = new Intl.DateTimeFormat('fr-CA', { hour: '2-digit', minute: '2-digit', hour12: false })

async function loadConflicts() {
  if (!activeProjectId.value) return
  loading.value = true
  loadError.value = null
  try {
    report.value = await api.get(`/projects/${activeProjectId.value}/conflicts/`)
  } catch (e) {
    loadError.value = e
  } finally {
    loading.value = false
  }
}

watch(activeProjectId, loadConflicts, { immediate: true })

const totalCount = computed(
  () =>
    (report.value.venue_conflicts?.length ?? 0) +
    (report.value.material_conflicts?.length ?? 0) +
    (report.value.technician_conflicts?.length ?? 0),
)

// --- Fenêtre temporelle générique (show OU transport) pour un côté de conflit ---

function sideWindow(side) {
  if (side.type === 'transport') {
    const start = new Date(side.scheduled_datetime)
    const end = new Date(start.getTime() + (side.estimated_duration_minutes ?? 0) * 60000)
    return { start, end }
  }
  return { start: new Date(side.show_start), end: new Date(side.show_end) }
}

function fmtWindow(side) {
  const { start, end } = sideWindow(side)
  return `${dateTimeFmt.format(start)} · ${timeFmt.format(start)}–${timeFmt.format(end)}`
}

function sideContext(side) {
  if (side.type === 'show_material') return side.material_name
  if (side.type === 'show') return side.venue_name
  if (side.type === 'transport') {
    // `transport_type` a disparu du modèle (tournées multi-arrêts,
    // 2026-08-04) — le contexte utile ici est la personne engagée.
    return `Tournée · ${side.technician_name ?? '—'}`
  }
  return side.technician_name // show_technician
}

// Barre de chevauchement proportionnelle, calculée dynamiquement sur la
// plage min/max des deux côtés (générique, peu importe le type de conflit).
function overlapBar(pair) {
  const a = sideWindow(pair.a)
  const b = sideWindow(pair.b)
  const rangeStart = Math.min(a.start, b.start)
  const rangeEnd = Math.max(a.end, b.end)
  const span = rangeEnd - rangeStart || 1
  const pct = (d) => ((d - rangeStart) / span) * 100
  const overlapStart = Math.max(a.start, b.start)
  const overlapEnd = Math.min(a.end, b.end)
  return {
    a: { left: pct(a.start), width: pct(a.end) - pct(a.start) },
    b: { left: pct(b.start), width: pct(b.end) - pct(b.start) },
    overlap: overlapEnd > overlapStart ? { left: pct(overlapStart), width: pct(overlapEnd) - pct(overlapStart) } : null,
  }
}

const groups = computed(() => [
  { key: 'venue', label: 'Conflits de lieu', items: report.value.venue_conflicts ?? [] },
  { key: 'material', label: 'Conflits de matériel', items: report.value.material_conflicts ?? [] },
  { key: 'technician', label: 'Conflits de technicien', items: report.value.technician_conflicts ?? [] },
])
</script>

<template>
  <AppShell>
    <div class="page">
      <div class="header">
        <h1 class="header__title">Conflits</h1>
        <div class="header__count" v-if="!loading">{{ totalCount }} conflit{{ totalCount > 1 ? 's' : '' }} actif{{ totalCount > 1 ? 's' : '' }}</div>
      </div>

      <div v-if="loading" class="hint">Chargement…</div>
      <div v-else-if="loadError" class="hint hint--error">
        Impossible de charger les conflits. Es-tu connecté (session Django) ?
      </div>

      <template v-else>
        <div v-if="totalCount === 0" class="empty-card">
          Aucun conflit détecté sur ce projet — toutes les assignations respectent les fenêtres d'horaire.
        </div>

        <div v-for="group in groups" :key="group.key">
          <template v-if="group.items.length">
            <div class="group-title">{{ group.label }} ({{ group.items.length }})</div>
            <div class="conflict-list">
              <div v-for="(pair, idx) in group.items" :key="`${group.key}-${idx}`" class="conflict">
                <div class="conflict__alert">
                  <span class="conflict__dot" />
                  <div class="conflict__body">
                    <div class="conflict__title">
                      {{ group.key === 'venue' ? `Conflit de lieu — ${pair.a.venue_name}`
                        : group.key === 'material' ? `Conflit de matériel — ${pair.a.material_name}`
                        : `Conflit de technicien — ${pair.a.technician_name ?? pair.b.technician_name}` }}
                    </div>
                    <div class="conflict__subtitle">{{ pair.a.show_title }} ⇄ {{ pair.b.show_title }}</div>
                  </div>
                </div>

                <div class="sides">
                  <div v-for="(side, i) in [pair.a, pair.b]" :key="i" class="side">
                    <div class="side__title">{{ side.show_title }}</div>
                    <div class="side__context">{{ sideContext(side) }}</div>
                    <div class="side__time">{{ fmtWindow(side) }}</div>
                    <RouterLink :to="`/spectacles/${side.show_id}`" class="side__link">Voir le spectacle →</RouterLink>
                  </div>
                </div>

                <div class="overlay-bar">
                  <div class="overlay-bar__seg overlay-bar__seg--a" :style="{ left: overlapBar(pair).a.left + '%', width: overlapBar(pair).a.width + '%' }" />
                  <div class="overlay-bar__seg overlay-bar__seg--b" :style="{ left: overlapBar(pair).b.left + '%', width: overlapBar(pair).b.width + '%' }" />
                  <div v-if="overlapBar(pair).overlap" class="overlay-bar__zone" :style="{ left: overlapBar(pair).overlap.left + '%', width: overlapBar(pair).overlap.width + '%' }" />
                </div>
              </div>
            </div>
          </template>
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

.header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
}

.header__count {
  font: 600 12.5px system-ui;
  color: rgba(var(--fg-rgb), 0.5);
}

.hint {
  padding: 32px 40px;
  font: 500 13px system-ui;
  color: rgba(var(--fg-rgb), 0.5);
}

.hint--error {
  color: oklch(0.78 0.16 35);
}

.empty-card {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-notch-lg);
  padding: 24px;
  font: 500 13px system-ui;
  color: rgba(var(--fg-rgb), 0.55);
}

.group-title {
  font: 700 11px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: rgba(var(--fg-rgb), 0.45);
  margin: 4px 0 10px;
}

.conflict-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-bottom: 8px;
}

.conflict {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-notch-lg);
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.conflict__alert {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 12px 16px;
  border-radius: 0 10px 0 10px;
  background: oklch(0.27 0.07 35);
  border: 1px solid oklch(0.5 0.15 35);
}

.conflict__dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: oklch(0.7 0.16 35);
  flex: none;
  box-shadow: 0 0 0 4px oklch(0.7 0.16 35 / 0.25);
}

.conflict__title {
  font: 700 13.5px var(--font-mono);
  color: #ffe3c9;
}

.conflict__subtitle {
  font: 400 12px system-ui;
  color: rgba(255, 217, 207, 0.75);
  margin-top: 2px;
}

.sides {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.side {
  background: var(--bg-row);
  border: 1px solid oklch(0.5 0.15 35 / 0.35);
  border-radius: 0 10px 0 10px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.side__title {
  font: 600 14px var(--font-mono);
  color: rgb(var(--fg-rgb));
}

.side__context {
  font: 400 12px system-ui;
  color: rgba(var(--fg-rgb), 0.5);
}

.side__time {
  font: 500 12px system-ui;
  color: rgba(var(--fg-rgb), 0.7);
  margin-top: 4px;
}

.side__link {
  margin-top: 8px;
  font: 600 11.5px system-ui;
  color: var(--link);
  text-decoration: none;
}

.overlay-bar {
  position: relative;
  height: 56px;
  background: var(--bg-row);
  border-radius: var(--radius-notch-sm);
}

.overlay-bar__seg {
  position: absolute;
  top: 6px;
  height: 20px;
  border-radius: 0 6px 0 6px;
  background: oklch(0.72 0.13 165 / 0.5);
}

.overlay-bar__seg--b {
  top: 30px;
}

.overlay-bar__zone {
  position: absolute;
  top: 0;
  bottom: 0;
  background: oklch(0.7 0.16 35 / 0.35);
  border-left: 1px dashed oklch(0.7 0.16 35);
  border-right: 1px dashed oklch(0.7 0.16 35);
}
</style>

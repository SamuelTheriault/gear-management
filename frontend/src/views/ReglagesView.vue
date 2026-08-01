<script setup>
import { ref, computed, onMounted } from 'vue'
import AppShell from '../components/AppShell.vue'
import { api } from '../api/client'
import { useActiveProject } from '../composables/useActiveProject'

/**
 * Écran « Réglages » — port de Reglages.dc.html.
 *
 * Branché sur le singleton GET/PATCH /api/settings/ (voir Settings,
 * models.py — une seule ligne, pk=1). La section « Projets » du mockup
 * (liste + création) réutilise `useActiveProject` plutôt que de refaire un
 * fetch séparé, et appelle `refreshProjects()` après création pour que le
 * sélecteur de projet dans AppShell voie la nouvelle entrée sans refresh.
 *
 * Contrairement au mockup (état local, jamais persisté), ici « Enregistrer »
 * fait un vrai PATCH — les erreurs de validation viennent du backend
 * (PositiveIntegerField) plutôt que d'une validation dupliquée côté Vue.
 */

const { projects, refreshProjects } = useActiveProject()

const loading = ref(false)
const loadError = ref(null)
const form = ref(null)

const saving = ref(false)
const saveError = ref(null)
const showSaved = ref(false)

const dateFormats = [
  { value: 'DMY', label: 'JJ/MM/AAAA' },
  { value: 'MDY', label: 'MM/DD/YYYY' },
]
const timeFormats = [
  { value: '24h', label: '24h' },
  { value: '12h', label: '12h' },
]

async function loadSettings() {
  loading.value = true
  loadError.value = null
  try {
    form.value = await api.get('/settings/')
  } catch (e) {
    loadError.value = e
  } finally {
    loading.value = false
  }
}

onMounted(loadSettings)

async function save() {
  saveError.value = null
  showSaved.value = false
  saving.value = true
  try {
    form.value = await api.patch('/settings/', {
      default_buffer_before_minutes: Number(form.value.default_buffer_before_minutes),
      default_buffer_after_minutes: Number(form.value.default_buffer_after_minutes),
      default_transport_duration_minutes: Number(form.value.default_transport_duration_minutes),
      date_format: form.value.date_format,
      time_format: form.value.time_format,
    })
    showSaved.value = true
  } catch (e) {
    saveError.value =
      e.data?.default_buffer_before_minutes?.[0] ??
      e.data?.default_buffer_after_minutes?.[0] ??
      e.data?.default_transport_duration_minutes?.[0] ??
      e.data?.detail ??
      "Impossible d'enregistrer les réglages."
  } finally {
    saving.value = false
  }
}

// --- Projets ---

const newProjectName = ref('')
const newProjectError = ref(null)
const creatingProject = ref(false)

const dateFmt = new Intl.DateTimeFormat('fr-CA', { day: 'numeric', month: 'short', year: 'numeric' })
const projectColors = ['oklch(0.65 0.15 290)', 'oklch(0.7 0.15 165)', 'oklch(0.75 0.15 60)', 'oklch(0.7 0.16 35)']

const decoratedProjects = computed(() =>
  projects.value.map((p, i) => ({
    ...p,
    color: projectColors[i % projectColors.length],
    createdAtLabel: p.created_at ? dateFmt.format(new Date(p.created_at)) : '—',
  })),
)

// --- Dates de projet (2026-07-30) ---
// `Project.start_date`/`end_date` existaient depuis le 2026-07-19 mais
// n'étaient saisissables nulle part. `end_date` sert d'horizon au contrôle de
// retour du matériel (voir transport_coherence.get_project_horizon) : sans
// elle, l'app retombe sur la fin du dernier événement du projet.

const projectDates = ref({})
const projectDateErrors = ref({})
const savingDates = ref({})

function draftDates(project) {
  if (!projectDates.value[project.id]) {
    projectDates.value = {
      ...projectDates.value,
      [project.id]: {
        start_date: project.start_date ?? '',
        end_date: project.end_date ?? '',
      },
    }
  }
  return projectDates.value[project.id]
}

async function saveProjectDates(project) {
  const draft = draftDates(project)
  savingDates.value = { ...savingDates.value, [project.id]: true }
  projectDateErrors.value = { ...projectDateErrors.value, [project.id]: null }
  try {
    await api.patch(`/projects/${project.id}/`, {
      // Champ vidé = pas de date, donc `null` et non la chaîne vide.
      start_date: draft.start_date || null,
      end_date: draft.end_date || null,
    })
    await refreshProjects()
  } catch (e) {
    projectDateErrors.value = {
      ...projectDateErrors.value,
      [project.id]:
        e.data?.end_date?.[0] ?? e.data?.start_date?.[0] ?? e.data?.detail ??
        'Impossible d’enregistrer les dates.',
    }
  } finally {
    savingDates.value = { ...savingDates.value, [project.id]: false }
  }
}

const canAddProject = computed(() => newProjectName.value.trim().length > 0)

async function addProject() {
  const name = newProjectName.value.trim()
  if (!name) {
    newProjectError.value = 'Nom requis.'
    return
  }
  newProjectError.value = null
  creatingProject.value = true
  try {
    await api.post('/projects/', { name })
    newProjectName.value = ''
    await refreshProjects()
  } catch (e) {
    newProjectError.value = e.data?.name?.[0] ?? e.data?.detail ?? 'Impossible de créer le projet.'
  } finally {
    creatingProject.value = false
  }
}
</script>

<template>
  <AppShell>
    <div class="page">
      <h1 class="page-title">Réglages</h1>

      <div v-if="loading" class="hint">Chargement…</div>
      <div v-else-if="loadError" class="hint hint--error">
        Impossible de charger les réglages. Es-tu connecté (session Django) ?
      </div>

      <template v-else-if="form">
        <section class="section">
          <div class="section-title">Projets</div>
          <div class="project-list">
            <div v-for="p in decoratedProjects" :key="p.id" class="project-row">
              <span class="project-dot" :style="{ background: p.color }" />
              <div class="project-body">
                <div class="project-top">
                  <div class="project-name">{{ p.name }}</div>
                  <div class="project-date">Créé le {{ p.createdAtLabel }}</div>
                </div>
                <div class="project-dates">
                  <label class="project-field">
                    <span class="project-field__label">Début</span>
                    <input
                      v-model="draftDates(p).start_date"
                      type="date"
                      class="input input--date"
                      @change="saveProjectDates(p)"
                    />
                  </label>
                  <label class="project-field">
                    <span class="project-field__label">Fin</span>
                    <input
                      v-model="draftDates(p).end_date"
                      type="date"
                      class="input input--date"
                      @change="saveProjectDates(p)"
                    />
                  </label>
                  <span v-if="savingDates[p.id]" class="project-saving">Enregistrement…</span>
                </div>
                <div v-if="projectDateErrors[p.id]" class="error">{{ projectDateErrors[p.id] }}</div>
              </div>
            </div>
            <div v-if="decoratedProjects.length === 0" class="row-empty">Aucun projet actif.</div>
          </div>
          <div class="create-card">
            <div class="create-title">Créer un projet</div>
            <div class="create-row">
              <input v-model="newProjectName" placeholder="Nom du projet" class="input input--wide" @keyup.enter="addProject" />
              <div
                class="btn"
                :class="canAddProject && !creatingProject ? 'btn--enabled' : 'btn--disabled'"
                @click="canAddProject && !creatingProject && addProject()"
              >
                + Créer
              </div>
            </div>
            <div v-if="newProjectError" class="error">{{ newProjectError }}</div>
            <div class="create-hint">
              Chaque projet a son propre matériel, spectacles, lieux et techniciens — les réglages ci-dessous s'appliquent globalement.
              La date de fin sert de repère pour vérifier que tout le matériel est
              revenu à son lieu d'origine (écran Cohérence) ; sans elle, l'app
              retient la fin du dernier événement.
            </div>
          </div>
        </section>

        <section class="section">
          <div class="section-title">Fenêtres effectives</div>
          <div class="card">
            <div class="field-row">
              <div class="field">
                <label class="label">Buffer avant (minutes)</label>
                <input v-model.number="form.default_buffer_before_minutes" type="number" min="0" class="input" />
              </div>
              <div class="field">
                <label class="label">Buffer après (minutes)</label>
                <input v-model.number="form.default_buffer_after_minutes" type="number" min="0" class="input" />
              </div>
            </div>
            <div class="hint-text">
              Marge appliquée automatiquement avant/après chaque spectacle pour couvrir transport et installation — s'applique aux nouvelles fiches seulement, pas rétroactif.
            </div>
          </div>
        </section>

        <section class="section">
          <div class="section-title">Transport</div>
          <div class="card">
            <div class="field field--narrow">
              <label class="label">Durée de transport par défaut (minutes)</label>
              <input v-model.number="form.default_transport_duration_minutes" type="number" min="0" class="input" />
            </div>
            <div class="hint-text">Utilisée si le calcul automatique du trajet échoue ou n'est pas configuré.</div>
          </div>
        </section>

        <section class="section">
          <div class="section-title">Affichage</div>
          <div class="card">
            <div class="field">
              <label class="label">Format de date</label>
              <div class="chips">
                <div
                  v-for="f in dateFormats"
                  :key="f.value"
                  class="chip"
                  :class="{ 'chip--active': form.date_format === f.value }"
                  @click="form.date_format = f.value"
                >
                  {{ f.label }}
                </div>
              </div>
            </div>
            <div class="field">
              <label class="label">Format d'heure</label>
              <div class="chips">
                <div
                  v-for="f in timeFormats"
                  :key="f.value"
                  class="chip"
                  :class="{ 'chip--active': form.time_format === f.value }"
                  @click="form.time_format = f.value"
                >
                  {{ f.label }}
                </div>
              </div>
            </div>
          </div>
        </section>

        <div class="save-row">
          <div class="btn btn--enabled" :class="{ 'btn--disabled': saving }" @click="!saving && save()">Enregistrer</div>
          <div v-if="showSaved" class="saved">
            <span class="saved__dot" />Réglages enregistrés
          </div>
          <div v-if="saveError" class="error">{{ saveError }}</div>
        </div>
      </template>
    </div>
  </AppShell>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 28px;
  max-width: 680px;
}

.hint {
  padding: 32px 40px;
  font: 500 13px system-ui;
  color: rgba(255, 255, 255, 0.5);
}

.hint--error {
  color: oklch(0.78 0.16 35);
}

.section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.section-title {
  font: 700 12px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: rgba(255, 255, 255, 0.45);
}

.card {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-notch-lg);
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.project-list {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-notch-lg);
  padding: 8px;
}

.project-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.project-row:last-child {
  border-bottom: none;
}

.project-dot {
  margin-top: 5px;
  width: 8px;
  height: 8px;
  border-radius: 2px;
  flex: none;
}

.project-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.project-top {
  display: flex;
  align-items: center;
  gap: 12px;
}

.project-name {
  flex: 1;
  font: 600 13px system-ui;
  color: #fff;
}

.project-dates {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.project-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.project-field__label {
  font: 700 9.5px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: rgba(255, 255, 255, 0.35);
}

.input--date {
  width: 160px;
}

.project-saving {
  font: 500 11px system-ui;
  color: rgba(255, 255, 255, 0.35);
  padding-bottom: 10px;
}

.project-date {
  font: 400 11.5px system-ui;
  color: rgba(255, 255, 255, 0.35);
}

.row-empty {
  font: 500 12.5px system-ui;
  color: rgba(255, 255, 255, 0.4);
  padding: 10px;
}

.create-card {
  background: var(--bg-card);
  border: 1px dashed rgba(255, 255, 255, 0.15);
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
  color: rgba(255, 255, 255, 0.4);
}

.create-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
}

.create-hint {
  font: 400 12px system-ui;
  color: rgba(255, 255, 255, 0.4);
  line-height: 1.5;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1;
  min-width: 200px;
}

.field--narrow {
  max-width: 260px;
}

.field-row {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
}

.label {
  font: 500 12px system-ui;
  color: rgba(255, 255, 255, 0.5);
}

.input {
  box-sizing: border-box;
  padding: 10px 12px;
  border-radius: var(--radius-notch-sm);
  background: #1b1f25;
  border: 1px solid rgba(255, 255, 255, 0.1);
  font: 500 13px system-ui;
  color: #fff;
}

.input--wide {
  flex: 2;
  min-width: 200px;
}

.hint-text {
  font: 400 12px system-ui;
  color: rgba(255, 255, 255, 0.4);
  line-height: 1.5;
}

.chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.save-row {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.btn {
  font: 600 13px system-ui;
  color: #0b0d10;
  background: var(--accent);
  padding: 12px 22px;
  border-radius: var(--radius-notch-sm);
  cursor: pointer;
  white-space: nowrap;
}

.btn--enabled {
  color: #fff;
  background: oklch(0.65 0.15 290 / 0.3);
}

.btn--disabled {
  color: rgba(255, 255, 255, 0.3);
  background: rgba(255, 255, 255, 0.06);
  cursor: default;
}

.saved {
  display: flex;
  align-items: center;
  gap: 6px;
  font: 600 12.5px system-ui;
  color: oklch(0.72 0.13 165);
}

.saved__dot {
  width: 7px;
  height: 7px;
  border-radius: 2px;
  background: oklch(0.72 0.13 165);
}

.error {
  font: 500 11.5px system-ui;
  color: oklch(0.78 0.16 35);
}
</style>

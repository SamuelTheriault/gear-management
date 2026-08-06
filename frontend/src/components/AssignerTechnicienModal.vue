<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api/client'
import { useEscapeKey } from '../composables/useEscapeKey'

/**
 * Modale « Assigner des techniciens » — port de AssignationTechnicien.dc.html.
 *
 * Le mockup montrait un champ « Rôle sur ce spectacle » éditable, mais
 * ShowTechnician (models.py) n'a pas de champ de rôle par assignation — le
 * rôle affiché est `Technician.specialty`, en lecture seule ici (décision
 * reconduite le 2026-07-30).
 *
 * Multi-sélection (2026-07-30) : liste à cocher plutôt qu'un menu déroulant,
 * même pattern que `AssignerMaterielModal`. Tous les techniciens du projet
 * sont visibles, ceux déjà assignés apparaissent cochés.
 *
 * Décochage = retrait (2026-07-30, suite) : décocher une personne déjà
 * assignée la marque à retirer, et le bouton « Appliquer » exécute ajouts et
 * retraits ensemble. Rien ne part avant la validation — décocher par erreur se
 * rattrape en recochant. `ShowTechnician` n'a pas d'écriture groupée côté
 * API : chaque ligne devient un `POST` ou un `DELETE` séparé (boucle
 * séquentielle).
 */

const props = defineProps({
  showId: { type: [Number, String], required: true },
  projectId: { type: [Number, String], required: true },
  showLabel: { type: String, default: '' },
  // Objets `ShowTechnician` complets (et non juste des ids) : leur `id` est
  // nécessaire pour le DELETE d'un retrait.
  assignedTechnicians: { type: Array, default: () => [] },
})

const emit = defineEmits(['close', 'assigned'])

// Échap ferme la modale, même geste que le clic sur le fond ou le « × ».
useEscapeKey(() => emit('close'))

function initials(name) {
  return (name || '?')
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join('')
}

const loading = ref(true)
const technicians = ref([])
// À ajouter : techniciens cochés qui ne sont pas déjà assignés.
const selectedIds = ref([])
// À retirer : techniciens déjà assignés qu'on vient de décocher.
const removedIds = ref([])
// Erreurs par technicien, remplies après une soumission partielle.
const rowErrors = ref({})
const conflictRows = ref({})

const saving = ref(false)
const formError = ref(null)

const assignedByTechnicianId = computed(() => {
  const map = new Map()
  props.assignedTechnicians.forEach((st) => map.set(st.technician, st))
  return map
})

onMounted(async () => {
  loading.value = true
  try {
    const data = await api.get('/technicians/', { project: props.projectId })
    technicians.value = Array.isArray(data) ? data : (data.results ?? [])
  } finally {
    loading.value = false
  }
})

const rows = computed(() =>
  technicians.value.map((t) => {
    const assignment = assignedByTechnicianId.value.get(t.id) ?? null
    const removed = removedIds.value.includes(t.id)
    const added = selectedIds.value.includes(t.id)
    return {
      id: t.id,
      name: t.name,
      specialty: t.specialty || '—',
      initials: initials(t.name),
      assigned: !!assignment,
      removed,
      added,
      // Coché = déjà assigné et non retiré, ou nouvellement coché.
      checked: (!!assignment && !removed) || added,
      error: rowErrors.value[t.id] ?? null,
      conflict: conflictRows.value[t.id] ?? null,
      toggle: () => {
        if (assignment) {
          removedIds.value = removed
            ? removedIds.value.filter((id) => id !== t.id)
            : [...removedIds.value, t.id]
        } else {
          selectedIds.value = added
            ? selectedIds.value.filter((id) => id !== t.id)
            : [...selectedIds.value, t.id]
        }
      },
    }
  }),
)

const addCount = computed(() => selectedIds.value.length)
const removeCount = computed(() => removedIds.value.length)
const hasChanges = computed(() => addCount.value + removeCount.value > 0)
const conflictCount = computed(() => Object.keys(conflictRows.value).length)

async function submit(force = false) {
  if (!hasChanges.value) {
    formError.value = 'Aucun changement à appliquer.'
    return
  }
  formError.value = null
  saving.value = true

  const nextErrors = {}
  const nextConflicts = {}
  let anySuccess = false

  // Retraits d'abord : libérer une personne peut lever le conflit qui
  // bloquerait l'ajout d'une autre dans la même fournée.
  for (const id of [...removedIds.value]) {
    const assignment = assignedByTechnicianId.value.get(id)
    if (!assignment) continue
    try {
      await api.delete(`/show-technicians/${assignment.id}/`)
      removedIds.value = removedIds.value.filter((other) => other !== id)
      anySuccess = true
    } catch (e) {
      nextErrors[id] = e.data?.detail ?? 'Impossible de retirer ce technicien.'
    }
  }

  for (const id of [...selectedIds.value]) {
    try {
      await api.post('/show-technicians/', { show: props.showId, technician: id, force })
      selectedIds.value = selectedIds.value.filter((other) => other !== id)
      anySuccess = true
    } catch (e) {
      if (e.data?.conflicts) {
        nextConflicts[id] = e.data
      } else {
        nextErrors[id] = e.data?.technician?.[0] ?? e.data?.detail ?? "Impossible d'assigner ce technicien."
      }
    }
  }

  rowErrors.value = nextErrors
  conflictRows.value = nextConflicts
  saving.value = false

  // `done` dit au parent s'il peut fermer la modale : on la garde ouverte tant
  // qu'il reste des conflits à forcer ou des erreurs à corriger, sinon on
  // perdrait le détail juste après l'avoir affiché.
  const done = Object.keys(nextConflicts).length === 0 && Object.keys(nextErrors).length === 0
  if (anySuccess || !done) emit('assigned', { done })
}
</script>

<template>
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="modal">
      <div class="modal__header">
        <div class="modal__title">Techniciens du spectacle</div>
        <div class="modal__close" @click="emit('close')">×</div>
      </div>
      <div class="modal__context">{{ showLabel }}</div>
      <div class="modal__hint">
        Coche pour assigner, décoche pour retirer. Rien n'est appliqué avant la validation.
      </div>

      <div v-if="loading" class="hint">Chargement des techniciens…</div>
      <template v-else>
        <div v-if="rows.length === 0" class="hint">
          Aucun technicien dans ce projet.
        </div>

        <div v-else class="tech-list">
          <div
            v-for="t in rows"
            :key="t.id"
            class="tech-row"
            :class="{
              'tech-row--selected': t.checked,
              'tech-row--added': t.added,
              'tech-row--removed': t.removed,
            }"
          >
            <div
              class="tech-row__check"
              :class="{ 'tech-row__check--on': t.checked }"
              @click="t.toggle"
            >
              <span v-if="t.checked">✓</span>
            </div>
            <div class="avatar">{{ t.initials }}</div>
            <div class="tech-row__body">
              <div class="tech-row__name">{{ t.name }}</div>
              <div class="tech-row__role">
                <template v-if="t.removed">À retirer</template>
                <template v-else-if="t.added">À assigner · {{ t.specialty }}</template>
                <template v-else-if="t.assigned">Assigné · {{ t.specialty }}</template>
                <template v-else>{{ t.specialty }}</template>
              </div>
              <div v-if="t.error" class="error">{{ t.error }}</div>
              <div v-if="t.conflict" class="conflict">{{ t.conflict.detail }}</div>
            </div>
          </div>
        </div>

        <div v-if="formError" class="error">{{ formError }}</div>
      </template>

      <div class="modal__footer">
        <div class="modal__count">
          <template v-if="hasChanges">
            {{ addCount }} à assigner · {{ removeCount }} à retirer
          </template>
          <template v-else>Aucun changement</template>
        </div>
        <div class="btn btn--ghost" @click="emit('close')">Fermer</div>
        <div v-if="conflictCount > 0" class="btn btn--force" @click="submit(true)">
          Forcer {{ conflictCount }} conflit(s)
        </div>
        <div
          class="btn btn--primary"
          :class="{ 'btn--disabled': saving || !hasChanges }"
          @click="!saving && hasChanges && submit(false)"
        >
          {{ saving ? 'Application…' : 'Appliquer' }}
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>

.modal {
  width: min(440px, 92vw);
  /* Hauteur FIXE (2026-07-30) — même raison que la modale matériel : la
     modale ne doit ni rétrécir ni se recentrer selon le nombre de lignes. */
  height: 85vh;
  max-height: 85vh;
  background: var(--bg-card);
  border: 1px solid rgba(var(--fg-rgb), 0.08);
  border-radius: 0 14px 0 14px;
  padding: 22px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.modal__title {
  font: 700 15px var(--font-mono);
  letter-spacing: 0.03em;
  color: rgb(var(--fg-rgb));
}

.modal__close {
  font: 400 20px system-ui;
  color: rgba(var(--fg-rgb), 0.58);
  cursor: pointer;
  line-height: 1;
}

.modal__context {
  font: 500 12px system-ui;
  color: rgba(var(--fg-rgb), 0.58);
  margin-top: -8px;
}

.hint {
  font: 500 12.5px system-ui;
  color: rgba(var(--fg-rgb), 0.58);
  padding: 8px 0;
}

.tech-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  /* Absorbe la hauteur restante et défile, plutôt qu'un plafond en vh qui
     laisserait du vide sous la liste quand elle est courte. */
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.tech-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: var(--radius-notch-sm);
  background: var(--bg-row);
  border: 1px solid rgba(var(--fg-rgb), 0.08);
}

.tech-row--selected {
  border-color: rgba(var(--accent-rgb), 0.35);
}

/* Marqué à retirer : barré et estompé jusqu'à la validation. */
.tech-row--removed {
  opacity: 0.5;
  border-color: oklch(0.5 0.15 35);
}

.tech-row--removed .tech-row__name {
  text-decoration: line-through;
}

.tech-row--removed .tech-row__role {
  color: oklch(0.78 0.16 35);
}

.tech-row__check {
  width: 18px;
  height: 18px;
  border-radius: 0 4px 0 4px;
  border: 1.5px solid rgba(var(--fg-rgb), 0.3);
  flex: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font: 700 11px system-ui;
  color: #0b0d10;
}

.tech-row__check--on {
  background: var(--accent);
  border-color: var(--accent);
}

.tech-row__body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.tech-row__name {
  font: 600 13px system-ui;
  color: rgb(var(--fg-rgb));
}

.tech-row__role {
  font: 400 11px system-ui;
  color: rgba(var(--fg-rgb), 0.48);
}

.modal__hint {
  font: 400 11.5px system-ui;
  color: rgba(var(--fg-rgb), 0.43);
  padding-bottom: 4px;
}

.modal__count {
  margin-right: auto;
  font: 500 11.5px system-ui;
  color: rgba(var(--fg-rgb), 0.48);
  align-self: center;
}

.avatar {
  width: 24px;
  height: 24px;
  border-radius: 0 6px 0 6px;
  background: oklch(0.65 0.15 290 / 0.3);
  color: var(--accent);
  display: flex;
  align-items: center;
  justify-content: center;
  font: 700 10.5px system-ui;
  flex: none;
}

.error {
  font: 500 11.5px system-ui;
  color: oklch(0.78 0.16 35);
}

.conflict {
  padding: 10px;
  border-radius: var(--radius-notch-sm);
  background: oklch(0.27 0.07 35);
  border: 1px solid oklch(0.5 0.15 35);
  font: 400 12px system-ui;
  color: rgba(255, 217, 207, 0.9);
}

.modal__footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 4px;
}

.btn {
  font: 600 12px system-ui;
  padding: 9px 16px;
  border-radius: var(--radius-notch-sm);
  cursor: pointer;
  white-space: nowrap;
}

.btn--ghost {
  color: rgba(var(--fg-rgb), 0.68);
  background: rgba(var(--fg-rgb), 0.06);
}

.btn--primary {
  color: #0b0d10;
  background: var(--accent);
}

.btn--disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn--force {
  background: oklch(0.7 0.16 35);
  color: #2a1400;
}
</style>

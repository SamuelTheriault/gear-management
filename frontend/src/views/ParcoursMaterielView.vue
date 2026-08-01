<script setup>
import { ref, computed, watch } from 'vue'
import AppShell from '../components/AppShell.vue'
import ParcoursDayPicker from '../components/ParcoursDayPicker.vue'
import { api } from '../api/client'
import { useActiveProject } from '../composables/useActiveProject'
import { useParcours } from '../composables/useParcours'

/**
 * Parcours du matériel (`/parcours/materiel`, sous-menu du Tableau de bord
 * depuis le 2026-07-30) — ajouté le 2026-07-30 à la
 * demande de Samuel : voir OÙ SE TROUVE chaque matériel sur toute la durée de
 * la production, et pas seulement ses engagements.
 *
 * Les séjours viennent de `GET /api/projects/{id}/material-journey/`, qui
 * réutilise le grand livre de positions de `transport_coherence.py` — même
 * source de vérité que la cohérence des emplacements et que la disponibilité
 * au départ d'un transport. Les trois écrans ne peuvent donc pas se
 * contredire.
 *
 * Affichage jour par jour (2026-07-31, demande de Samuel : « comme le
 * dashboard principal, avec des boutons de filtre pour sélectionner la
 * journée ») : une seule journée à la fois (axe 0h→24h), choisie via des
 * puces + flèches précédent/suivant (`days`/`selectedDayKey`/`selectDay`/
 * `stepDay` dans useParcours). Chaque séjour/marque/transport est tronqué aux
 * bornes de la journée choisie (`overlapsDay`) — un séjour à cheval sur deux
 * jours n'apparaît que pour sa portion dans le jour affiché.
 *
 * Lecture d'une ligne : un segment coloré par lieu de séjour, et un liseré
 * lavande en bas quand le matériel est requis par un spectacle à ce
 * moment-là — pour repérer d'un coup d'œil « il est bien là où il sert ».
 *
 * Filtre par catégorie (2026-07-30, suite, demande de Samuel : « on va avoir
 * beaucoup de matériel ») : les mêmes puces que l'inventaire, appliquées au
 * panneau de sélection. « Tout » ne coche alors que ce qui est visible — voir
 * `selectAll` dans useParcours. Comme dans l'inventaire, seules les catégories
 * réellement présentes deviennent des puces : une puce qui ne mène nulle part
 * n'aide personne.
 *
 * Sélection multiple des puces (2026-07-30, suite) : ⌘ + clic (ou Ctrl sur
 * PC) ajoute/retire une catégorie de la sélection ; un clic simple remplace
 * la sélection par cette seule catégorie. Aucune catégorie sélectionnée
 * équivaut à « Tous », ce qui évite un état vide où plus rien ne s'afficherait.
 *
 * Arborescence des kits (2026-07-30, suite) : le panneau de sélection affiche
 * les composants en retrait sous leur kit, comme l'inventaire et les modales
 * d'assignation. Un composant dont le kit est masqué par le filtre de
 * catégorie reste affiché, mais au premier niveau — mieux vaut orphelin que
 * perdu.
 *
 * Sélection en cascade : cocher un kit coche ses composants, décocher le kit
 * les décoche — même comportement que les modales d'assignation, à la demande
 * de Samuel. La cascade porte sur TOUS les composants du kit, y compris ceux
 * que le filtre de catégorie masque : ils appartiennent au kit, et leur ligne
 * apparaît alors dans la timeline même si la case correspondante n'est pas
 * visible dans le panneau. Chaque composant reste décochable individuellement.
 */

const { activeProjectId } = useActiveProject()

const {
  options, selectedIds, rows, window: fenetre, loading, loadError,
  days, selectedDayKey, selectDay, stepDay, hourMarks, overlapsDay,
  selectAll, selectNone, segmentStyle,
} = useParcours({
  endpoint: 'material-journey',
  itemsKey: 'materials',
  listEndpoint: '/materials/',
  listParam: 'materials',
})

// --- Filtre par catégorie ---

const categories = ref([])
// Liste de clés sélectionnées (id de catégorie, ou 'none' pour le matériel
// non classé). Vide = aucune restriction, donc « Tous ».
const selectedCategories = ref([])

async function loadCategories() {
  if (!activeProjectId.value) return
  const data = await api.get('/material-categories/', { project: activeProjectId.value })
  categories.value = Array.isArray(data) ? data : (data.results ?? [])
}

watch(activeProjectId, loadCategories, { immediate: true })

/**
 * Clic sur une puce de catégorie.
 *
 * ⌘ (macOS) ou Ctrl (PC) enfoncé : bascule cette catégorie dans la sélection,
 * pour en cumuler plusieurs. Sinon : la sélection est remplacée par cette
 * seule catégorie — le geste courant reste un clic simple.
 *
 * Décocher la dernière catégorie retombe sur « Tous » plutôt que sur une
 * liste vide : un panneau sans aucune option n'apprend rien.
 */
function pickCategory(key, event) {
  const cumul = event?.metaKey || event?.ctrlKey
  if (key === 'all') {
    selectedCategories.value = []
    return
  }
  if (!cumul) {
    selectedCategories.value = [key]
    return
  }
  selectedCategories.value = selectedCategories.value.includes(key)
    ? selectedCategories.value.filter((other) => other !== key)
    : [...selectedCategories.value, key]
}

const categoryChips = computed(() => {
  // Seules les catégories présentes dans le matériel du projet, et la puce
  // « Sans catégorie » uniquement s'il existe vraiment du matériel non classé.
  const present = new Set(options.value.map((m) => m.category).filter((id) => id != null))
  const chips = [
    {
      key: 'all',
      label: 'Tous',
      active: selectedCategories.value.length === 0,
    },
    ...categories.value
      .filter((c) => present.has(c.id))
      .map((c) => ({
        key: c.id,
        label: c.name,
        color: c.color,
        active: selectedCategories.value.includes(c.id),
      })),
  ]
  if (options.value.some((m) => m.category == null)) {
    chips.push({
      key: 'none',
      label: 'Sans catégorie',
      active: selectedCategories.value.includes('none'),
    })
  }
  return chips
})

const matchingOptions = computed(() =>
  options.value.filter((m) => {
    if (selectedCategories.value.length === 0) return true
    const cle = m.category == null ? 'none' : m.category
    return selectedCategories.value.includes(cle)
  }),
)

/**
 * Ordonne la liste comme l'inventaire : chaque composant suit immédiatement
 * son kit. `nested` marque ceux qu'on affiche en retrait — c'est-à-dire ceux
 * dont le parent est lui aussi visible dans la liste courante.
 */
const visibleOptions = computed(() => {
  const liste = matchingOptions.value
  const visibles = new Set(liste.map((m) => m.id))

  const enfants = new Map()
  liste.forEach((m) => {
    if (m.parent_material == null || !visibles.has(m.parent_material)) return
    if (!enfants.has(m.parent_material)) enfants.set(m.parent_material, [])
    enfants.get(m.parent_material).push(m)
  })

  const ordonne = []
  liste.forEach((m) => {
    if (m.parent_material != null && visibles.has(m.parent_material)) return
    ordonne.push({ ...m, nested: false, childCount: (enfants.get(m.id) ?? []).length })
    ;(enfants.get(m.id) ?? []).forEach((child) => {
      ordonne.push({ ...child, nested: true, childCount: 0 })
    })
  })
  return ordonne
})

const childrenByParent = computed(() => {
  const map = new Map()
  options.value.forEach((m) => {
    if (m.parent_material == null) return
    if (!map.has(m.parent_material)) map.set(m.parent_material, [])
    map.get(m.parent_material).push(m)
  })
  return map
})

/**
 * Coche/décoche une ligne, en entraînant les composants d'un kit.
 *
 * On écrit `selectedIds` en une seule fois plutôt que d'appeler le `toggle`
 * du composable pour chaque id : celui-ci est observé et déclencherait un
 * appel API par composant.
 */
function toggleOption(option) {
  const dejaCoche = selectedIds.value.includes(option.id)
  const enfants = childrenByParent.value.get(option.id) ?? []
  const cibles = [option.id, ...enfants.map((c) => c.id)]

  selectedIds.value = dejaCoche
    ? selectedIds.value.filter((id) => !cibles.includes(id))
    : [...new Set([...selectedIds.value, ...cibles])]
}

// Une couleur stable par lieu, pour qu'un même lieu garde la même teinte d'une
// ligne à l'autre. L'entrepôt (le « bercail ») est volontairement neutre : ce
// qui doit sauter aux yeux, c'est quand le matériel en est SORTI.
const PALETTE = [
  'oklch(0.55 0.13 290)',
  'oklch(0.52 0.13 200)',
  'oklch(0.55 0.13 145)',
  'oklch(0.55 0.13 60)',
  'oklch(0.52 0.13 320)',
  'oklch(0.55 0.13 25)',
]

const venueColors = computed(() => {
  const map = new Map()
  let i = 0
  rows.value.forEach((row) => {
    row.stays.forEach((stay) => {
      if (map.has(stay.venue_id)) return
      map.set(stay.venue_id, stay.is_storage ? 'rgba(255,255,255,.12)' : PALETTE[i++ % PALETTE.length])
    })
  })
  return map
})

const legend = computed(() => {
  const seen = new Map()
  rows.value.forEach((row) => {
    row.stays.forEach((stay) => {
      if (!seen.has(stay.venue_id)) {
        seen.set(stay.venue_id, { name: stay.venue_name, color: venueColors.value.get(stay.venue_id) })
      }
    })
  })
  return [...seen.values()]
})

const dateFmt = new Intl.DateTimeFormat('fr-CA', {
  day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
})

const decorated = computed(() =>
  rows.value.map((row) => ({
    ...row,
    stays: row.stays.filter((s) => overlapsDay(s.start, s.end)).map((stay) => ({
      ...stay,
      style: {
        ...segmentStyle(stay.start, stay.end),
        background: venueColors.value.get(stay.venue_id),
      },
      tooltipTitle: stay.venue_name,
      tooltipTime: `${dateFmt.format(new Date(stay.start))} – ${dateFmt.format(new Date(stay.end))}`,
      tooltipLines: [
        `${stay.quantity} unité(s)`,
        stay.is_storage ? 'Lieu d\'entreposage' : 'Lieu de spectacle',
      ],
    })),
    marks: row.assignments.filter((a) => overlapsDay(a.start, a.end)).map((a) => ({
      ...a,
      style: segmentStyle(a.start, a.end),
      tooltipTitle: a.show_title,
      tooltipTime: `${dateFmt.format(new Date(a.start))} – ${dateFmt.format(new Date(a.end))}`,
      tooltipLines: [
        'Requis par un spectacle',
        `${a.venue_name} · ${a.quantity} unité(s)`,
      ],
    })),
    transports: (row.transports ?? []).filter((t) => overlapsDay(t.start, t.end)).map((t) => ({
      ...t,
      style: segmentStyle(t.start, t.end),
      tooltipTitle: `Déplacement — ${t.show_title}`,
      tooltipTime: `${dateFmt.format(new Date(t.start))} – ${dateFmt.format(new Date(t.end))}`,
      tooltipLines: [
        `${t.origin_venue_name} → ${t.destination_venue_name}`,
        `${t.quantity} unité(s)`,
      ],
    })),
  })),
)
</script>

<template>
  <AppShell>
    <div class="page">
      <div class="page-header">
        <h1 class="page-title">Parcours Matériel</h1>
        <div class="page-count">{{ selectedIds.length }} item(s) affiché(s)</div>
      </div>

      <div v-if="loadError" class="hint hint--error">
        Impossible de charger le parcours. Es-tu connecté (session Django) ?
      </div>
      <div v-else-if="!fenetre && !loading" class="hint">
        Ce projet n'a ni dates ni événement : il n'y a pas encore de période à afficher.
        Tu peux saisir les dates du projet dans les Réglages.
      </div>

      <div class="parcours">
        <div class="parcours-picker">
          <div class="parcours-picker__head">
            <div class="parcours-picker__title">Matériel</div>
            <button type="button" class="parcours-picker__link" @click="selectAll(visibleOptions)">
              Tout
            </button>
            <button type="button" class="parcours-picker__link" @click="selectNone">Aucun</button>
          </div>
          <div class="picker-filters">
            <span
              v-for="c in categoryChips"
              :key="c.key"
              class="picker-chip"
              :class="{ 'picker-chip--active': c.active }"
              @click="pickCategory(c.key, $event)"
            >
              <span v-if="c.color" class="picker-chip__dot" :style="{ background: c.color }" />
              {{ c.label }}
            </span>
          </div>
          <div class="picker-hint">⌘ + clic pour cumuler plusieurs catégories</div>
          <div v-if="visibleOptions.length === 0" class="picker-empty">
            Aucun matériel dans cette sélection.
          </div>
          <label
            v-for="o in visibleOptions"
            :key="o.id"
            class="parcours-option"
            :class="{ 'parcours-option--nested': o.nested }"
            @click.prevent="toggleOption(o)"
          >
            <span
              class="parcours-option__check"
              :class="{ 'parcours-option__check--on': selectedIds.includes(o.id) }"
            >{{ selectedIds.includes(o.id) ? '✓' : '' }}</span>
            <span class="parcours-option__name">{{ o.name }}</span>
            <span v-if="o.childCount > 0" class="parcours-option__badge">{{ o.childCount }}</span>
          </label>
        </div>

        <div class="parcours-board">
          <div v-if="loading" class="parcours-empty">Chargement…</div>
          <div v-else-if="decorated.length === 0" class="parcours-empty">
            Coche du matériel à gauche pour voir son parcours.
          </div>

          <template v-else>
            <ParcoursDayPicker
              :days="days"
              :selected-day-key="selectedDayKey"
              @select="selectDay"
              @step="stepDay"
            />

            <div class="parcours-axis">
              <div v-for="mark in hourMarks" :key="mark.key" class="parcours-axis__tick" :style="{ left: mark.left }">
                {{ mark.label }}
              </div>
            </div>

            <div v-for="row in decorated" :key="row.id" class="parcours-row">
              <div class="parcours-row__label">
                <div class="parcours-row__name">{{ row.name }}</div>
                <div class="parcours-row__meta">
                  {{ row.category_name ?? 'Sans catégorie' }} · origine {{ row.home_venue_name }}
                </div>
              </div>
              <div class="parcours-track">
                <div
                  v-for="mark in hourMarks"
                  :key="`grid-${mark.key}`"
                  class="parcours-gridline"
                  :style="{ left: mark.left }"
                />
                <div
                  v-for="(stay, i) in row.stays"
                  :key="`s${i}`"
                  class="parcours-seg"
                  :style="stay.style"
                >
                  <span class="parcours-seg__label">{{ stay.venue_name }}</span>
                  <div class="parcours-tooltip">
                    <div class="parcours-tooltip__title">{{ stay.tooltipTitle }}</div>
                    <div class="parcours-tooltip__time">{{ stay.tooltipTime }}</div>
                    <div v-for="(line, li) in stay.tooltipLines" :key="li" class="parcours-tooltip__line">
                      {{ line }}
                    </div>
                  </div>
                </div>
                <div
                  v-for="(mark, i) in row.marks"
                  :key="`m${i}`"
                  class="parcours-mark"
                  :style="mark.style"
                >
                  <div class="parcours-tooltip">
                    <div class="parcours-tooltip__title">{{ mark.tooltipTitle }}</div>
                    <div class="parcours-tooltip__time">{{ mark.tooltipTime }}</div>
                    <div v-for="(line, li) in mark.tooltipLines" :key="li" class="parcours-tooltip__line">
                      {{ line }}
                    </div>
                  </div>
                </div>
                <div
                  v-for="(t, i) in row.transports"
                  :key="`t${i}`"
                  class="parcours-transport"
                  :style="t.style"
                >
                  <div class="parcours-tooltip">
                    <div class="parcours-tooltip__title">{{ t.tooltipTitle }}</div>
                    <div class="parcours-tooltip__time">{{ t.tooltipTime }}</div>
                    <div v-for="(line, li) in t.tooltipLines" :key="li" class="parcours-tooltip__line">
                      {{ line }}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div class="legend">
              <span v-for="l in legend" :key="l.name" class="legend__item">
                <span class="legend__swatch" :style="{ background: l.color }" />{{ l.name }}
              </span>
              <span class="legend__item">
                <span class="legend__swatch legend__swatch--mark" />Requis par un spectacle
              </span>
              <span class="legend__item">
                <span class="legend__swatch legend__swatch--transport" />Déplacement confirmé
              </span>
            </div>
          </template>
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
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.page-count {
  font: 500 12px system-ui;
  color: rgba(255, 255, 255, 0.4);
}

.hint {
  font: 500 13px system-ui;
  color: rgba(255, 255, 255, 0.5);
}

.hint--error {
  color: oklch(0.78 0.16 35);
}

.picker-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.picker-chip {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 4px 8px;
  border-radius: 0 6px 0 6px;
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.55);
  font: 500 10.5px system-ui;
  cursor: pointer;
  white-space: nowrap;
}

.picker-chip--active {
  background: rgba(155, 138, 239, 0.2);
  color: var(--accent);
  font-weight: 600;
}

.picker-chip__dot {
  width: 7px;
  height: 7px;
  border-radius: 2px;
  flex: none;
}

/* Composant affiché en retrait sous son kit, avec le trait de raccordement —
   même lecture que l'inventaire et les modales d'assignation. */
.parcours-option--nested {
  position: relative;
  margin-left: 18px;
  border-left: 2px solid rgba(155, 138, 239, 0.25);
  padding-left: 10px;
}

.parcours-option--nested::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  width: 8px;
  height: 2px;
  background: rgba(155, 138, 239, 0.25);
}

/* Nombre de composants d'un kit, pour comprendre le regroupement sans avoir
   à compter les lignes en retrait. */
.parcours-option__badge {
  flex: none;
  min-width: 16px;
  padding: 1px 5px;
  border-radius: 0 5px 0 5px;
  background: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.4);
  font: 600 9.5px var(--font-mono);
  text-align: center;
}

.picker-hint {
  font: 400 10px system-ui;
  color: rgba(255, 255, 255, 0.25);
  padding: 2px 0 4px;
}

.picker-empty {
  padding: 10px 4px;
  font: 400 11.5px system-ui;
  color: rgba(255, 255, 255, 0.3);
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  padding-top: 8px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.legend__item {
  display: flex;
  align-items: center;
  gap: 6px;
  font: 400 11px system-ui;
  color: rgba(255, 255, 255, 0.45);
}

.legend__swatch {
  width: 12px;
  height: 10px;
  border-radius: 0 3px 0 3px;
}

.legend__swatch--mark {
  height: 3px;
  background: var(--accent);
}

.legend__swatch--transport {
  height: 3px;
  background: oklch(0.5 0.1 250);
}
</style>

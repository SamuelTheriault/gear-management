<script setup>
import { computed } from 'vue'
import AppShell from '../components/AppShell.vue'
import ParcoursDayPicker from '../components/ParcoursDayPicker.vue'
import { useParcours } from '../composables/useParcours'

/**
 * Parcours des techniciens (`/parcours/techniciens`, sous-menu du Tableau de
 * bord depuis le 2026-07-30) — pendant de
 * `ParcoursMaterielView`, ajouté le 2026-07-30.
 *
 * Une ligne par technicien, un bloc par engagement sur toute la durée du
 * projet. Spectacles et déplacements sont mélangés sur la même piste, dans
 * l'ordre chronologique : c'est exactement le croisement que fait déjà la
 * détection de conflit (`_technician_commitments`, conflicts.py), donc voir
 * les deux sur la même ligne rend le conflit lisible d'un coup d'œil.
 *
 * La fenêtre des spectacles est la fenêtre EFFECTIVE (buffers compris) —
 * même base que la détection de conflit, sinon deux blocs pourraient sembler
 * ne pas se toucher alors qu'ils sont en conflit.
 *
 * Affichage jour par jour (2026-07-31, demande de Samuel : « comme le
 * dashboard principal, avec des boutons de filtre pour sélectionner la
 * journée ») : une seule journée à la fois (axe 0h→24h), choisie via
 * `ParcoursDayPicker` — même composable/composant que `ParcoursMaterielView`.
 * Un engagement à cheval sur deux jours n'apparaît que pour sa portion dans
 * le jour affiché (`overlapsDay`).
 */

const {
  options, selectedIds, rows, window: fenetre, loading, loadError,
  days, selectedDayKey, selectDay, stepDay, hourMarks, overlapsDay,
  toggle, selectAll, selectNone, segmentStyle,
} = useParcours({
  endpoint: 'technician-journey',
  itemsKey: 'technicians',
  listEndpoint: '/technicians/',
  listParam: 'technicians',
})

const KIND_COLORS = {
  show: 'oklch(0.55 0.13 290)',
  transport: 'oklch(0.5 0.1 250)',
}

const dateFmt = new Intl.DateTimeFormat('fr-CA', {
  day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
})

const decorated = computed(() =>
  rows.value.map((row) => {
    const engagements = row.engagements.filter((e) => overlapsDay(e.start, e.end))
    return {
      ...row,
      blocks: engagements.map((e) => ({
        ...e,
        style: {
          ...segmentStyle(e.start, e.end),
          // Le conflit prime sur le type : c'est l'information à repérer.
          background: e.conflict ? 'oklch(0.5 0.16 25)' : KIND_COLORS[e.kind],
          border: e.conflict ? '1px solid oklch(0.7 0.16 25)' : 'none',
        },
        tooltipTitle: e.label,
        tooltipTime: `${dateFmt.format(new Date(e.start))} – ${dateFmt.format(new Date(e.end))}`,
        tooltipLines: [
          e.kind === 'show' ? 'Spectacle' : 'Déplacement',
          ...(e.conflict ? ['⚠ En conflit'] : []),
        ],
      })),
      engagementCount: engagements.length,
      conflictCount: engagements.filter((e) => e.conflict).length,
    }
  }),
)
</script>

<template>
  <AppShell>
    <div class="page">
      <div class="page-header">
        <h1 class="page-title">Parcours Technicien</h1>
        <div class="page-count">{{ selectedIds.length }} technicien(s) affiché(s)</div>
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
            <div class="parcours-picker__title">Techniciens</div>
            <button type="button" class="parcours-picker__link" @click="selectAll()">Tous</button>
            <button type="button" class="parcours-picker__link" @click="selectNone">Aucun</button>
          </div>
          <label v-for="o in options" :key="o.id" class="parcours-option" @click.prevent="toggle(o.id)">
            <span
              class="parcours-option__check"
              :class="{ 'parcours-option__check--on': selectedIds.includes(o.id) }"
            >{{ selectedIds.includes(o.id) ? '✓' : '' }}</span>
            <span class="parcours-option__name">{{ o.name }}</span>
          </label>
        </div>

        <div class="parcours-board">
          <div v-if="loading" class="parcours-empty">Chargement…</div>
          <div v-else-if="decorated.length === 0" class="parcours-empty">
            Coche des techniciens à gauche pour voir leur parcours.
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
                  {{ row.specialty || '—' }} · {{ row.engagementCount }} engagement(s)
                  <template v-if="row.conflictCount > 0"> · {{ row.conflictCount }} conflit(s)</template>
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
                  v-for="(b, i) in row.blocks"
                  :key="i"
                  class="parcours-seg"
                  :style="b.style"
                >
                  <span class="parcours-seg__label">{{ b.label }}</span>
                  <div class="parcours-tooltip">
                    <div class="parcours-tooltip__title">{{ b.tooltipTitle }}</div>
                    <div class="parcours-tooltip__time">{{ b.tooltipTime }}</div>
                    <div v-for="(line, li) in b.tooltipLines" :key="li" class="parcours-tooltip__line">
                      {{ line }}
                    </div>
                  </div>
                </div>
                <div v-if="row.blocks.length === 0" class="track-empty">Aucun engagement</div>
              </div>
            </div>

            <div class="legend">
              <span class="legend__item">
                <span class="legend__swatch" :style="{ background: KIND_COLORS.show }" />Spectacle
              </span>
              <span class="legend__item">
                <span class="legend__swatch" :style="{ background: KIND_COLORS.transport }" />Déplacement
              </span>
              <span class="legend__item">
                <span class="legend__swatch" style="background: oklch(0.5 0.16 25)" />En conflit
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

.track-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  padding-left: 10px;
  font: 400 10.5px system-ui;
  color: rgba(255, 255, 255, 0.25);
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
</style>

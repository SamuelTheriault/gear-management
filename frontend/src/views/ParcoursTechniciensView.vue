<script setup>
import { computed, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
import ParcoursDayPicker from '../components/ParcoursDayPicker.vue'
import ZoomControls from '../components/ZoomControls.vue'
import FloatingTooltip from '../components/FloatingTooltip.vue'
import { useParcours } from '../composables/useParcours'
import { useZoomScroll } from '../composables/useZoomScroll'
import { useFloatingTooltip } from '../composables/useFloatingTooltip'

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
 *
 * Zoom (2026-08-02, demande de Samuel) : `ZoomControls.vue` + l'état
 * correspondant vivent entièrement dans `useParcours.js` (partagé avec
 * `ParcoursMaterielView`) — cet écran n'a qu'à afficher les boutons et leur
 * passer les callbacks. « Réinitialiser » revient à la journée complète
 * (0h-24h), pas à un sous-ensemble — c'est `dayBounds`, pas `autoWindow`
 * façon Tableau de bord, qui n'a pas d'équivalent ici.
 *
 * Défilement horizontal sous zoom (2026-08-02, suite, demande de Samuel :
 * « se déplacer dans la vue ») : `pct`/`segmentStyle`/`hourMarks` restent
 * relatifs à la journée entière (voir `useParcours.js`) — c'est
 * `.parcours-scroll__content` qui s'élargit à `zoomLevel * 100 %` dans
 * `.parcours-scroll` (`overflow-x: auto`), rendant le déplacement natif
 * (molette/trackpad/barre) plutôt qu'un recalcul de fenêtre.
 * `useZoomScroll` repositionne ce défilement à chaque zoomIn/zoomOut/
 * resetZoom. Même structure à deux colonnes que `ParcoursMaterielView`
 * (étiquettes fixes, timeline scrollable) — voir sa note de tête pour le
 * détail, identique ici.
 *
 * Info-bulle flottante (2026-08-03, demande de Samuel) — même composable
 * `useFloatingTooltip` que `ParcoursMaterielView`/le Tableau de bord : évite
 * le clipping de `.parcours-scroll` (`overflow-x: auto`) qui piégeait
 * l'ancienne info-bulle CSS-only, voir `useFloatingTooltip.js`.
 */

const {
  options, selectedIds, rows, window: fenetre, loading, loadError,
  days, selectedDayKey, selectDay, stepDay, hourMarks, overlapsDay,
  toggle, selectAll, selectNone, segmentStyle,
  isZoomed, canZoomIn, canZoomOut, zoomIn, zoomOut, resetZoom,
  zoomLevel, scrollFraction,
} = useParcours({
  endpoint: 'technician-journey',
  itemsKey: 'technicians',
  listEndpoint: '/technicians/',
  listParam: 'technicians',
})

const scrollRef = ref(null)
useZoomScroll(scrollRef, zoomLevel, scrollFraction)

// Info-bulle flottante (2026-08-03) — voir la note de tête.
const { tooltip, show: showTooltip, hide: hideTooltip } = useFloatingTooltip()

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
            <div class="parcours-toolbar">
              <ParcoursDayPicker
                :days="days"
                :selected-day-key="selectedDayKey"
                @select="selectDay"
                @step="stepDay"
              />
              <ZoomControls
                :is-zoomed="isZoomed"
                :can-zoom-in="canZoomIn"
                :can-zoom-out="canZoomOut"
                @zoom-in="zoomIn"
                @zoom-out="zoomOut"
                @reset="resetZoom"
              />
            </div>

            <div class="parcours-timeline">
              <div class="parcours-labels">
                <div class="parcours-labels__spacer" />
                <div v-for="row in decorated" :key="`label-${row.id}`" class="parcours-row__label">
                  <div class="parcours-row__name">{{ row.name }}</div>
                  <div class="parcours-row__meta">
                    {{ row.specialty || '—' }} · {{ row.engagementCount }} engagement(s)
                    <template v-if="row.conflictCount > 0"> · {{ row.conflictCount }} conflit(s)</template>
                  </div>
                </div>
              </div>

              <div ref="scrollRef" class="parcours-scroll">
                <div class="parcours-scroll__content" :style="{ width: `${zoomLevel * 100}%` }">
                  <div class="parcours-axis">
                    <div v-for="mark in hourMarks" :key="mark.key" class="parcours-axis__tick" :style="{ left: mark.left }">
                      {{ mark.label }}
                    </div>
                  </div>

                  <div v-for="row in decorated" :key="`track-${row.id}`" class="parcours-track">
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
                      @mouseenter="showTooltip($event, { title: b.tooltipTitle, time: b.tooltipTime, lines: b.tooltipLines })"
                      @mouseleave="hideTooltip"
                    >
                      <span class="parcours-seg__label">{{ b.label }}</span>
                    </div>
                    <div v-if="row.blocks.length === 0" class="track-empty">Aucun engagement</div>
                  </div>
                </div>
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
    <FloatingTooltip :tooltip="tooltip" />
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
  color: rgba(var(--fg-rgb), 0.4);
}

.hint {
  font: 500 13px system-ui;
  color: rgba(var(--fg-rgb), 0.5);
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
  color: rgba(var(--fg-rgb), 0.25);
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  padding-top: 8px;
  border-top: 1px solid rgba(var(--fg-rgb), 0.06);
}

.legend__item {
  display: flex;
  align-items: center;
  gap: 6px;
  font: 400 11px system-ui;
  color: rgba(var(--fg-rgb), 0.45);
}

.legend__swatch {
  width: 12px;
  height: 10px;
  border-radius: 0 3px 0 3px;
}
</style>

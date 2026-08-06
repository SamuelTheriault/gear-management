<script setup>
/**
 * Info-bulle flottante partagée (2026-08-03) — voir `useFloatingTooltip.js`
 * pour le contexte complet (remplace l'ancienne info-bulle 100% CSS,
 * piégée par le clipping des conteneurs `overflow-x: auto` du Tableau de
 * bord et des deux Parcours).
 *
 * Un seul de ces composants par écran, positionné entièrement par l'état
 * réactif `tooltip` (produit par `useFloatingTooltip`). `position: fixed` +
 * `Teleport to="body"` : sort du DOM du conteneur qui l'a déclenché, donc
 * aucun ancêtre ne peut plus la rogner ni la faire défiler avec lui.
 */
defineProps({
  tooltip: { type: Object, required: true },
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="tooltip.visible"
      class="floating-tooltip"
      :class="`floating-tooltip--${tooltip.placement}`"
      :style="{ left: `${tooltip.x}px`, top: `${tooltip.y}px` }"
    >
      <div v-if="tooltip.title" class="floating-tooltip__title">{{ tooltip.title }}</div>
      <div v-if="tooltip.time" class="floating-tooltip__time">{{ tooltip.time }}</div>
      <div v-for="(line, i) in tooltip.lines ?? []" :key="i" class="floating-tooltip__line">
        {{ line }}
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.floating-tooltip {
  position: fixed;
  transform: translateX(-50%);
  min-width: 170px;
  max-width: 240px;
  padding: 10px 12px;
  border-radius: var(--radius-notch-sm);
  background: var(--bg-deep);
  border: 1px solid rgba(var(--fg-rgb), 0.12);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
  pointer-events: none;
  white-space: normal;
  z-index: 1000;
}

/* Bascule vers le haut (voir `useFloatingTooltip.show`) : `y` représente
   alors le bord INFÉRIEUR visé, il faut donc remonter toute la hauteur de
   l'info-bulle en plus du centrage horizontal. */
.floating-tooltip--top {
  transform: translate(-50%, -100%);
}

.floating-tooltip__title {
  font: 700 12px system-ui;
  color: rgb(var(--fg-rgb));
  margin-bottom: 4px;
}

.floating-tooltip__time {
  font: 600 11px system-ui;
  color: rgba(var(--fg-rgb), 0.63);
  margin-bottom: 6px;
}

.floating-tooltip__line {
  font: 500 11.5px system-ui;
  color: rgba(var(--fg-rgb), 0.75);
  line-height: 1.4;
}
</style>

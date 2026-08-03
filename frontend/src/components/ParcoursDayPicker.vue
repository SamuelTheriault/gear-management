<script setup>
/**
 * Sélecteur de journée partagé par les deux écrans « Parcours » (matériel et
 * techniciens), ajouté le 2026-07-31 à la demande de Samuel : afficher le
 * parcours jour par jour (comme une ligne du Dashboard) plutôt que tout le
 * projet sur un seul axe continu, avec des puces pour cibler la journée.
 *
 * Purement présentationnel — la logique (liste des jours, jour choisi,
 * navigation) vit dans `useParcours.js`, partagée par les deux vues.
 *
 * Depuis le 2026-08-02 (ajout du zoom), ce composant est posé à côté de
 * `ZoomControls.vue` dans un conteneur commun `.parcours-toolbar` (classe
 * globale, `style.css`) — c'est LUI qui porte désormais la séparation
 * visuelle (bordure/marge basse) sur toute la largeur de la ligne, pas
 * `.day-picker` qui ne couvrirait que sa propre portion.
 */
defineProps({
  days: { type: Array, required: true },
  selectedDayKey: { type: String, default: null },
})

const emit = defineEmits(['select', 'step'])
</script>

<template>
  <div class="day-picker">
    <button
      type="button"
      class="day-picker__nav"
      :disabled="days.length === 0 || days[0]?.key === selectedDayKey"
      @click="emit('step', -1)"
    >←</button>
    <div class="day-picker__chips">
      <span
        v-for="d in days"
        :key="d.key"
        class="day-picker__chip"
        :class="{ 'day-picker__chip--active': d.key === selectedDayKey }"
        @click="emit('select', d.key)"
      >{{ d.label }}</span>
    </div>
    <button
      type="button"
      class="day-picker__nav"
      :disabled="days.length === 0 || days[days.length - 1]?.key === selectedDayKey"
      @click="emit('step', 1)"
    >→</button>
  </div>
</template>

<style scoped>
.day-picker {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 220px;
}

.day-picker__nav {
  flex: none;
  width: 26px;
  height: 26px;
  border-radius: 0 6px 0 6px;
  background: rgba(var(--fg-rgb), 0.06);
  border: 1px solid rgba(var(--fg-rgb), 0.12);
  color: rgba(var(--fg-rgb), 0.7);
  font: 700 12px system-ui;
  cursor: pointer;
}

.day-picker__nav:disabled {
  opacity: 0.3;
  cursor: default;
}

.day-picker__chips {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.day-picker__chip {
  padding: 5px 11px;
  border-radius: 0 6px 0 6px;
  font: 600 11.5px system-ui;
  color: rgba(var(--fg-rgb), 0.55);
  background: rgba(var(--fg-rgb), 0.05);
  cursor: pointer;
  white-space: nowrap;
  text-transform: capitalize;
}

.day-picker__chip--active {
  background: rgba(var(--accent-rgb), 0.22);
  color: var(--accent);
  font-weight: 700;
}
</style>

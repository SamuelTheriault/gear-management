<script setup>
/**
 * Sélecteur de couleur réutilisable — même gabarit (aperçu + puces de
 * palette + sélecteur natif) que celui dupliqué sur `LieuDetailView.vue`
 * (`Venue.color`) et `CategoriesMaterielView.vue` (`MaterialCategory.color`).
 * Ajouté le 2026-08-02 pour les 6 couleurs de `Settings` (transport + types
 * de spectacle, voir `ReglagesView.vue`) : plutôt qu'une TROISIÈME copie de
 * ce bloc, cette fois-ci extrait en composant — les deux fiches existantes
 * ne sont pas touchées (pas demandé, pas dans la portée de ce changement).
 *
 * Contrairement à `Venue.color`, ces couleurs ne sont jamais vides : pas de
 * puce « ✕ Automatique » comme sur `LieuDetailView.vue`. À la place, une
 * puce « ✕ » TOUJOURS visible (`defaultValue`, 2026-08-02, demande de
 * Samuel : « un bouton par ligne entre le carré de sélection et la première
 * couleur ») remet le champ à sa valeur d'ORIGINE (celle du formulaire au
 * chargement, pas une réinitialisation en base) plutôt qu'à « rien ».
 */
import { VENUE_PALETTE } from '../constants/venuePalette'

const props = defineProps({
  modelValue: { type: String, required: true },
  defaultValue: { type: String, default: '' },
  palette: { type: Array, default: () => VENUE_PALETTE },
})
const emit = defineEmits(['update:modelValue'])

function set(value) {
  emit('update:modelValue', value)
}

// Valeur de départ du sélecteur natif (<input type="color">, qui n'accepte
// que du hex) — même limite que LieuDetailView.vue : sans rapport avec ce
// qui est réellement enregistré tant qu'on n'y touche pas.
function hexColor(c) {
  return /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(c) ? c : '#9b8aef'
}
</script>

<template>
  <div class="color-picker-row">
    <span class="color-preview" :style="{ background: modelValue }" />
    <div class="swatches">
      <button
        v-if="defaultValue"
        type="button"
        class="swatch swatch--reset"
        :class="{ 'swatch--reset-inactive': modelValue === defaultValue }"
        title="Réinitialiser à la couleur d'origine"
        @click="set(defaultValue)"
      >
        ✕
      </button>
      <button
        v-for="color in palette"
        :key="color"
        type="button"
        class="swatch"
        :class="{ 'swatch--active': modelValue === color }"
        :style="{ background: color }"
        :title="color"
        @click="set(color)"
      />
      <span class="swatch swatch--picker" title="Choisir une couleur personnalisée">
        <input
          type="color"
          class="swatch--picker__input"
          :value="hexColor(modelValue)"
          @input="set($event.target.value)"
        />
      </span>
    </div>
  </div>
</template>

<style scoped>
.color-preview {
  width: 28px;
  height: 28px;
  border-radius: 0 7px 0 7px;
  border: 1px solid var(--border-card);
  flex: none;
}

.color-picker-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.swatches {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.swatch {
  width: 26px;
  height: 26px;
  border-radius: 0 6px 0 6px;
  border: 2px solid transparent;
  cursor: pointer;
  padding: 0;
}

.swatch--active {
  border-color: rgb(var(--fg-rgb));
}

.swatch--reset {
  background: var(--bg-row);
  color: rgba(var(--fg-rgb), 0.53);
  font: 700 12px system-ui;
}

/* Déjà à la valeur d'origine — la puce reste cliquable (pas de v-if) mais
   s'atténue pour indiquer qu'elle n'aurait aucun effet. */
.swatch--reset-inactive {
  opacity: 0.35;
}

.swatch--picker {
  position: relative;
  overflow: hidden;
  background: conic-gradient(
    from 0deg,
    red, yellow, lime, cyan, blue, magenta, red
  );
}

.swatch--picker__input {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  padding: 0;
  border: none;
  opacity: 0;
  cursor: pointer;
}
</style>

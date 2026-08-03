<script setup>
/**
 * Contrôles de zoom partagés par les 3 écrans à axe horaire (Tableau de
 * bord, Parcours Matériel, Parcours Technicien) — ajouté le 2026-08-02 à la
 * demande de Samuel : voir le détail d'une journée chargée sans devoir
 * plisser les yeux sur des blocs de quelques minutes.
 *
 * Composant purement présentationnel : la logique de zoom (paliers, bornes,
 * fenêtre par défaut) vit dans `useParcours.js` pour les deux écrans
 * Parcours, et directement dans `DashboardView.vue` pour le Tableau de
 * bord — ce composant ne fait qu'émettre les trois intentions
 * (`zoom-in`/`zoom-out`/`reset`) et refléter l'état (`disabled` sur chaque
 * bouton) que le parent lui donne.
 *
 * Le libellé du bouton Réinitialiser reste générique ; ce que « toute la
 * page » signifie diffère par écran (journée complète 0h-24h pour les
 * Parcours, du premier au dernier événement pour le Tableau de bord) — c'est
 * au parent de le documenter, pas à ce composant.
 */
defineProps({
  canZoomIn: { type: Boolean, default: true },
  canZoomOut: { type: Boolean, default: true },
  isZoomed: { type: Boolean, default: false },
})
defineEmits(['zoom-in', 'zoom-out', 'reset'])
</script>

<template>
  <div class="zoom-controls">
    <button
      type="button"
      class="zoom-btn"
      :disabled="!canZoomOut"
      title="Zoom arrière"
      @click="$emit('zoom-out')"
    >−</button>
    <button
      type="button"
      class="zoom-btn zoom-btn--reset"
      :disabled="!isZoomed"
      @click="$emit('reset')"
    >Réinitialiser le zoom</button>
    <button
      type="button"
      class="zoom-btn"
      :disabled="!canZoomIn"
      title="Zoom avant"
      @click="$emit('zoom-in')"
    >+</button>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { useEscapeKey } from '../composables/useEscapeKey'

/**
 * Fenêtre affichée quand on tente de quitter une fiche en cours d'édition
 * (2026-08-05) — voir `useLeaveGuard.js` pour la logique.
 *
 * Deux issues, comme demandé par Samuel : rester sur la page, ou enregistrer
 * puis continuer. Pas de « quitter sans enregistrer ».
 *
 * Échap et le clic sur le fond équivalent à « rester » : ce sont les gestes
 * d'annulation habituels, et ici annuler veut dire « ne pas quitter ». Le
 * choix destructeur, lui, n'existe pas.
 *
 * Composant partagé par les cinq fiches plutôt qu'un bloc de markup recopié
 * — même raison que `.fiche-confirm` : cinq copies auraient divergé.
 */
const props = defineProps({
  visible: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
  error: { type: String, default: null },
})
const emit = defineEmits(['stay', 'save'])

const router = useRouter()

useEscapeKey(() => {
  if (props.visible && !props.saving) emit('stay')
})

function onSave() {
  emit('save', router)
}
</script>

<template>
  <div v-if="visible" class="fiche-confirm-backdrop" @click.self="!saving && emit('stay')">
    <div class="fiche-confirm">
      <div class="fiche-confirm__title">Modifications non enregistrées</div>
      <p class="fiche-confirm__text">
        Cette fiche est en cours d'édition. Enregistre pour continuer, ou reste
        sur la page pour poursuivre tes modifications.
      </p>
      <div v-if="error" class="fiche-error">{{ error }}</div>
      <div class="fiche-confirm__actions">
        <button type="button" class="fiche-btn" :disabled="saving" @click="emit('stay')">
          Rester sur la page
        </button>
        <button
          type="button"
          class="fiche-btn fiche-btn--primary"
          :disabled="saving"
          @click="onSave"
        >
          {{ saving ? 'Enregistrement…' : 'Enregistrer et continuer' }}
        </button>
      </div>
    </div>
  </div>
</template>

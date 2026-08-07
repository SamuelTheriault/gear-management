<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { api } from '../api/client'

/**
 * Champ adresse avec suggestions Google Places (2026-08-07, demande de
 * Samuel — dans la foulée du géocodage automatique) : proposer les adresses
 * possibles en menu déroulant pendant la saisie, pour des adresses propres
 * dès la source. Utilisé par la fiche Lieu (édition) et le formulaire de
 * création de LieuxView.
 *
 * Les suggestions viennent du backend (`GET /venues/address-autocomplete/`,
 * qui relaie Places Autocomplete New — la clé Google ne quitte jamais le
 * serveur). Débounce de 300 ms, déclenché à partir de 4 caractères ; un
 * jeton écarte les réponses arrivées en retard (même garde-fou que
 * l'estimation de trajet du formulaire Transports). Si l'API ne répond pas
 * (clé absente, Places non activée), le champ reste un simple champ texte —
 * la dégradation est invisible, pas un message d'erreur.
 *
 * `inputClass` transmet les classes du champ hôte (`fiche-input`,
 * `add-form__input`, variantes d'erreur) : le composant n'impose aucun
 * style d'input, seulement le menu déroulant.
 */

const props = defineProps({
  modelValue: { type: String, default: '' },
  inputClass: { type: [String, Object, Array], default: '' },
  placeholder: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue'])

const suggestions = ref([])
const open = ref(false)
let timer = null
let requestToken = 0
// Après un choix dans le menu, le modelValue change : ce changement-là ne
// doit pas rouvrir le menu avec une nouvelle recherche.
let suppressNextSearch = false

watch(
  () => props.modelValue,
  (query) => {
    if (suppressNextSearch) {
      suppressNextSearch = false
      return
    }
    clearTimeout(timer)
    if (!query || query.trim().length < 4) {
      suggestions.value = []
      open.value = false
      return
    }
    timer = setTimeout(async () => {
      const mine = ++requestToken
      try {
        const data = await api.get('/venues/address-autocomplete/', { q: query.trim() })
        if (mine !== requestToken) return
        suggestions.value = data.suggestions ?? []
        open.value = suggestions.value.length > 0
      } catch {
        suggestions.value = []
        open.value = false
      }
    }, 300)
  },
)

function pick(suggestion) {
  suppressNextSearch = true
  emit('update:modelValue', suggestion)
  suggestions.value = []
  open.value = false
}

onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <div class="addr">
    <input
      :value="modelValue"
      :class="inputClass"
      :placeholder="placeholder"
      autocomplete="off"
      @input="emit('update:modelValue', $event.target.value)"
      @blur="open = false"
      @keydown.escape="open = false"
    />
    <!-- mousedown.prevent : le choix doit passer AVANT le blur de l'input,
         sinon le menu se ferme sous le clic. -->
    <div v-if="open" class="addr__list">
      <div
        v-for="s in suggestions"
        :key="s"
        class="addr__item"
        @mousedown.prevent="pick(s)"
      >
        {{ s }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.addr {
  position: relative;
}

.addr :deep(input) {
  width: 100%;
}

.addr__list {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  z-index: 30;
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: 0 10px 0 10px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
  overflow: hidden;
}

.addr__item {
  padding: 9px 12px;
  font: 500 12.5px system-ui;
  color: rgba(var(--fg-rgb), 0.82);
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.addr__item:hover {
  background: color-mix(in oklab, var(--transport) 14%, transparent);
  color: rgb(var(--fg-rgb));
}

.addr__item + .addr__item {
  border-top: 1px solid rgba(var(--fg-rgb), 0.06);
}
</style>

<script setup>
import { ref, computed, watch } from 'vue'
import AppShell from '../components/AppShell.vue'
import { api } from '../api/client'
import { useActiveProject } from '../composables/useActiveProject'
import { VENUE_PALETTE } from '../constants/venuePalette'

/**
 * Liste des lieux — port de Lieux.dc.html, branché sur l'API réelle
 * (/api/venues/). Voir schema.md section 2 pour les champs de `Venue`
 * (contact_name/contact_info séparés côté modèle, `code` optionnel et unique
 * par projet — voir `VenueSerializer.validate_code`).
 *
 * Tag du code court coloré (2026-08-02, demande de Samuel) : reprend la
 * couleur du lieu (`Venue.color`, voir LieuDetailView.vue) — même
 * `autoPreviewColor()` que la fiche pour un aperçu en mode Automatique
 * (dupliqué faute de composant partagé, même limite documentée là-bas : un
 * aperçu plausible, pas la couleur exacte du Parcours Matériel). Un
 * entrepôt SANS couleur fixée garde le badge neutre d'origine plutôt que la
 * teinte grise translucide de l'aperçu — celle-ci est trop pâle pour rester
 * lisible comme couleur de TEXTE.
 */

const { activeProjectId } = useActiveProject()

const venues = ref([])
const loading = ref(false)
const loadError = ref(null)

async function loadVenues() {
  if (!activeProjectId.value) return
  loading.value = true
  loadError.value = null
  try {
    const data = await api.get('/venues/', { project: activeProjectId.value })
    venues.value = Array.isArray(data) ? data : (data.results ?? [])
  } catch (e) {
    loadError.value = e
  } finally {
    loading.value = false
  }
}

watch(activeProjectId, loadVenues, { immediate: true })

// Aperçu déterministe par id — voir la note de tête du module et
// LieuDetailView.vue pour la limite (approximation, pas la couleur exacte
// du Parcours Matériel, qui cycle par ordre d'apparition dans les données).
function autoPreviewColor(v) {
  return VENUE_PALETTE[v.id % VENUE_PALETTE.length]
}

const decorated = computed(() =>
  venues.value.map((v) => ({
    ...v,
    tag: v.is_storage ? 'Entrepôt' : 'Salle',
    tagColor: v.is_storage ? 'rgba(var(--fg-rgb),.6)' : 'oklch(0.75 0.13 320)',
    tagBg: v.is_storage ? 'rgba(var(--fg-rgb),.08)' : 'oklch(0.75 0.13 320 / .16)',
    // Entrepôt sans couleur fixée : `null` retombe sur le badge neutre
    // d'origine (voir `.card-code`) plutôt que le gris translucide de
    // l'aperçu, illisible comme couleur de texte.
    venueColor: v.color || (v.is_storage ? null : autoPreviewColor(v)),
    contact: [v.contact_name, v.contact_info].filter(Boolean).join(' · ') || '—',
  })),
)

// --- Ajout rapide d'un lieu ---

const form = ref({
  name: '',
  code: '',
  address: '',
  contact_name: '',
  contact_info: '',
  is_storage: false,
})
const formError = ref(null)
const nameError = ref(false)
const submitting = ref(false)

const canSubmit = computed(() => form.value.name.trim().length > 0 && !submitting.value)

// Le backend normalise déjà `code` en majuscules à l'enregistrement
// (Venue.save()) ; on le fait aussi à la saisie pour que le champ montre
// tout de suite ce qui sera stocké.
function onCodeInput(event) {
  form.value.code = event.target.value.toUpperCase().slice(0, 4)
}

async function addVenue() {
  formError.value = null
  const name = form.value.name.trim()
  if (!name) {
    nameError.value = true
    return
  }
  submitting.value = true
  try {
    await api.post('/venues/', {
      project: activeProjectId.value,
      name,
      code: form.value.code.trim(),
      address: form.value.address.trim(),
      contact_name: form.value.contact_name.trim(),
      contact_info: form.value.contact_info.trim(),
      is_storage: form.value.is_storage,
    })
    form.value = { name: '', code: '', address: '', contact_name: '', contact_info: '', is_storage: false }
    nameError.value = false
    await loadVenues()
  } catch (e) {
    // `validate_code` renvoie une erreur de champ (clé `code`), pas un
    // `detail` global — ex. code déjà pris par un autre lieu du projet.
    formError.value =
      e.data?.code?.[0] ?? e.data?.detail ?? "Impossible d'enregistrer le lieu."
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <AppShell>
    <div class="page">
      <div class="page-header">
        <h1 class="page-title">Lieux</h1>
        <div class="page-count">{{ decorated.length }} lieu(x)</div>
      </div>

      <div v-if="loading" class="hint">Chargement…</div>
      <div v-else-if="loadError" class="hint hint--error">
        Impossible de charger les lieux. Es-tu connecté (session Django) ?
      </div>

      <template v-else>
        <div v-if="decorated.length > 0" class="grid">
          <div v-for="v in decorated" :key="v.id" class="card">
            <div class="card-top">
              <div class="card-name" :title="v.name">
                <span
                  v-if="v.code"
                  class="card-code"
                  :style="v.venueColor ? {
                    background: `color-mix(in oklch, ${v.venueColor} 65%, transparent)`,
                    color: '#fff',
                  } : {}"
                >{{ v.code }}</span>{{ v.name }}
              </div>
              <div class="card-tag" :style="{ color: v.tagColor, background: v.tagBg }">{{ v.tag }}</div>
            </div>
            <div class="card-address">{{ v.address || 'Adresse non renseignée' }}</div>
            <div class="card-bottom">
              <div class="card-contact">Contact : {{ v.contact }}</div>
              <RouterLink :to="`/lieux/${v.id}`" class="card-link">Voir la fiche →</RouterLink>
            </div>
          </div>
        </div>
        <div v-else class="empty">
          <div class="empty__icon" />
          <div class="empty__title">Aucun lieu pour ce projet</div>
        </div>
      </template>

      <div class="add-form">
        <div class="add-form__title">Ajouter un lieu</div>
        <div class="add-form__row">
          <label class="add-form__field add-form__field--wide">
            <span class="add-form__label">Nom du lieu</span>
            <input
              v-model="form.name"
              placeholder="ex. Chapelle historique"
              class="add-form__input"
              :class="{ 'add-form__input--error': nameError }"
              @input="nameError = false"
            />
          </label>
          <label class="add-form__field add-form__field--code">
            <span class="add-form__label">Code</span>
            <input
              :value="form.code"
              placeholder="4 car."
              maxlength="4"
              class="add-form__input add-form__input--code"
              @input="onCodeInput"
            />
          </label>
          <label class="add-form__field add-form__field--wide">
            <span class="add-form__label">Adresse</span>
            <input v-model="form.address" class="add-form__input" />
          </label>
          <label class="add-form__field">
            <span class="add-form__label">Contact sur place</span>
            <input v-model="form.contact_name" class="add-form__input" />
          </label>
          <label class="add-form__field">
            <span class="add-form__label">Type</span>
            <select v-model="form.is_storage" class="add-form__input">
              <option :value="false">Salle</option>
              <option :value="true">Entrepôt</option>
            </select>
          </label>
          <div
            class="add-form__submit"
            :class="{ 'add-form__submit--disabled': !canSubmit }"
            @click="canSubmit && addVenue()"
          >
            + Ajouter
          </div>
        </div>
        <div v-if="nameError" class="add-form__error">Le nom du lieu est requis.</div>
        <div v-if="formError" class="add-form__error">{{ formError }}</div>
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
  color: rgba(var(--fg-rgb), 0.4);
}

.hint {
  font: 500 13px system-ui;
  color: rgba(var(--fg-rgb), 0.5);
}

.hint--error {
  color: oklch(0.78 0.16 35);
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 14px;
}

.card {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-notch-lg);
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.card-name {
  font: 600 15px var(--font-mono);
  color: rgb(var(--fg-rgb));
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.card-tag {
  font: 700 10px system-ui;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 3px 9px;
  border-radius: 0 6px 0 6px;
  white-space: nowrap;
  flex: none;
}

.card-code {
  display: inline-block;
  margin-right: 8px;
  padding: 2px 6px;
  border-radius: 0 5px 0 5px;
  background: rgba(var(--fg-rgb), 0.08);
  font: 700 10.5px var(--font-mono);
  letter-spacing: 0.06em;
  color: rgba(var(--fg-rgb), 0.65);
  vertical-align: 1px;
}

.card-address {
  font: 400 12.5px system-ui;
  color: rgba(var(--fg-rgb), 0.5);
}

.card-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 4px;
}

.card-contact {
  font: 400 12px system-ui;
  color: rgba(var(--fg-rgb), 0.4);
}

.card-link {
  font: 600 11px system-ui;
  color: var(--link);
  cursor: pointer;
  white-space: nowrap;
  text-decoration: none;
}

.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 64px 20px;
  background: var(--bg-card);
  border: 1px dashed rgba(var(--fg-rgb), 0.15);
  border-radius: var(--radius-notch-lg);
}

.empty__icon {
  width: 40px;
  height: 40px;
  border-radius: 0 10px 0 10px;
  background: rgba(var(--fg-rgb), 0.06);
}

.empty__title {
  font: 600 13px system-ui;
  color: rgba(var(--fg-rgb), 0.6);
}

</style>

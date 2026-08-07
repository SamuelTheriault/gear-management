<script setup>
import { ref, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppShell from '../components/AppShell.vue'
import AdresseAutocomplete from '../components/AdresseAutocomplete.vue'
import LeaveEditPrompt from '../components/LeaveEditPrompt.vue'
import { api } from '../api/client'
import { useFicheEdition } from '../composables/useFicheEdition'
import { useSuppressionFiche } from '../composables/useSuppressionFiche'
import { VENUE_PALETTE } from '../constants/venuePalette'

/**
 * Fiche lieu — port de LieuDetail.dc.html, branché sur l'API réelle
 * (/api/venues/{id}/, /api/shows/?project=). La carte embarquée utilise les
 * coordonnées GPS du lieu si elles sont renseignées (voir `Venue.latitude`/
 * `longitude`, utilisées aussi par l'estimation Google Routes du module
 * transport — maps.py), sinon retombe sur une recherche par adresse.
 *
 * Couleur des bandes (2026-08-02, demande de Samuel) : `Venue.color`
 * (optionnel, vide par défaut) permet de fixer la teinte utilisée pour ce
 * lieu sur le Parcours Matériel — voir ParcoursMaterielView.vue,
 * `venueColorOverrides`. Vide = comportement inchangé, génération
 * automatique. Le sélecteur pioche dans `VENUE_PALETTE`
 * (constants/venuePalette.js), la MÊME palette que la génération
 * automatique — Samuel a explicitement demandé de garder cette dernière
 * telle quelle, pas d'en proposer une différente pour le choix manuel.
 *
 * Aperçu + sélecteur natif (2026-08-02, suite, demande de Samuel) : une
 * pastille `.color-preview` affiche la couleur réellement retenue (lecture
 * ET édition), pas seulement le contour des puces de palette — nécessaire
 * dès qu'une couleur ne vient PAS de `VENUE_PALETTE`. Un `<input
 * type="color">` (`.swatch--picker`) s'ajoute aux puces pour choisir une
 * teinte libre, hors palette — `draft.color` devient alors une chaîne hex,
 * pas `oklch(...)` ; `hexColor()` ne sert qu'à donner une valeur de départ
 * valide au picker natif (qui ne comprend pas `oklch`), il n'altère jamais
 * `draft.color` lui-même.
 *
 * Aperçu même en mode Automatique (2026-08-02, suite, demande de Samuel :
 * « la couleur n'est pas affichée en mode auto ») : `autoPreviewColor()`
 * calcule une teinte à afficher quand `color` est vide, par
 * `venue.id % VENUE_PALETTE.length` — stable et déterministe, mais À NE PAS
 * CONFONDRE avec la couleur RÉELLEMENT utilisée sur le Parcours Matériel
 * (`venueColorOverrides`/cycle par ORDRE D'APPARITION dans les données
 * affichées, voir ParcoursMaterielView.vue) : cette dernière dépend de quels
 * lieux apparaissent ce jour-là et dans quel ordre chronologique, une donnée
 * que cette fiche n'a pas. C'est un aperçu plausible, pas une garantie de
 * correspondance exacte — seule une couleur FIXÉE (non vide) est garantie
 * identique partout.
 *
 * Icône de sélecteur (2026-08-02, suite, demande de Samuel : « montrer
 * l'icône de dégradé de couleur et de hue ») : `<input type="color">`
 * n'affiche par défaut que sa valeur courante (un carré uni), pas une icône
 * de sélecteur. `.swatch--picker` superpose donc un `<input>` NATIF
 * invisible (`opacity: 0`, mais toujours cliquable et fonctionnel) par-
 * dessus un dégradé conique (roue de teintes) posé en fond — l'utilisateur
 * voit une icône « roue de couleurs », mais clique bien sur le vrai
 * sélecteur système en dessous.
 */

const route = useRoute()

const venue = ref(null)
const shows = ref([])
const loading = ref(false)
const loadError = ref(null)

const dateFmt = new Intl.DateTimeFormat('fr-CA', { weekday: 'short', day: 'numeric', month: 'short' })
const timeFmt = new Intl.DateTimeFormat('fr-CA', { hour: '2-digit', minute: '2-digit', hour12: false })

async function loadVenue() {
  const id = route.params.id
  loading.value = true
  loadError.value = null
  try {
    venue.value = await api.get(`/venues/${id}/`)

    const showsData = await api.get('/shows/', { project: venue.value.project })
    const rawShows = Array.isArray(showsData) ? showsData : (showsData.results ?? [])
    // Tous les spectacles de ce lieu, passés compris (2026-08-05) : le filtre
    // « fin >= maintenant » qui traînait ici vidait la carte dès que la
    // production était terminée, alors que la fiche sert justement à
    // consulter ce qui s'y est joué.
    const atThisVenue = rawShows
      .filter((s) => s.venue === Number(id))
      .sort((a, b) => new Date(a.start_datetime) - new Date(b.start_datetime))

    const withConflicts = await Promise.all(
      atThisVenue.map(async (s) => {
        try {
          const c = await api.get(`/shows/${s.id}/conflicts/`)
          const conflict =
            (c.venue_conflicts?.length ?? 0) +
              (c.material_conflicts?.length ?? 0) +
              (c.technician_conflicts?.length ?? 0) >
            0
          return { ...s, conflict }
        } catch {
          return { ...s, conflict: false }
        }
      }),
    )
    shows.value = withConflicts
  } catch (e) {
    loadError.value = e
  } finally {
    loading.value = false
  }
}

watch(() => route.params.id, loadVenue, { immediate: true })

const decoratedShows = computed(() =>
  shows.value.map((s) => {
    const start = new Date(s.start_datetime)
    const end = new Date(s.end_datetime)
    return {
      ...s,
      // `display_title` et non `title` (2026-08-05) : depuis que le nom d'un
      // bloc est généré (« Montage — Vertiges », voir `Show.display_title`),
      // `title` ne porte plus qu'une précision facultative — vide la plupart
      // du temps. La liste affichait donc des lignes sans nom dès qu'un
      // montage ou un démontage s'y trouvait.
      label: s.display_title || s.title,
      date: dateFmt.format(start),
      time: `${timeFmt.format(start)}–${timeFmt.format(end)}`,
      dot: s.conflict ? 'oklch(0.7 0.16 35)' : 'oklch(0.72 0.13 165)',
    }
  }),
)

// --- Édition de la fiche (voir schema.md section 2) ---
// Le bouton Modifier vit dans l'entête et bascule TOUTE la fiche en édition
// (un seul PATCH à l'enregistrement) — voir useFicheEdition pour le détail
// du pattern, commun à toutes les fiches. `project` n'est volontairement pas
// éditable : changer un lieu de projet casserait les spectacles/matériel/
// transports qui le référencent.

const {
  editing, draft, saving, saveError, fieldErrors, canSave,
  startEdit, cancelEdit, save: saveVenue,
  leavePrompt, leaveSaving, leaveError, stayOnPage, saveAndLeave,
} = useFicheEdition({
  entity: venue,
  endpoint: '/venues',
  fields: [
    'name', 'code', 'address', 'contact_name', 'contact_info',
    'notes', 'is_storage', 'latitude', 'longitude', 'color',
  ],
  errorMessage: 'Impossible d’enregistrer le lieu.',
  toDraft: (v) => ({
    name: v.name ?? '',
    code: v.code ?? '',
    address: v.address ?? '',
    contact_name: v.contact_name ?? '',
    contact_info: v.contact_info ?? '',
    notes: v.notes ?? '',
    is_storage: Boolean(v.is_storage),
    // Le backend renvoie des DecimalField sérialisés en chaîne — on garde
    // la chaîne telle quelle dans le formulaire et on ne convertit qu'à
    // l'envoi (voir toPayload).
    latitude: v.latitude ?? '',
    longitude: v.longitude ?? '',
    // '' = pas de couleur fixée, génération automatique (voir la note de
    // tête du module).
    color: v.color ?? '',
  }),
  isValid: (d) => d.name.trim().length > 0,
  toPayload: (d) => ({
    name: d.name.trim(),
    code: d.code.trim(),
    address: d.address.trim(),
    contact_name: d.contact_name.trim(),
    contact_info: d.contact_info.trim(),
    notes: d.notes.trim(),
    is_storage: d.is_storage,
    // latitude/longitude sont nullables côté modèle : un champ vidé doit
    // renvoyer `null`, pas la chaîne vide (que DRF refuserait sur un
    // DecimalField).
    latitude: String(d.latitude).trim() === '' ? null : d.latitude,
    longitude: String(d.longitude).trim() === '' ? null : d.longitude,
    color: d.color,
  }),
})

// Valeur de départ du sélecteur natif (<input type="color">, qui n'accepte
// que du hex) — sans rapport avec ce qui est réellement enregistré tant que
// l'utilisateur n'y touche pas : une puce de palette reste `oklch(...)`.
function hexColor(c) {
  return /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(c) ? c : '#9b8aef'
}

// Aperçu affiché quand aucune couleur n'est fixée (mode Automatique) — voir
// la note de tête du module pour la limite de cet aperçu (approximation,
// pas la couleur exacte du Parcours Matériel).
function autoPreviewColor({ id, is_storage }) {
  if (is_storage) return 'rgba(var(--fg-rgb),.12)'
  return VENUE_PALETTE[id % VENUE_PALETTE.length]
}

// Normalisation majuscules à la saisie — le backend fait la même chose à
// l'enregistrement (Venue.save()).
function onCodeInput(event) {
  draft.value.code = event.target.value.toUpperCase().slice(0, 4)
}

// --- Suppression (2026-07-30) ---
// Refusée côté serveur tant que le lieu est référencé par un spectacle, un
// déplacement ou du matériel — voir VenueViewSet.destroy.
const {
  confirming, deleting, deleteError, askDelete, cancelDelete, confirmDelete,
} = useSuppressionFiche({ endpoint: '/venues', redirectTo: '/lieux',
  beforeRedirect: () => cancelEdit(),
})

// Changer de lieu sans quitter la vue ne doit pas conserver un formulaire
// à moitié rempli sur le lieu précédent.
watch(() => route.params.id, cancelEdit)

const mapSrc = computed(() => {
  if (!venue.value) return null
  const { latitude, longitude, address, name } = venue.value
  if (latitude != null && longitude != null) {
    return `https://maps.google.com/maps?q=${latitude},${longitude}&output=embed`
  }
  if (address) {
    return `https://maps.google.com/maps?q=${encodeURIComponent(address)}&output=embed`
  }
  return null
})
</script>

<template>
  <AppShell>
    <div v-if="loading" class="hint">Chargement…</div>
    <div v-else-if="loadError" class="hint hint--error">
      Impossible de charger ce lieu. Es-tu connecté (session Django) ?
    </div>

    <div v-else-if="venue" class="page">
      <div class="breadcrumb"><RouterLink to="/lieux">Lieux</RouterLink> / {{ venue.name }}</div>

      <div class="header">
        <h1 class="header__title">{{ venue.name }}</h1>
        <div class="header__tag" :style="venue.is_storage
          ? { color: 'rgba(var(--fg-rgb),.6)', background: 'rgba(var(--fg-rgb),.08)' }
          : { color: 'oklch(0.75 0.13 320)', background: 'oklch(0.75 0.13 320 / .16)' }">
          {{ venue.is_storage ? 'Entrepôt' : 'Salle' }}
        </div>
        <div class="fiche-actions">
          <button v-if="!editing" type="button" class="fiche-btn" @click="startEdit">
            Modifier la fiche
          </button>
          <template v-else>
            <button
              type="button"
              class="fiche-btn fiche-btn--primary"
              :disabled="!canSave"
              @click="saveVenue()"
            >
              {{ saving ? 'Enregistrement…' : 'Enregistrer' }}
            </button>
            <button type="button" class="fiche-btn" :disabled="saving" @click="cancelEdit">
              Annuler
            </button>
          </template>
        </div>
      </div>

      <!-- Mode lecture -->
      <div v-if="!editing" class="card info-grid">
        <div class="info-col">
          <div>
            <div class="info-label">Adresse</div>
            <div class="info-value">{{ venue.address || '—' }}</div>
          </div>
          <div>
            <div class="info-label">Contact sur place</div>
            <div class="info-value">{{ venue.contact_name || '—' }}</div>
          </div>
          <div>
            <div class="info-label">Coordonnées</div>
            <div class="info-value">{{ venue.contact_info || '—' }}</div>
          </div>
          <div>
            <div class="info-label">Code court</div>
            <div class="info-value info-value--code">
              <span v-if="venue.code" class="code-badge">{{ venue.code }}</span>
              <span v-else class="code-empty">Aucun code</span>
            </div>
          </div>
          <div>
            <div class="info-label">Couleur (Parcours Matériel)</div>
            <div class="info-value info-value--code">
              <span
                class="color-preview"
                :style="{ background: venue.color || autoPreviewColor(venue) }"
              />
              <span>{{ venue.color ? 'Personnalisée' : 'Automatique' }}</span>
            </div>
          </div>
          <div v-if="venue.latitude != null && venue.longitude != null">
            <div class="info-label">GPS</div>
            <div class="info-value info-value--mono">{{ venue.latitude }}, {{ venue.longitude }}</div>
          </div>
        </div>
        <iframe
          v-if="mapSrc"
          :title="`Carte — ${venue.name}`"
          :src="mapSrc"
          class="map"
          loading="lazy"
        />
        <div v-else class="map map--empty">Aucune adresse ni coordonnée renseignée.</div>
      </div>

      <!-- Mode édition : un seul PATCH à l'enregistrement -->
      <div v-else class="fiche-edit-card">
        <div class="fiche-grid">
          <label class="fiche-field fiche-field--wide">
            <span class="fiche-label">Nom du lieu</span>
            <input v-model="draft.name" class="fiche-input" :class="{ 'fiche-input--error': fieldErrors.name }" />
            <span v-if="fieldErrors.name" class="fiche-error">{{ fieldErrors.name }}</span>
          </label>

          <label class="fiche-field">
            <span class="fiche-label">Code court (4 car.)</span>
            <input
              :value="draft.code"
              maxlength="4"
              placeholder="ex. CHAP"
              class="fiche-input fiche-input--code"
              :class="{ 'fiche-input--error': fieldErrors.code }"
              @input="onCodeInput"
            />
            <span v-if="fieldErrors.code" class="fiche-error">{{ fieldErrors.code }}</span>
          </label>

          <label class="fiche-field">
            <span class="fiche-label">Type</span>
            <select v-model="draft.is_storage" class="fiche-input">
              <option :value="false">Salle</option>
              <option :value="true">Entrepôt</option>
            </select>
          </label>

          <label class="fiche-field fiche-field--wide">
            <span class="fiche-label">Adresse</span>
            <!-- Suggestions Google Places pendant la saisie (2026-08-07) —
                 voir AdresseAutocomplete.vue. -->
            <AdresseAutocomplete
              v-model="draft.address"
              :input-class="['fiche-input', { 'fiche-input--error': fieldErrors.address }]"
            />
            <span v-if="fieldErrors.address" class="fiche-error">{{ fieldErrors.address }}</span>
          </label>

          <label class="fiche-field">
            <span class="fiche-label">Contact sur place</span>
            <input v-model="draft.contact_name" class="fiche-input" />
          </label>

          <label class="fiche-field">
            <span class="fiche-label">Coordonnées du contact</span>
            <input v-model="draft.contact_info" class="fiche-input" placeholder="Téléphone / courriel" />
          </label>

          <label class="fiche-field">
            <span class="fiche-label">Latitude</span>
            <input
              v-model="draft.latitude"
              inputmode="decimal"
              placeholder="45.508888"
              class="fiche-input fiche-input--mono"
              :class="{ 'fiche-input--error': fieldErrors.latitude }"
            />
            <span v-if="fieldErrors.latitude" class="fiche-error">{{ fieldErrors.latitude }}</span>
          </label>

          <label class="fiche-field">
            <span class="fiche-label">Longitude</span>
            <input
              v-model="draft.longitude"
              inputmode="decimal"
              placeholder="-73.561668"
              class="fiche-input fiche-input--mono"
              :class="{ 'fiche-input--error': fieldErrors.longitude }"
            />
            <span v-if="fieldErrors.longitude" class="fiche-error">{{ fieldErrors.longitude }}</span>
          </label>

          <label class="fiche-field fiche-field--full">
            <span class="fiche-label">Couleur (bandes du Parcours Matériel)</span>
            <div class="color-picker-row">
              <span
                class="color-preview"
                :style="{ background: draft.color || autoPreviewColor({ id: venue.id, is_storage: draft.is_storage }) }"
              />
              <div class="swatches">
                <button
                  type="button"
                  class="swatch swatch--auto"
                  :class="{ 'swatch--active': !draft.color }"
                  title="Automatique (génération par défaut)"
                  @click="draft.color = ''"
                >
                  ✕
                </button>
                <button
                  v-for="color in VENUE_PALETTE"
                  :key="color"
                  type="button"
                  class="swatch"
                  :class="{ 'swatch--active': draft.color === color }"
                  :style="{ background: color }"
                  :title="color"
                  @click="draft.color = color"
                />
                <span class="swatch swatch--picker" title="Choisir une couleur personnalisée">
                  <input
                    type="color"
                    class="swatch--picker__input"
                    :value="hexColor(draft.color)"
                    @input="draft.color = $event.target.value"
                  />
                </span>
              </div>
            </div>
          </label>
        </div>

        <div class="fiche-hint">
          Laisse sur « Automatique » pour garder la couleur générée par ordre
          d'apparition dans le Parcours Matériel — ce choix ne fixe une teinte
          que pour CE lieu, sans toucher aux autres.
        </div>

        <div class="fiche-hint">
          Les coordonnées GPS servent à l'estimation automatique des temps de trajet
          des transports — laisse vide si tu ne les as pas.
        </div>
        <div v-if="!draft.name.trim()" class="fiche-error">Le nom du lieu est requis.</div>
        <div v-if="saveError" class="fiche-error">{{ saveError }}</div>

        <div class="fiche-danger">
          <div class="fiche-danger__hint">
            Supprimer ce lieu n'est possible que s'il n'est utilisé par aucun
            spectacle, déplacement ou matériel.
          </div>
          <button type="button" class="fiche-btn fiche-btn--danger" @click="askDelete">
            Supprimer ce lieu
          </button>
        </div>
      </div>

      <div v-if="confirming" class="fiche-confirm-backdrop" @click.self="cancelDelete">
        <div class="fiche-confirm">
          <div class="fiche-confirm__title">Supprimer « {{ venue.name }} » ?</div>
          <p class="fiche-confirm__text">
            Cette action est définitive. Le lieu ne sera supprimé que s'il n'est
            plus référencé nulle part.
          </p>
          <div v-if="deleteError" class="fiche-error">{{ deleteError }}</div>
          <div class="fiche-confirm__actions">
            <button type="button" class="fiche-btn" :disabled="deleting" @click="cancelDelete">
              Annuler
            </button>
            <button
              type="button"
              class="fiche-btn fiche-btn--danger"
              :disabled="deleting"
              @click="confirmDelete(venue.id)"
            >
              {{ deleting ? 'Suppression…' : 'Supprimer' }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="!editing && venue.notes" class="card">
        <div class="card-title">Notes</div>
        <div class="card-text">{{ venue.notes }}</div>
      </div>

      <div class="card">
        <div class="card-title" style="margin-bottom: 14px">Spectacles assignés</div>
        <div v-if="decoratedShows.length > 0" class="row-list">
          <RouterLink
            v-for="s in decoratedShows"
            :key="s.id"
            :to="`/spectacles/${s.id}`"
            class="row row--clickable"
          >
            <span class="row__dot" :style="{ background: s.dot }" />
            <div class="row__body">
              <div class="row__title">{{ s.label }}</div>
              <div class="row__subtitle">{{ s.date }} · {{ s.time }}</div>
            </div>
            <div v-if="s.conflict" class="row__conflict">CONFLIT</div>
          </RouterLink>
        </div>
        <div v-else class="row-empty">Aucun spectacle assigné à ce lieu.</div>
      </div>
    </div>

    <!-- Quitter une fiche en cours d'édition demande d'abord quoi faire
         (2026-08-05) — voir useLeaveGuard.js. -->
    <LeaveEditPrompt
      :visible="leavePrompt"
      :saving="leaveSaving"
      :error="leaveError"
      @stay="stayOnPage"
      @save="saveAndLeave"
    />
  </AppShell>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 20px;
  max-width: 820px;
}

.hint {
  padding: 32px 40px;
  font: 500 13px system-ui;
  color: rgba(var(--fg-rgb), 0.58);
}

.hint--error {
  color: oklch(0.78 0.16 35);
}

.breadcrumb {
  font: 500 12px system-ui;
  color: rgba(var(--fg-rgb), 0.48);
}

.breadcrumb :deep(a) {
  color: var(--link);
  text-decoration: none;
}

.header {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.header__tag {
  font: 700 10px system-ui;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 3px 9px;
  border-radius: 0 6px 0 6px;
}

.card {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-notch-lg);
  padding: 20px;
}

.info-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
}

@media (max-width: 640px) {
  .info-grid {
    grid-template-columns: 1fr;
  }
}

.info-col {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.info-label {
  font: 700 11px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: rgba(var(--fg-rgb), 0.53);
}

.info-value {
  font: 500 14px system-ui;
  color: rgb(var(--fg-rgb));
  margin-top: 4px;
}

.info-value--code {
  display: flex;
  align-items: center;
  gap: 10px;
}

.code-badge {
  padding: 3px 8px;
  border-radius: 0 6px 0 6px;
  background: rgba(var(--fg-rgb), 0.08);
  font: 700 12px var(--font-mono);
  letter-spacing: 0.08em;
  color: rgb(var(--fg-rgb));
}

.code-empty {
  font: 500 13px system-ui;
  color: rgba(var(--fg-rgb), 0.43);
}

/* Aperçu de la couleur retenue (2026-08-02, suite) — carré plutôt qu'un
   petit point : la teinte doit se voir clairement, pas juste se deviner.
   Utilisé en lecture (à côté de « Personnalisée »/« Automatique ») ET en
   édition (à côté du sélecteur), même élément dans les deux cas. Toujours
   une vraie couleur de fond (jamais vide) : en mode Automatique,
   `autoPreviewColor()` fournit un aperçu — voir la note de tête du module. */
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

/* Sélecteur de couleur (2026-08-02) — même gabarit que les puces de
   catégorie de CategoriesMaterielView.vue, dupliqué faute de composant
   partagé. `.swatch--auto` (« ✕ », remet `draft.color` à `''`) est le seul
   ajout propre à ce sélecteur : contrairement aux catégories, une couleur de
   lieu est optionnelle, il faut donc un moyen de revenir à « rien ». */
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

.swatch--auto {
  background: var(--bg-row);
  color: rgba(var(--fg-rgb), 0.53);
  font: 700 12px system-ui;
}

/* Sélecteur natif (2026-08-02, suite, demande de Samuel : « donner l'option
   d'utiliser le color picker », puis « montrer l'icône de dégradé de
   couleur et de hue ») — même gabarit que les puces de palette. Un
   `<input type="color">` affiche par défaut sa VALEUR courante (un carré
   uni), pas une icône de sélecteur : on superpose donc un dégradé conique
   (roue de teintes) en fond de `.swatch--picker`, et le vrai `<input>`
   NATIF par-dessus en `opacity: 0` — invisible mais toujours cliquable et
   fonctionnel (`inset: 0`, plein cadre), c'est lui qui ouvre le sélecteur
   système et reçoit la valeur choisie. */
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

.info-value--mono {
  font-family: var(--font-mono);
  font-size: 13px;
}

.map {
  border: 0;
  width: 100%;
  height: 100%;
  min-height: 180px;
  border-radius: 0 10px 0 10px;
}

.map--empty {
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-row);
  color: rgba(var(--fg-rgb), 0.48);
  font: 500 12.5px system-ui;
  text-align: center;
  padding: 20px;
}


.card-text {
  font: 400 13.5px/1.6 system-ui;
  color: rgba(var(--fg-rgb), 0.75);
  margin-top: 14px;
}

.row-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: var(--radius-notch-sm);
  background: var(--bg-row);
}

/* Ligne entière cliquable (2026-08-05, demande de Samuel) : le titre seul
   était un point de clic étroit, alors que toute la ligne mène au même
   endroit. Même geste que les chronologies des fiches spectacle/matériel. */
.row--clickable {
  text-decoration: none;
  cursor: pointer;
}

.row--clickable:hover {
  background: rgba(var(--fg-rgb), 0.09);
}

.row__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
}

.row__body {
  flex: 1;
  min-width: 0;
}

.row__title {
  font: 600 13px system-ui;
  color: rgb(var(--fg-rgb));
  text-decoration: none;
  display: block;
}

.row__subtitle {
  font: 400 11.5px system-ui;
  color: rgba(var(--fg-rgb), 0.58);
}

.row__conflict {
  font: 700 10px system-ui;
  color: oklch(0.85 0.13 35);
  background: oklch(0.7 0.16 35 / 0.18);
  padding: 2px 8px;
  border-radius: 0 10px 0 10px;
}

.row-empty {
  font: 500 12.5px system-ui;
  color: rgba(var(--fg-rgb), 0.48);
  padding: 10px 12px;
}
</style>

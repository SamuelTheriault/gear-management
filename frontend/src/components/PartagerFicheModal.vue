<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api/client'
import { useEscapeKey } from '../composables/useEscapeKey'

/**
 * Panneau « Partager / Imprimer » d'une sortie de rapport (2026-08-08).
 *
 * Point d'entrée unique vers les liens publics (`ReportShare`, backend) depuis
 * les fiches de l'app. Quatre types de feuille passent par ici : tournée,
 * spectacle, parcours technicien, horaire d'une journée.
 *
 * **Pourquoi un panneau et pas un bouton qui ouvre le PDF directement**
 * (décision de Samuel du 2026-08-08) : cliquer « Imprimer » émettrait un lien
 * PUBLIC sans qu'on le voie passer. Ici on montre d'abord ce qu'on s'apprête à
 * diffuser — l'URL, le code QR tel qu'il sera imprimé — et on laisse le choix
 * entre imprimer, envoyer le lien par courriel, ou révoquer.
 *
 * **Le lien n'est pas créé à l'ouverture.** On cherche d'abord s'il en existe
 * déjà un actif pour cette cible ; sinon on affiche une explication et un
 * bouton. Ouvrir un panneau pour regarder ne doit pas publier quoi que ce
 * soit.
 *
 * **Le QR vient du serveur** (champ `qr` du `ReportShareSerializer`), rendu
 * par le même code que celui qui le grave sur le PDF. Une bibliothèque QR en
 * JavaScript serait une deuxième vérité à maintenir, et le premier écart
 * entre l'aperçu et le papier passerait inaperçu jusqu'au quai.
 */

const props = defineProps({
  // 'transport' | 'show' | 'technician' | 'day' — voir ReportShare.KIND_*.
  kind: { type: String, required: true },
  projectId: { type: [Number, String], required: true },
  // Id de la cible. Absent pour 'day', dont la cible est une DATE saisie ici.
  targetId: { type: [Number, String], default: null },
  // Ce qu'on partage, en clair, pour que la personne sache ce qu'elle diffuse.
  label: { type: String, default: '' },
})

const emit = defineEmits(['close'])
useEscapeKey(() => emit('close'))

const LIBELLES = {
  transport: 'Fiche de transport',
  show: 'Fiche spectacle',
  technician: 'Parcours technicien',
  day: 'Horaire de la journée',
}

const CHAMP_CIBLE = {
  transport: 'transport',
  show: 'show',
  technician: 'technician',
  day: 'day',
}

const chargement = ref(true)
const enCours = ref(false)
const erreur = ref('')
const partage = ref(null)
const copie = ref(false)
const confirmerRevocation = ref(false)

// Pour 'day' seulement : la journée à partager, aujourd'hui par défaut.
const jour = ref(new Date().toISOString().slice(0, 10))

const titre = computed(() => LIBELLES[props.kind] ?? 'Sortie de rapport')
const urlPdf = computed(() => (
  partage.value ? `/api/public/reports/${partage.value.token}/pdf/` : ''
))

function corpsRequete() {
  const corps = { project: props.projectId, kind: props.kind }
  corps[CHAMP_CIBLE[props.kind]] = props.kind === 'day' ? jour.value : props.targetId
  return corps
}

/** Le partage actif déjà émis pour cette cible, s'il y en a un. */
function correspond(ligne) {
  if (ligne.kind !== props.kind || !ligne.is_active) return false
  if (props.kind === 'day') return ligne.day === jour.value
  return String(ligne[CHAMP_CIBLE[props.kind]]) === String(props.targetId)
}

async function chercherExistant() {
  chargement.value = true
  erreur.value = ''
  try {
    const lignes = await api.get('/report-shares/', { project: props.projectId })
    partage.value = lignes.find(correspond) ?? null
  } catch {
    erreur.value = "Impossible de vérifier les liens déjà émis."
  } finally {
    chargement.value = false
  }
}

async function creer() {
  enCours.value = true
  erreur.value = ''
  try {
    // L'endpoint est idempotent : si un lien actif existe déjà pour cette
    // cible, il renvoie le même (200 au lieu de 201) plutôt qu'une erreur de
    // contrainte. On peut donc appeler sans se demander qui a cliqué avant.
    partage.value = await api.post('/report-shares/', corpsRequete())
    confirmerRevocation.value = false
  } catch (e) {
    erreur.value = e?.data?.detail
      || Object.values(e?.data ?? {}).flat().join(' ')
      || "La création du lien a échoué."
  } finally {
    enCours.value = false
  }
}

async function revoquer() {
  enCours.value = true
  erreur.value = ''
  try {
    await api.delete(`/report-shares/${partage.value.id}/`)
    partage.value = null
    confirmerRevocation.value = false
  } catch {
    erreur.value = "La révocation a échoué."
  } finally {
    enCours.value = false
  }
}

async function copier() {
  try {
    await navigator.clipboard.writeText(partage.value.url)
    copie.value = true
    setTimeout(() => { copie.value = false }, 2000)
  } catch {
    erreur.value = "Copie impossible — sélectionne l'adresse à la main."
  }
}

onMounted(chercherExistant)
</script>

<template>
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="modal">
      <div class="modal__header">
        <div class="modal__title">Partager — {{ titre }}</div>
        <div class="modal__close" @click="emit('close')">×</div>
      </div>
      <div v-if="label" class="modal__context">{{ label }}</div>

      <div class="modal__corps">
        <p v-if="chargement" class="etat">Chargement…</p>

        <template v-else>
          <!-- Choix de la journée : seul cas où la cible se choisit ici. -->
          <label v-if="kind === 'day'" class="champ-jour">
            <span>Journée</span>
            <input v-model="jour" type="date" @change="chercherExistant">
          </label>

          <!-- Aucun lien actif : on explique AVANT de publier quoi que ce soit. -->
          <template v-if="!partage">
            <p class="explication">
              Créer un lien met cette feuille en ligne à une adresse secrète,
              consultable <strong>sans compte</strong> par qui la reçoit. C'est
              ce que le code QR imprimé fera ouvrir.
            </p>
            <p class="explication explication--fine">
              La portée se limite à cette feuille : ni le reste de la production,
              ni les autres projets. Tu peux révoquer le lien à tout moment.
            </p>
            <button type="button" class="fiche-btn fiche-btn--primary" :disabled="enCours" @click="creer">
              {{ enCours ? 'Création…' : 'Créer le lien de partage' }}
            </button>
          </template>

          <!-- Lien actif : le QR tel qu'il sera imprimé, l'adresse, les actions. -->
          <template v-else>
            <div class="apercu">
              <!-- eslint-disable-next-line vue/no-v-html -->
              <div class="qr" v-html="partage.qr"></div>
              <div class="apercu__texte">
                <div class="etiquette">Adresse publique</div>
                <code class="url">{{ partage.url }}</code>
                <div class="apercu__meta">
                  {{ partage.access_count }} consultation<span v-if="partage.access_count > 1">s</span>
                  <span v-if="partage.last_accessed_at">
                    · dernière le {{ new Date(partage.last_accessed_at).toLocaleDateString('fr-CA') }}
                  </span>
                </div>
              </div>
            </div>

            <div class="actions">
              <a class="fiche-btn fiche-btn--primary" :href="urlPdf" target="_blank" rel="noopener">
                Ouvrir le PDF
              </a>
              <button type="button" class="fiche-btn" @click="copier">
                {{ copie ? 'Adresse copiée' : "Copier l'adresse" }}
              </button>
            </div>

            <!-- Révocation en deux temps : elle tue AUSSI les copies papier
                 déjà distribuées, ce qui n'est pas évident au moment du clic. -->
            <div class="revocation">
              <button
                v-if="!confirmerRevocation"
                type="button"
                class="lien-danger"
                @click="confirmerRevocation = true"
              >
                Révoquer ce lien
              </button>
              <template v-else>
                <p class="avertissement">
                  Toutes les feuilles déjà imprimées avec ce code QR cesseront
                  de fonctionner, y compris celles qui circulent sur le terrain.
                  Un nouveau lien portera un code différent.
                </p>
                <div class="actions">
                  <button type="button" class="fiche-btn" @click="confirmerRevocation = false">
                    Annuler
                  </button>
                  <button type="button" class="fiche-btn fiche-btn--danger" :disabled="enCours" @click="revoquer">
                    {{ enCours ? 'Révocation…' : 'Révoquer quand même' }}
                  </button>
                </div>
              </template>
            </div>
          </template>

          <p v-if="erreur" class="erreur">{{ erreur }}</p>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed; inset: 0; z-index: 200;
  background: rgba(0, 0, 0, 0.55);
  display: flex; align-items: center; justify-content: center; padding: 1rem;
}
.modal {
  width: min(34rem, 100%);
  background: var(--surface, #16181d);
  color: var(--text, #e8eaee);
  border: 1px solid var(--border, rgba(255, 255, 255, 0.12));
  border-radius: 0 14px 0 14px;
  display: flex; flex-direction: column;
}
.modal__header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0.9rem 1.1rem 0.5rem;
}
.modal__title { font-weight: 600; }
.modal__close { cursor: pointer; font-size: 1.3rem; line-height: 1; opacity: 0.7; }
.modal__close:hover { opacity: 1; }
.modal__context {
  padding: 0 1.1rem 0.6rem; color: var(--text-muted, rgba(232, 234, 238, 0.66));
  font-size: 0.9rem;
}
.modal__corps { padding: 0.4rem 1.1rem 1.1rem; display: flex; flex-direction: column; gap: 0.8rem; }

.champ-jour { display: flex; flex-direction: column; gap: 0.3rem; font-size: 0.85rem; }
.champ-jour input {
  background: transparent; color: inherit; padding: 0.45rem 0.6rem;
  border: 1px solid var(--border, rgba(255, 255, 255, 0.18)); border-radius: 0 8px 0 8px;
}

.explication { font-size: 0.9rem; line-height: 1.5; margin: 0; }
.explication--fine { color: var(--text-muted, rgba(232, 234, 238, 0.66)); font-size: 0.83rem; }

.apercu { display: flex; gap: 0.9rem; align-items: flex-start; }
/* Le SVG arrive dimensionné en millimètres (il est fait pour le papier) :
   on le contraint ici en pixels pour l'écran. */
.qr { flex: 0 0 auto; background: #fff; padding: 6px; border-radius: 0 8px 0 8px; }
.qr :deep(svg) { width: 96px; height: 96px; display: block; }
.apercu__texte { min-width: 0; flex: 1; }
.etiquette {
  font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.09em;
  color: var(--text-muted, rgba(232, 234, 238, 0.6)); margin-bottom: 0.25rem;
}
.url { font-size: 0.78rem; word-break: break-all; display: block; line-height: 1.45; }
.apercu__meta {
  margin-top: 0.5rem; font-size: 0.78rem;
  color: var(--text-muted, rgba(232, 234, 238, 0.6));
}

.actions { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.revocation { border-top: 1px solid var(--border, rgba(255, 255, 255, 0.1)); padding-top: 0.7rem; }
.lien-danger {
  background: none; border: none; padding: 0; cursor: pointer;
  color: oklch(0.68 0.17 25); font-size: 0.83rem; text-decoration: underline;
}
.avertissement { font-size: 0.83rem; line-height: 1.5; margin: 0 0 0.6rem; color: oklch(0.78 0.12 60); }
.erreur { color: oklch(0.7 0.17 25); font-size: 0.85rem; margin: 0; }
.etat { color: var(--text-muted, rgba(232, 234, 238, 0.66)); margin: 0; }
</style>

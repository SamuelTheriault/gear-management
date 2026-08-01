import { ref, computed } from 'vue'
import { api } from '../api/client'

/**
 * Mode lecture/édition partagé par les fiches de détail (lieu, matériel,
 * technicien, spectacle).
 *
 * Comportement commun décidé avec Samuel le 2026-07-30, en repartant de
 * `LieuDetailView.vue` : un bouton « Modifier la fiche » dans l'entête
 * bascule TOUTE la carte d'infos en édition, et l'enregistrement part en un
 * seul PATCH — plutôt qu'un crayon par champ. Une fiche se corrige en bloc
 * (on récupère une adresse et un contact en même temps), pas champ par champ.
 *
 * Contrairement à `useActiveProject`/`useAuth`, ce composable n'est PAS un
 * singleton : chaque fiche appelle `useFicheEdition()` et obtient son propre
 * état.
 *
 * Ce que le composable prend en charge :
 *  - l'état `editing` / `saving` et le brouillon local `draft` (jeté à
 *    l'annulation, pour ne jamais écrire dans l'objet affiché tant que le
 *    serveur n'a pas répondu) ;
 *  - le PATCH et le remplacement de l'objet par la réponse serveur ;
 *  - le dispatch des erreurs DRF **par champ** (`fieldErrors`) plus un
 *    message résiduel (`saveError`), pour afficher chaque message sous
 *    l'input concerné.
 *
 * Ce qu'il laisse à la vue : le choix des champs, leur rendu HTML, et toute
 * validation métier propre à l'entité (ex. le bandeau « Forcer » des
 * conflits de spectacle, qui n'est pas une erreur de champ ordinaire).
 *
 * @param {object} options
 * @param {import('vue').Ref} options.entity   Ref contenant l'objet affiché ;
 *   remplacé par la réponse du PATCH en cas de succès.
 * @param {string} options.endpoint            Préfixe DRF, ex. `/venues`.
 * @param {() => object} options.toDraft       Construit le brouillon à partir
 *   de l'objet courant (appelé à chaque entrée en édition).
 * @param {(draft: object) => object} options.toPayload  Construit le corps du
 *   PATCH à partir du brouillon (trim, conversions, `null` plutôt que chaîne
 *   vide sur les champs nullables…).
 * @param {string[]} options.fields            Champs dont on veut récupérer
 *   les erreurs DRF individuellement.
 * @param {(draft: object) => boolean} [options.isValid]  Validation locale
 *   avant envoi (par défaut : toujours valide).
 * @param {string} [options.errorMessage]      Message générique de repli.
 */
export function useFicheEdition({
  entity,
  endpoint,
  toDraft,
  toPayload,
  fields,
  isValid = () => true,
  errorMessage = 'Impossible d’enregistrer les changements.',
}) {
  const editing = ref(false)
  const draft = ref(null)
  const saving = ref(false)
  const saveError = ref(null)
  const fieldErrors = ref({})
  // Corps brut de la dernière réponse d'erreur. Certaines validations métier
  // ne sont pas des erreurs de champ ordinaires et méritent leur propre
  // affichage : le conflit de lieu d'un spectacle renvoie `{conflicts: [...],
  // detail}` et se règle par un réenregistrement avec `force: true`.
  const lastError = ref(null)

  function resetErrors() {
    saveError.value = null
    fieldErrors.value = {}
    lastError.value = null
  }

  function startEdit() {
    if (!entity.value) return
    draft.value = toDraft(entity.value)
    resetErrors()
    editing.value = true
  }

  function cancelEdit() {
    editing.value = false
    draft.value = null
    resetErrors()
  }

  const canSave = computed(
    () => editing.value && !saving.value && !!draft.value && isValid(draft.value),
  )

  /**
   * Range une erreur d'API dans `fieldErrors` / `saveError`.
   *
   * Exporté parce que les fiches qui font leurs propres appels (ex. le PATCH
   * avec `force` d'un spectacle en conflit) veulent le même affichage
   * d'erreurs sans repasser par `save()`.
   */
  function applyApiError(e) {
    const data = e?.data
    lastError.value = data ?? null
    if (data && typeof data === 'object' && !Array.isArray(data)) {
      const perField = {}
      for (const field of fields) {
        if (data[field]) perField[field] = [].concat(data[field])[0]
      }
      fieldErrors.value = perField
      const global = data.detail ?? (data.non_field_errors ? [].concat(data.non_field_errors)[0] : null)
      saveError.value = global ?? (Object.keys(perField).length ? null : errorMessage)
    } else {
      fieldErrors.value = {}
      saveError.value = errorMessage
    }
  }

  /**
   * Enregistre le brouillon (PATCH). Renvoie `true` en cas de succès, `false`
   * si le serveur a refusé — la vue peut ainsi enchaîner (rechargement des
   * données liées, par exemple) sans dupliquer la gestion d'erreur.
   *
   * `extraPayload` sert aux champs qui ne viennent pas du brouillon, comme le
   * `force: true` d'un réenregistrement après conflit.
   */
  async function save(extraPayload = {}) {
    if (!canSave.value) return false
    saving.value = true
    resetErrors()
    try {
      const id = entity.value.id
      entity.value = await api.patch(`${endpoint}/${id}/`, {
        ...toPayload(draft.value),
        ...extraPayload,
      })
      editing.value = false
      draft.value = null
      return true
    } catch (e) {
      applyApiError(e)
      return false
    } finally {
      saving.value = false
    }
  }

  return {
    editing,
    draft,
    saving,
    saveError,
    fieldErrors,
    lastError,
    canSave,
    startEdit,
    cancelEdit,
    save,
    applyApiError,
    resetErrors,
  }
}

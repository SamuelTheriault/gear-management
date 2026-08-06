import { ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'

/**
 * Empêche de quitter une fiche en cours d'édition sans avoir tranché
 * (2026-08-05, demande de Samuel : « si on clique sur un lien du menu, la
 * page ferme et les modifications sont perdues »).
 *
 * Deux issues seulement, comme demandé : **rester sur la page** ou
 * **enregistrer puis continuer**. Pas de « quitter sans enregistrer » —
 * l'oubli d'un enregistrement est justement ce qu'on cherche à éviter, et
 * annuler volontairement reste possible par le bouton Annuler de la fiche,
 * qui est un geste explicite.
 *
 * Ne se déclenche que si le brouillon a RÉELLEMENT changé (`isDirty`) :
 * entrer en édition puis repartir sans rien toucher ne doit rien demander.
 *
 * ## Ce que ce garde-fou ne couvre pas
 *
 * Fermer l'onglet ou recharger la page passe par `beforeunload`, que le
 * navigateur limite à son propre message générique — impossible d'y proposer
 * « enregistrer ». On s'y contente donc d'avertir, ce que fait le second
 * écouteur ci-dessous.
 *
 * @param {object} options
 * @param {() => boolean} options.isDirty  Y a-t-il des changements non enregistrés ?
 * @param {() => Promise<boolean>} options.save  Enregistre ; `false` si refusé.
 */
export function useLeaveGuard({ isDirty, save }) {
  const leavePrompt = ref(false)
  const leaveSaving = ref(false)
  const leaveError = ref(null)
  let destinationEnAttente = null

  onBeforeRouteLeave((to) => {
    if (!isDirty()) return true
    // La navigation en cours est refusée ; elle sera rejouée telle quelle si
    // l'enregistrement réussit.
    destinationEnAttente = to.fullPath
    leaveError.value = null
    leavePrompt.value = true
    return false
  })

  function stayOnPage() {
    leavePrompt.value = false
    destinationEnAttente = null
    leaveError.value = null
  }

  /**
   * Enregistre puis reprend la navigation interrompue.
   *
   * En cas de refus du serveur (conflit, champ invalide), on reste sur la
   * fiche et on laisse la modale ouverte avec le message : partir malgré tout
   * perdrait les changements, ce que la demande exclut explicitement.
   */
  async function saveAndLeave(router) {
    leaveSaving.value = true
    leaveError.value = null
    try {
      const ok = await save()
      if (!ok) {
        leaveError.value = "L'enregistrement a été refusé — corrige la fiche avant de continuer."
        return
      }
      const destination = destinationEnAttente
      leavePrompt.value = false
      destinationEnAttente = null
      if (destination) router.push(destination)
    } finally {
      leaveSaving.value = false
    }
  }

  return { leavePrompt, leaveSaving, leaveError, stayOnPage, saveAndLeave }
}

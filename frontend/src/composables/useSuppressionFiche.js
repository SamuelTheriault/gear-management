import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api/client'
import { useEscapeKey } from './useEscapeKey'

/**
 * Suppression d'une fiche, avec confirmation — lieu, spectacle et transport
 * (ajouté le 2026-07-30 à la demande de Samuel).
 *
 * Le bouton vit en bas du formulaire d'édition, à l'écart de
 * Enregistrer/Annuler : une suppression ne doit pas se cliquer par accident.
 * D'où aussi la modale de confirmation, qui annonce ce qui va disparaître
 * (voir `ShowSerializer.deletion_impact` pour le cas du spectacle).
 *
 * Comportement du backend selon l'entité — c'est volontairement différent :
 *  - **Lieu** : la suppression est REFUSÉE tant qu'un spectacle, un transport
 *    ou du matériel y est rattaché (`VenueViewSet.destroy` renvoie un 400 avec
 *    les décomptes). L'erreur est affichée telle quelle dans la modale.
 *  - **Spectacle** : autorisée, mais emporte en cascade ses assignations et
 *    ses déplacements (FK en CASCADE). D'où l'avertissement chiffré.
 *  - **Transport** : autorisée, emporte ses lignes de matériel et de
 *    techniciens (tables de liaison en CASCADE).
 *
 * @param {object} options
 * @param {string} options.endpoint   Préfixe DRF, ex. `/venues`.
 * @param {string} options.redirectTo Route de liste où revenir après succès.
 */
export function useSuppressionFiche({ endpoint, redirectTo }) {
  const router = useRouter()

  const confirming = ref(false)
  const deleting = ref(false)
  const deleteError = ref(null)

  function askDelete() {
    confirming.value = true
    deleteError.value = null
  }

  function cancelDelete() {
    confirming.value = false
    deleteError.value = null
  }

  // Échap ferme la confirmation, même geste que le clic sur le fond ou sur
  // « Annuler » — les trois fiches qui utilisent ce composable (lieu,
  // spectacle, transport) l'obtiennent donc gratuitement.
  useEscapeKey(() => {
    if (confirming.value) cancelDelete()
  })

  async function confirmDelete(id) {
    deleting.value = true
    deleteError.value = null
    try {
      await api.delete(`${endpoint}/${id}/`)
      router.push(redirectTo)
    } catch (e) {
      // Le refus du backend (lieu encore utilisé) porte son propre message,
      // décomptes compris : on l'affiche tel quel plutôt que de le résumer.
      deleteError.value = e.data?.detail ?? 'Impossible de supprimer cet élément.'
    } finally {
      deleting.value = false
    }
  }

  return { confirming, deleting, deleteError, askDelete, cancelDelete, confirmDelete }
}

// `\p{Mn}` = tout caractère combinant ajouté par la décomposition NFD
// (accents, cédille…) — plus lisible qu'une plage Unicode écrite à la main.
const DIACRITICS = /\p{Mn}/gu

/**
 * Normalisation pour la recherche texte libre : insensible à la casse et
 * aux accents (NFD + suppression des marques combinantes), même logique
 * que le tri des catégories côté backend (2026-07-30), mais en JS ici.
 *
 * Partagé entre `MaterielView.vue` (2026-07-31, point 3 de l'audit
 * ergonomie/navigation), `AssignerMaterielModal.vue` et la modale
 * « Ajouter du matériel » de `TransportDetailView.vue` (étendu le même
 * jour) — plutôt que trois copies de la même fonction.
 */
export function normalizeText(str) {
  return (str || '').normalize('NFD').replace(DIACRITICS, '').toLowerCase()
}

// Palette de couleurs par lieu — « charte de couleur » de l'app pour les
// bandes représentant un lieu (Parcours Matériel). Source unique partagée
// entre la génération automatique (ParcoursMaterielView.vue, cyclée par
// ordre d'apparition) et le sélecteur manuel de la fiche Lieu
// (LieuDetailView.vue, `Venue.color`, 2026-08-02) : Samuel a demandé de
// pouvoir fixer la couleur d'un lieu, mais en piochant dans les mêmes
// teintes que la génération automatique — pas une palette différente.
//
// Ne pas dupliquer ce tableau ailleurs : un lieu fixé manuellement doit
// rester visuellement cohérent avec ceux encore générés automatiquement.
//
// 10 teintes (2026-08-02, suite, demande de Samuel : « 10 couleurs bien
// différentes les unes des autres ») — les 6 d'origine sont conservées
// TELLES QUELLES, en tête de tableau (continuité pour les lieux déjà
// générés/choisis) ; 4 teintes ajoutées à la suite, choisies pour maximiser
// l'écart de teinte avec les 6 premières ET entre elles (angles oklch
// répartis à ≥25° les uns des autres sur les 10, contre ~36° en moyenne
// pour une répartition parfaitement égale) — même style que les 6
// d'origine (`oklch(0.52–0.55 0.13 h)`).
export const VENUE_PALETTE = [
  'oklch(0.55 0.13 290)',
  'oklch(0.52 0.13 200)',
  'oklch(0.55 0.13 145)',
  'oklch(0.55 0.13 60)',
  'oklch(0.52 0.13 320)',
  'oklch(0.55 0.13 25)',
  'oklch(0.55 0.13 100)',
  'oklch(0.52 0.13 170)',
  'oklch(0.55 0.13 245)',
  'oklch(0.52 0.13 350)',
]

// Métadonnées d'affichage par type de spectacle/bloc (`Show.EVENT_TYPE_CHOICES`)
// — source unique partagée entre `SpectaclesView.vue`, `SpectacleDetailView.vue`,
// `MaterielDetailView.vue` et `DashboardView.vue`, qui avaient chacun leur
// propre copie de cet objet jusqu'au 2026-08-02 (constat de Samuel : « les
// couleurs des bandes qui ne sont pas gérées dans une fiche »).
//
// `color`/`bg` référencent les CSS custom properties posées par
// `useEventColors.js` (`--event-rehearsal`, etc., voir aussi le repli
// statique dans style.css) plutôt que des valeurs oklch littérales : la
// couleur RÉELLE vient du singleton `Settings`, modifiable depuis Réglages
// sans toucher à ce fichier. `bg` reprend la même transparence (16%) que
// l'ancien `oklch(... / .16)` codé en dur, via `color-mix()` — fonctionne
// quelle que soit la syntaxe choisie pour la couleur de base (oklch(...) de
// la palette ou hex du sélecteur natif), contrairement à la notation
// `oklch(... / .16)` qui n'acceptait que de l'oklch.
// `dot` = `color` pour tous les types SAUF storage, qui utilisait déjà une
// puce plus discrète que sa couleur de badge avant ce passage en source
// unique (`rgba(var(--fg-rgb),.3)` contre `.6` pour le badge, un ratio de
// 50%) — reproduit ici via `color-mix()` à 50% plutôt qu'une deuxième valeur
// stockée, pour que ça continue de s'atténuer pareil même si Samuel choisit
// une autre couleur d'Entreposage depuis Réglages.
export const EVENT_TYPE_META = {
  rehearsal: {
    label: 'Répétition',
    color: 'var(--event-rehearsal)',
    bg: 'color-mix(in oklch, var(--event-rehearsal) 16%, transparent)',
    dot: 'var(--event-rehearsal)',
  },
  performance: {
    label: 'Représentation',
    color: 'var(--event-performance)',
    bg: 'color-mix(in oklch, var(--event-performance) 16%, transparent)',
    dot: 'var(--event-performance)',
  },
  storage: {
    label: 'Entreposage',
    color: 'var(--event-storage)',
    // 8%, pas 16% comme les autres types — Entreposage était déjà plus discret
    // dans les 3 fichiers d'origine (`rgba(var(--fg-rgb),.08)` contre `.16`),
    // conservé tel quel.
    bg: 'color-mix(in oklch, var(--event-storage) 8%, transparent)',
    dot: 'color-mix(in oklch, var(--event-storage) 50%, transparent)',
  },
  setup: {
    label: 'Montage',
    color: 'var(--event-setup)',
    bg: 'color-mix(in oklch, var(--event-setup) 16%, transparent)',
    dot: 'var(--event-setup)',
  },
  teardown: {
    label: 'Démontage',
    color: 'var(--event-teardown)',
    bg: 'color-mix(in oklch, var(--event-teardown) 16%, transparent)',
    dot: 'var(--event-teardown)',
  },
}

// Couleur des déplacements confirmés — même source (`--transport`), exposée
// ici pour les quelques endroits qui composaient déjà un `typeMeta`-like avec
// une 6e entrée `transport` (ex. MaterielDetailView.vue).
export const TRANSPORT_META = {
  label: 'Déplacement',
  color: 'var(--transport)',
  bg: 'color-mix(in oklch, var(--transport) 16%, transparent)',
}

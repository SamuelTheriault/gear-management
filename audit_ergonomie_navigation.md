# Audit ergonomie & navigation — gear-management

Passe d'ergonomie sur le frontend Vue (`frontend/src/`), à la demande de
Samuel : normaliser les éléments d'interface et optimiser la navigation.
Portée couverte : navigation globale (AppShell/router), cohérence des
fiches de détail, listes/filtres, modales, et les fondations CSS qui
sous-tendent tout ça. Audit uniquement — aucun changement de code à ce
stade.

Méthode : lecture du code réel (25 vues + 2 composants de modale +
`style.css`), pas de supposition. Chaque constat cite le(s) fichier(s) en
cause.

## 1. Navigation globale

### 1.1 Tabbar mobile incomplète — angle mort le plus sérieux

`AppShell.vue` bascule en tabbar sous 860 px (`shell-tabbar`, la sidebar
passe en `display: none`). Cette tabbar ne contient que 4 entrées :
Accueil, Spectacles, Matériel, Techniciens (`tabbarItems`, lignes 74-79).

Sept sections sont donc **injoignables sur mobile** : Lieux, Transports,
Conflits, Cohérence, les deux Parcours, Réglages/Utilisateurs. Pour un
directeur technique qui consulte l'outil depuis son téléphone en salle ou
en tournée, c'est probablement la lacune la plus coûteuse de tout l'audit
— Transports et Conflits en particulier sont des écrans qu'on consulte
justement quand on n'est pas à son poste.

### 1.2 Logique de regroupement incohérente dans la sidebar

`navItems` (AppShell.vue, lignes 39-67) donne un sous-menu à « Tableau de
bord » (Vue d'ensemble + les deux Parcours) et à « Matériel » (Inventaire +
Catégories), mais laisse Conflits et Cohérence en items de premier niveau,
au même rang que Spectacles/Lieux/Techniciens/Transports.

Or Conflits et Cohérence sont, comme les Parcours, des **rapports
transversaux au projet** (`GET /projects/{id}/conflicts/`,
`GET /projects/{id}/transport-coherence/`) — pas des entités qu'on liste et
qu'on édite comme un spectacle ou un lieu. Rien dans le code n'explique ce
traitement différent ; ça ressemble à un ajout au fil de l'eau plutôt qu'à
un choix délibéré. Deux lectures possibles : soit ces deux rapports
rejoignent le sous-menu du Tableau de bord, soit c'est l'inverse (Parcours
remonte au premier niveau) — dans les deux cas, le critère de regroupement
mérite d'être explicite avant d'ajouter une prochaine section.

### 1.3 (Point positif) Le fil d'Ariane des fiches est déjà exemplaire

À l'inverse de ce que je pensais en première lecture : les cinq fiches de
détail ont bien un fil d'Ariane (`.breadcrumb`, ex. « Techniciens /
Jean Tremblay ») qui ramène vers la liste — et son CSS est **identique au
caractère près** dans les cinq fichiers (`font: 500 12px system-ui; color:
rgba(255, 255, 255, 0.4);`). C'est le seul bloc de tout l'audit dupliqué
sans la moindre dérive de valeur. Aucune action requise sur le fond ; il ne
resterait qu'à le déplacer vers `style.css` comme les autres blocs `fiche-*`
pour éviter que la prochaine retouche ne le fasse diverger à son tour — un
simple copier-coller sans risque, pas une priorité.

### 1.4 Sélecteur de projet sans libellé

Le `<select>` de projet actif (`shell-nav__project`, AppShell.vue ligne
105) n'a ni label ni titre — seul son contenu (le nom du projet) indique
son rôle. Sur un `<select>` natif ça reste lisible, mais rien ne dit
explicitement « projet actif » à quelqu'un qui découvre l'outil.

### 1.5 Résidu probable de maquette

`shell-nav__version` affiche `v0.1 · JD` (AppShell.vue ligne 148) — codé en
dur, aucune référence ailleurs dans le repo à des initiales « JD ». Je
soupçonne un reliquat du mockup original plutôt qu'une info voulue par
Samuel ; à confirmer avant de retirer.

## 2. Cohérence des fiches de détail

Le pattern d'édition (`useFicheEdition.js`) et les classes `fiche-*`
globales sont déjà bien standardisés — c'est le seul endroit de l'app où la
normalisation a été poussée jusqu'au bout (voir §5). Deux écarts
persistent :

- **Le titre de page change de recette d'un écran à l'autre.** Quatre
  classes différentes portent exactement le même rôle (titre principal de
  la page) : `page-title` (Catégories, Lieux, Matériel, les deux Parcours),
  `header__title` (Cohérence, Conflits, Lieu-détail, Matériel-détail,
  Spectacle-détail, Transport-détail), `dash-title` (Dashboard), `title`
  (Réglages, Utilisateurs). En comparant leur CSS scoped : `page-title` est
  identique partout (27px, `letter-spacing: 0.06em`, majuscules) ; mais
  `header__title` **diverge en interne** — 27px/`0.04em` sur
  Cohérence/Conflits/Spectacle, 26px/`0.02em` sur Lieu, 25px/`0.02em` sur
  Matériel, et jamais en majuscules contrairement à `page-title`.
- **La fiche Technicien n'utilise même pas `header__title`.** Les quatre
  autres fiches de détail affichent un simple titre en tête de carte ; la
  fiche technicien a un en-tête à part entière — avatar rond avec initiales
  (`header__avatar`), nom en `header__name` (19px mono) et spécialité en
  `header__role` (13px, gris) juste en dessous. C'est un choix de mise en
  page défendable pour une fiche personne (l'avatar aide à repérer un nom
  dans une liste de rendez-vous), mais ça veut dire que sur les cinq
  fiches, quatre partagent une recette de titre (elle-même déjà à trois
  variantes de taille/espacement, voir ci-dessus) et la cinquième en a une
  complètement différente.
- **`TransportDetailView` reste volontairement en édition permanente** (pas
  de mode lecture, contrairement aux quatre autres fiches) — décision déjà
  actée le 2026-07-30 dans CLAUDE.md (« un mode lecture n'y ajouterait
  qu'un clic »). Je le mentionne pour mémoire, pas comme un défaut : c'est
  une asymétrie assumée, pas un oubli, et ce n'est pas une invitation à
  la refaire tomber dans le pattern des quatre autres sans repasser par
  toi.

## 3. Listes et filtres

### 3.1 Les puces de filtre (`.chip`) sont copiées-collées six fois, avec dérive

`.chip`/`.chip--active` sont redéfinies en `<style scoped>` dans
`CoherenceEmplacementsView.vue`, `DashboardView.vue`, `MaterielView.vue`,
`ReglagesView.vue`, `SpectaclesView.vue` et `TransportDetailView.vue`
(`ParcoursMaterielView.vue` a sa propre variante, `.picker-chip`, pour un
besoin un peu différent — puce avec pastille de couleur). Le padding et la
taille de police divergent déjà d'une copie à l'autre : `6px 13px`/12px
(Cohérence), `7px 14px`/12px (Dashboard, Matériel, Spectacles),
`9px 16px`/12.5px (Réglages), `6px 12px`/11.5px (Transport-détail). C'est
exactement le scénario que le commentaire au-dessus de `.fiche-*` dans
`style.css` anticipait pour les fiches (« cinq copies identiques...
garantissait qu'elles divergeraient ») — sauf que pour les puces, ça n'a
jamais été corrigé.

### 3.2 Aucune recherche texte, nulle part

Aucune vue ne propose de champ de recherche (`grep` sur `type="search"` et
sur les placeholders de recherche : zéro résultat dans tout `views/`). Le
seul filtrage disponible est par puce de catégorie/type. Tu as toi-même
signalé le risque le 2026-07-31 (« il y aura beaucoup de matériel et la
liste risque de devenir longue ») et la réponse apportée jusqu'ici a été de
compacter l'espacement des lignes — ce qui aide à voir plus de lignes à
l'écran, mais ne résout pas la question de retrouver un item précis dans un
inventaire de plusieurs centaines de pièces. Matériel est le cas le plus
net, mais Spectacles/Techniciens grossiront aussi avec le temps.

### 3.3 États vides : trois variantes

`.empty`/`.empty__title` (Catégories, Lieux, Matériel, Spectacles,
Techniciens, Transports) coexiste avec `.empty-card` (Conflits, Cohérence)
et `.empty-card`/`.empty-title`/`.empty-subtitle` (Utilisateurs, noms
différents du `.empty-card` des deux autres). Trois structures pour le même
message « rien à afficher ».

## 4. Modales

### 4.1 Le fond assombri change de nom quatre fois

`overlay` (`AssignerMaterielModal.vue`, `AssignerTechnicienModal.vue`,
`UtilisateursView.vue`), `modal-backdrop` (`CategoriesMaterielView.vue`),
`modal-overlay` (`TransportDetailView.vue`), et `fiche-confirm-backdrop`
(les trois confirmations de suppression, déjà globalisée) : quatre classes
scoped différentes pour le même rôle visuel (fond noir semi-transparent,
`position: fixed; inset: 0`), plutôt qu'une seule classe globale comme
`fiche-confirm-backdrop` l'a déjà fait pour les suppressions.

### 4.2 Fermeture au clavier absente

Aucune des modales (assignation, suppression, confirmation) ne réagit à la
touche Échap — recherche vide sur `Escape`/`keyup.esc` dans tout `views/`
et `components/`. Fermeture uniquement par clic sur le fond, sur le `×`, ou
sur « Annuler ». Petit ajout, gain d'ergonomie clavier immédiat.

### 4.3 Ce qui fonctionne déjà bien ici, à ne pas casser

`AssignerMaterielModal` et la modale de `TransportDetailView` partagent
déjà `width: min(640px, 94vw)` et une structure `modal__header`/
`modal__body`/`modal__footer` identique — c'est le résultat de
l'unification du 2026-07-30 documentée dans CLAUDE.md, et ça se voit : ces
deux-là sont la paire la plus cohérente de tout l'audit. Le travail restant
est surtout de nommage (classes partagées), pas de refonte visuelle.

## 5. Fondations CSS : l'absence de tokens explique une bonne partie du reste

`style.css` ne définit aucune variable CSS (`grep` sur `--[a-z-]*:` en
dehors des bindings `:style` inline : zéro déclaration dans un `:root`).
Les valeurs de base de l'identité visuelle sont donc répétées en dur, en
toutes lettres, dans des dizaines de blocs `<style scoped>` :

- `#d0c8f0` (couleur d'accent lavande) : 45 occurrences
- `#161a1f` (fond des cartes) : 41 occurrences
- `rgba(255, 255, 255, 0.07)` (bordure de carte) : 33 occurrences
- Le motif de coin « encoché » `0 12px 0 12px` (cartes) et `0 8px 0 8px`
  (boutons/inputs), une signature visuelle cohérente et bien tenue dans
  tout le produit : 38 et 54 occurrences respectivement

C'est la cause racine des sections 2, 3.1 et 4.1 : sans un socle de
variables partagées, chaque nouvel écran repart d'une copie du dernier
plutôt que d'une référence commune, et les micro-écarts s'accumulent. Les
blocs `fiche-*`, `add-form-*` et `parcours-*` dans `style.css` montrent que
le réflexe existe déjà chez toi (leurs commentaires l'expliquent très bien)
— il s'agit de l'étendre, pas de l'inventer.

## 6. Recommandations, par ordre de priorité

1. **Tokeniser les valeurs de base dans `style.css`** (`--accent`,
   `--bg-card`, `--border-card`, `--radius-notch-lg`/`--radius-notch-sm`,
   police mono, etc.). Zéro changement visuel si bien fait — c'est un
   renommage, pas une refonte — et ça devient la fondation de tout le
   reste. À faire en premier, le reste en dépend.
2. **Remonter trois blocs de plus au rang de classes globales**, sur le
   modèle déjà validé de `fiche-*`/`add-form-*`/`parcours-*` : le titre de
   page (unifie `page-title`/`header__title`/`dash-title`/`title`), le
   couple `.chip`/`.chip--active`, et le fond de modale
   (`overlay`/`modal-backdrop`/`modal-overlay` → une seule classe).
3. **Ajouter une recherche texte sur Matériel** (et si le volume le
   justifie, Spectacles/Techniciens) — répond directement à la
   préoccupation que tu as déjà exprimée sur la longueur des listes ;
   les puces de catégorie ne suffisent pas à retrouver un item précis.
4. **Compléter l'accès mobile** : soit étoffer la tabbar (au-delà de 4
   entrées, ça se discute — un item « Plus » ouvrant le reste du menu est
   probablement plus réaliste qu'une tabbar à 9 icônes), soit rendre la
   sidebar accessible via un tiroir sous 860px plutôt que de la masquer
   entièrement. Priorité haute si tu consultes l'outil au téléphone en
   salle ou en tournée.
5. **Clarifier le regroupement Conflits/Cohérence vs Parcours** dans la
   sidebar — les quatre sont des rapports project-wide, actuellement
   scindés en deux traitements différents sans raison apparente.
6. **Fermeture des modales à Échap.**
7. Décider si la fiche Technicien garde son en-tête à avatar (défendable en
   soi) ou rejoint la recette des quatre autres — actuellement les deux
   coexistent sans que ce soit documenté comme un choix.
8. Confirmer si `v0.1 · JD` est un résidu à retirer.

Rien ci-dessus ne touche à la logique métier ni aux endpoints — tout reste
dans `frontend/src/` (Vue + CSS). Je n'ai encore rien modifié : je veux ton
feu vert sur les priorités avant de commencer, et en particulier sur
l'ordre des points 1-2 (fondation CSS) puisque plusieurs autres points en
dépendent.

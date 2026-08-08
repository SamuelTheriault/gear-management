# Suivi de projet — gear-management

Tableau de bord manuel. À mettre à jour à chaque étape franchie ou décision
prise. Complète `recapitulatif_projet.md` (contenu fonctionnel) sans le
dupliquer — ce fichier ne suit que **l'avancement**, pas le scope.

Dernière mise à jour : 2026-08-08 — étape 31 (chantier documentation
utilisateur lancé : liste des écrans + commande `seed_demo` livrée, à
exécuter par Samuel). Mise à jour précédente, 2026-08-07 : étape 26
(corrections transport géocodage/menu/formulaire) confirmée mergée (PR #31)
et déployée, plus trois correctifs supplémentaires du même jour sur la saga
géocodage : bug de la fiche Lieu (PR #32), diagnostic actionnable avec liens
vers les fiches Lieu exactes (PR #33), et instrumentation par logs Railway
(PR #34) — la cause du symptôme signalé par Samuel reste **non résolue**,
en attente de son prochain essai avec les nouveaux logs. Railway montre en
plus une **5e PR déjà mergée et déployée** (`feat/autocomplete-adresse`,
#35, suggestions d'adresses Google Places) que ce bac à sable ne voit pas
encore dans son clone local — voir « Points de vigilance ».

## Statut global

Backend et frontend sont en ligne sur le même service Railway (Dockerfile,
WhiteNoise sert le build Vue — étape 13). Le `main` de CE clone
(`769cc79`, merge PR #34) est à jour avec les migrations `0001`→`0029`
appliquées (`Truck` compris, étape 24) et 503 tests locaux (`tests.py` +
6 fichiers `test_*.py`), dépendances `nh3` (pip) confirmée dans
`requirements.txt` et TipTap (npm) installées au build. OAuth Google testé
en vrai navigateur et fonctionnel (étape 7). ⚠️ **Le `main` GitHub a
avancé au-delà de ce que voit ce clone** : le dernier déploiement Railway
SUCCESS (2026-08-07 15 h 31 UTC) correspond à la PR #35
(`feat/autocomplete-adresse`, commit `51a8f87`), un merge que ce bac à
sable n'a pas — `git fetch`/`pull` a échoué ici (« Host key verification
failed »). Un `git pull` depuis le poste de Samuel est nécessaire avant
toute nouvelle branche, et une session suivante devra rattraper le contenu
de la PR #35 dans la doc.

**⚠️ Incident opérationnel du 2026-08-04, résolu sans perte de données :**
deux sessions Cowork ont travaillé sur le même dossier `gear-management` en
même temps (l'une sur les tournées transport, l'autre sur l'onboarding/CSV),
causant des symptômes déroutants — la branche courante changeait seule,
`suivi_projet.md` se modifiait sous nos yeux, un `git stash pop` de l'autre
session a été interrompu par erreur. Tout a été retrouvé intact (un stash
contenait bien tout ce qui semblait manquant) et le travail des deux
sessions a pu être mergé proprement. **Leçon à respecter à l'avenir : une
seule session Cowork à la fois doit toucher le dossier de travail.**

**`wip/checkpoint-2026-08-04` entièrement traité** : tout ce qui était
récupérable en a été extrait — CSV import/export (étape 17) et tooltip
flottant (étape 18). Le reste du checkpoint est périmé (prédate les
tournées multi-arrêts) — la branche peut être nettoyée à l'occasion.

**Doc de référence rattrapée** (étape 18, 2026-08-05) :
`schema.md`/`architecture.md`/`recapitulatif_projet.md` ont été mis à jour
sur les étapes 14-17 (accès par projet, tournées multi-arrêts, suppression
cascade, export/import CSV+JSON, `Venue.color`, `Material.is_kit_parent`.
Reste volontairement non documenté (fonctionnalités frontend pures, sans
modèle backend) : voir « Points de vigilance ».

## Ordre à respecter (ne pas brûler d'étape)

| # | Étape | Statut | Date |
|---|---|---|---|
| 1 | Base de données confirmée (MySQL 8.0) | ✅ Fait | — |
| 2 | Stack backend/frontend confirmée (Django + Vue) | ✅ Fait | 2026-07-16 |
| 3 | Structure de repo (scaffold + Git init) | ✅ Fait | 2026-07-16 |
| 4 | Hébergement confirmé (Railway) | ✅ Fait | 2026-07-17 |
| 5 | Déploiement Railway fonctionnel (Django + Gunicorn + WhiteNoise) | ✅ Fait | 2026-07-18 |
| 6 | Superutilisateur Django créé | ✅ Fait | 2026-07-18 |
| 7 | Projet Google Cloud OAuth (config + intégration Django) | ✅ Fait, testé en vrai navigateur — corrigé un bug de schéma http/https derrière le proxy Railway (`SECURE_PROXY_SSL_HEADER`) et géré la liaison de compte (email partagé avec le superutilisateur Django existant, flux « connect » d'allauth) | 2026-08-03 |
| 8 | Modèles Django + migrations | ✅ Fait — migrations `0001`→`0029` (dans ce clone ; `0030`+ possible côté GitHub, voir Statut global) | 2026-07-17 |
| 9 | API DRF + logique de conflits | ✅ Fait | 2026-07-17 |
| 9bis | Entreposage, transports, réglages, calcul de trajet (Google Routes API) | ✅ Fait, mergé (PR #2) | 2026-07-18 |
| 9ter | Couleur par département, quantité de matériel, `is_active`, isolation par projet (`Project`) + duplication | ✅ Fait, mergé (PR #3, #4, #5) | 2026-07-19 |
| 9quater | `Venue.code` (identification courte) | ✅ Fait, mergé (PR #6), déployé | 2026-07-24 |
| 9quinquies | Module transport : `TransportMaterial`, `Transport.status`, cohérence des emplacements, génération auto de propositions | ✅ Fait, mergé (PR #7, `e9cd546`) dans `main` | 2026-07-24 |
| 9sexies | Conflit de lieu entre spectacles (`get_venue_conflicts`, bloquant + `force`) | ✅ Mergé (PR #8) et déployé | 2026-07-25 |
| 9septies | Retrait du modèle `Department` (migration `0013`) | ✅ Mergé (PR #9) et déployé | 2026-07-29 |
| 9octies | Catégories de matériel éditables (`MaterialCategory`, migration `0014`) | ✅ Mergé (PR #9) et déployé | 2026-07-30 |
| 9nonies | Fenêtre départ/arrivée des transports (bloquant + `force`) | ✅ Mergé (PR #9) et déployé | 2026-07-30 |
| 9decies | Disponibilité du matériel au lieu de départ | ✅ Mergé (PR #9) et déployé | 2026-07-30 |
| 9undecies | Plusieurs techniciens par déplacement (`TransportTechnician`, migration `0015`) | ✅ Mergé (PR #9) et déployé | 2026-07-30 |
| 9duodecies | Blocs rattachés à un événement — montage/démontage/répétition (migrations `0016`+`0017`) | ✅ Mergé (PR #9) et déployé | 2026-07-31 |
| 10 | Frontend connecté à l'API | ✅ Fait, mergé (PR #9) | 2026-07-31 |
| 11 | Push + merge dans `main` | ✅ Fait, par Samuel depuis son poste (le bac à sable Claude n'a pas les credentials git) | 2026-08-01 |
| 12 | Déploiement Railway du backend à jour | ✅ Fait | 2026-08-01 |
| 13 | Décider et mettre en place le déploiement du frontend | ✅ Fait — option B (Django sert le build Vue via WhiteNoise, même service, Dockerfile) | 2026-08-03 |
| 14 | Gestion des accès par projet, kits, quantités, couleurs personnalisables, ordre des types réordonnable | ✅ Mergé et déployé — migrations `0018`→`0024` | 2026-08-03 |
| 15 | Module transport en tournées multi-arrêts : `TransportStop`, matériel par portion, retrait de `transport_type`, migration `0025`, manifeste par arrêt | ✅ Mergée dans `main` et déployée. Revue `code-reviewer` : 1 correctif (durée négative acceptée sur le chemin de compat A→B) | 2026-08-04 |
| 16 | Onboarding de projet (écran bloquant + garde de route), suppression cascade de projet/matériel/technicien | ✅ Mergée dans `main` et déployée — migration `0026` (renumérotée depuis `0025`, collision avec l'étape 15 résolue). Revue `code-reviewer` : 1 **bug bloquant** corrigé (`DELETE /api/projects/{id}/` en 500 sur tout projet réel) + exemption `/utilisateurs` de la garde d'onboarding | 2026-08-04 |
| 17 | Export/import CSV par section (matériel/lieux/techniciens/spectacles) + export/import JSON complet du projet (réimportable) et XML (lecture seule) | ✅ Mergée dans `main` (PR #17) et déployée. `portability.py` réparé pour `TransportStop` (remappage des arrêts par position, pas par id). Revue `code-reviewer` : 1 bug corrigé (import replace des lieux ne bloquait pas sur le matériel qui en fait son origine, contrairement à `VenueViewSet.destroy`) + 2 suggestions de tests ajoutées (permissions `export-csv`, tournée à 3 arrêts). Suite à 393 tests, flake8 propre, aucune migration | 2026-08-05 |
| 18 | Info-bulle flottante Dashboard/Parcours (`FloatingTooltip.vue`, remplace l'ancienne info-bulle CSS-only piégée par le clipping du défilement zoomé) + rattrapage de `schema.md`/`architecture.md`/`recapitulatif_projet.md` sur les étapes 14-17 | ✅ Mergée dans `main` (PR #18) et déployée. Extrait à la main de `wip/checkpoint-2026-08-04` (périmé — prédate les tournées, aurait régressé Transport/Dashboard si appliqué tel quel). Revue `code-reviewer` : code propre (aucune régression du checkpoint périmé), 1 oubli corrigé (doc rattrapée pas committée avec le code au premier passage). Frontend + doc seulement, aucun changement backend | 2026-08-05 |
| 19 | Interface Import/Export (étape 17 côté frontend) : section « Import / Export » sur Réglages — export JSON/XML complet d'un projet, export CSV par section (matériel/lieux/techniciens/spectacles), import JSON (nouveau projet), import CSV par section (append/remplace, confirmé par modale) | ✅ Mergée dans `main` (PR #22) et déployée. Brouillon retrouvé déjà présent, non committé, dans l'arbre de travail — complété par le seul chaînon manquant (`api.downloadUrl()` dans `client.js`) plutôt que réécrit, après vérification champ par champ contre l'API réelle. Inclut au passage le rattrapage `CLAUDE.md` de l'étape 18 (tooltip), resté non committé lui aussi. Revue `code-reviewer` : rien à corriger, 3 suggestions mineures non bloquantes. Frontend + doc seulement, aucun changement backend | 2026-08-05 |
| 20 | Correctif de renvoi `schema.md`/`architecture.md` (section 12 → 9 pour `transport_materials`) + tests des filtres `?show`/`?material`/`?technician` (`ShowMaterialViewSet`/`ShowTechnicianViewSet`/`TransportViewSet`) et `?project=` (`TransportViewSet`), jusqu'ici sans couverture | ✅ Mergée dans `main` (PR #25) et déployée. 8 tests ajoutés (`QueryParamFilterAPITests`), suite à 401 tests, flake8 propre, aucune migration | 2026-08-05 |
| 21 | Lot du 2026-08-05 soir : corrections d'affichage + `touched_shows`, détachement de tournée à la suppression d'un spectacle (`transport_detach.py`), ordre des lieux réordonnable (migration `0027`), Parcours Technicien complet, pincer pour zoomer + ⌘0, notes en texte riche (nh3/TipTap), garde-fou « quitter en cours d'édition » | ✅ Commitée, mergée dans `main` (PR #27) et déployée le 2026-08-06 — migration `0027` appliquée en prod, `nh3`/TipTap installés au build. Inclut les correctifs de relecture (XSS des imports, réancrage, garde-fou de navigation) | 2026-08-06 |
| 22 | Points non bloquants de la relecture de l'étape 21 : atomicité, reorder, listes allégées (`dc25a46`) | ✅ Mergée dans `main` (PR #28) et déployée — Railway SUCCESS 2026-08-06 20 h 52 (`a28bc20`) | 2026-08-06 |
| 23 | Travaux transport, chantier 1 : `Transport.project` direct + spectacle desservi OPTIONNEL (migration `0028`, « — Aucun spectacle — »), formulaire clarifié (« Spectacle desservi (arrivée) », liste filtrée par lieu d'arrivée), `transport_detach` révisé (détachement au lieu de suppression), correctif suppression de projet | ✅ Mergée dans `main` (PR #29) et déployée — migration `0028` appliquée en prod (vérifié dans les logs Railway) | 2026-08-07 |
| 24 | Travaux transport, chantier 2 : entité **Camion** (table `trucks`, camion par défaut par projet, migration `0029`), tournée assignée à un camion (conflit d'horaire bloquant + force, 4e groupe de l'écran Conflits), période de réservation (avertissement non bloquant), km estimé via distances Google Routes par segment, écrans Camions + fiche | ✅ Mergée dans `main` (PR #29) et déployée — migration `0029` appliquée en prod | 2026-08-07 |
| 25 | Travaux transport, chantier 3 : **suggestion d'ordre optimal des arrêts** (`transport_ordering.py` — énumération exacte, premier arrêt fixe, précédences chargement→déchargement, `POST /transports/order-suggestion/` stateless + bouton « Suggérer un ordre optimal » avec bandeau avant/après et remap des lignes de matériel), bouton « Réestimer les distances » (`POST /transports/{id}/refresh-distances/`, distances seules, durées intactes — comble les tournées pré-`0029`), correctif serializer (durée manuelle sur couple changé → distance quand même estimée) | ✅ Mergée dans `main` (PR #29) et déployée — aucune migration nouvelle. `GOOGLE_MAPS_API_KEY` confirmée dans les Variables Railway | 2026-08-07 |
| 26 | Passe de corrections transport : **géocodage automatique des adresses de lieux** (Google Geocoding — à l'enregistrement d'une fiche Lieu + filet au vol dans `estimate_travel`, les lieux existants se complètent à la première estimation), diagnostic actionnable de « Réestimer les distances » (nomme les lieux sans GPS / clé absente), menu **Camions en sous-menu de Transports** (Tournées/Camions), formulaire de création piloté par le spectacle desservi (lieu d'arrivée auto-sélectionné + heure de départ calée pour arriver juste avant le début effectif, via `POST /transports/estimate-travel/`) | ✅ Mergée dans `main` (PR #31, `07d172a`) et déployée | 2026-08-07 |
| 27 | Correctif géocodage : `VenueSerializer.validate` jugeait `'latitude' in attrs` toujours vrai (la fiche Lieu renvoie tout son formulaire à chaque PATCH) — le géocodage à l'enregistrement ne se déclenchait donc jamais depuis l'écran recommandé. Corrigé pour juger sur un **changement de valeur** | ✅ Mergée dans `main` (PR #32, `4b7f042`) et déployée | 2026-08-07 |
| 28 | Diagnostic « quels lieux exactement ? » : `refresh-distances` distingue `venues_missing_everything` (ni adresse ni GPS) de `venues_geocoding_failed` (adresse présente, géocodage en échec), le message de la fiche tournée pointe vers la fiche Lieu exacte de chaque lieu problématique, noms d'arrêts cliquables en lecture | ✅ Mergée dans `main` (PR #33, `d53644f`) et déployée | 2026-08-07 |
| 29 | Instrumentation du géocodage : config `LOGGING` explicite (logger `inventory` en INFO sur stdout — sans elle rien ne sortait en prod, seul WARNING+ passait), traces dans `geocode_address`/`_ensure_coordinates`/`refresh_distances`/`VenueSerializer.validate` | ✅ Mergée dans `main` (PR #34, `6396c3a`) et déployée. **Symptôme de Samuel toujours non expliqué** — prochain essai à faire côté Samuel pour lire les logs Railway | 2026-08-07 |
| 30 | *(constatée via l'historique de déploiement Railway, pas encore visible dans ce clone)* Suggestions d'adresses Google Places dans les champs adresse (`feat/autocomplete-adresse`) | 🔶 Mergée sur GitHub (PR #35, `51a8f87`) et **déployée** (Railway SUCCESS 2026-08-07 15 h 31 UTC, après un premier échec sur le même commit) — contenu non vérifié dans ce bac à sable, `git pull` requis pour rattraper | 2026-08-07 |
| 31 | **Chantier documentation utilisateur, phase 1** : liste ordonnée des 23 écrans établie + commande `manage.py seed_demo` (projet « Projet Démo » complet : 5 lieux Montréal avec GPS, 6 techniciens, 16 matériels dont kit vidéo et location, 6 événements aux titres de pièces de théâtre + 7 blocs montage/répétition/démontage, 2 camions, 2 tournées confirmées dont une multi-arrêts, ~5 propositions auto « à approuver », et des conflits VOLONTAIRES autour de « L'Avare » pour l'écran Conflits). **Toute la production tient sur 3 jours (J0–J+2, demande de Samuel du 2026-08-08 : timelines denses pour les captures)**. Réexécutable (dates relatives au jour même) — validée par exécution réelle sur une base de test (conflits vérifiés : seuls les voulus restent) | 🔶 Fichiers livrés (`inventory/management/commands/seed_demo.py`) — **Samuel doit lancer `python manage.py seed_demo` localement**, puis commit/push depuis son poste (pas de Git depuis le bac à sable) | 2026-08-08 |
| 32 | **Sorties de rapports imprimables** (chantier 2026-08-08) : liens publics signés (`ReportShare`, migration `0030`, jeton de 128 bits, un partage par cible réutilisé, révocation explicite), page publique `/p/<token>` exemptée de la garde du routeur, endpoint `AllowAny` unique + throttle + `robots.txt`, assemblage des données partagé écran/papier (`reports.py`), rendu PDF WeasyPrint A4 des **quatre** feuilles (transport, spectacle, parcours technicien, horaire de la journée en paysage) portées depuis les maquettes Claude Design, QR segno vectoriel de 25 mm en pied de CHAQUE page | ✅ Commitée sur `feat/sorties-rapports` (`f5f544f`), fusionnée avec `main` (PR #35 rattrapée) — **550 tests OK** en local (8 tests PDF sautés faute de Pango sur macOS). PR à ouvrir, `PUBLIC_BASE_URL` à ajouter sur Railway | 2026-08-08 |
| 33 | **Bouton « Partager / Imprimer »** (chantier 3) : composant partagé `PartagerFicheModal.vue` — cherche d'abord un lien actif existant, ne publie rien à l'ouverture, affiche le QR *rendu par le serveur* (même code que le PDF, champ `qr` du serializer), l'adresse copiable, le compteur de consultations, le PDF et la révocation en deux temps. Branché sur fiche tournée, fiche spectacle, fiche technicien, et sur le Tableau de bord pour l'horaire d'une journée (la date se choisit dans le panneau, cette feuille n'ayant pas d'objet à elle). Correctif `ReportShareSerializer.validate` : un PATCH partiel (ex. `expires_at` seul) tombait en 400 | ✅ Écrit dans le dépôt — **546 tests OK**, lint à zéro violation, build Vue vert, et les deux écrans vérifiés en captures réelles (navigateur piloté, données de démo) | 2026-08-08 |
| 34 | **Écran de gestion des liens dans Réglages** : section « Liens de partage » listant les liens actifs du projet actif (type, cible, adresse, nombre de consultations, dernier accès) avec PDF / copier / révoquer par ligne, plus les liens RÉVOQUÉS repliés — gardés volontairement, ils sont la trace de ce qui a circulé et de combien il a été consulté | ✅ Écrit dans le dépôt — build Vue vert, section vérifiée en capture réelle (3 liens actifs, 1 révoqué) | 2026-08-08 |
| 35 | **Documentation de référence du chantier rapports** : `schema.md` § 14 (table `report_shares`, contraintes d'unicité partielles et le raisonnement derrière), `security.md` § 6 (modèle de menace du lien public énoncé franchement, 8 garde-fous, ce que ça implique au quotidien, règles pour toute vue ajoutée à `public_views.py`), `architecture.md` § 4octies + workflow 11 (carte des modules, écarts imposés par WeasyPrint) | ✅ Écrite dans le dépôt — identifiants cités vérifiés un à un contre le code | 2026-08-08 |

## Prochaine action concrète

**Ouvrir la PR du chantier « sorties de rapports »** depuis
`feat/sorties-rapports`, puis ajouter la variable `PUBLIC_BASE_URL`
(`https://gear-management-production.up.railway.app`) dans Railway AVANT de
déployer : sans elle, l'URL encodée dans un QR est déduite de la requête
courante — correct tant qu'un PDF sort d'un cycle requête/réponse, faux dès
qu'une tâche planifiée s'en mêle. Un QR faux imprimé en quarante exemplaires
ne se rattrape pas. Vérifier après déploiement que la migration `0030` est
bien appliquée (logs Railway).

**Le chantier « sorties de rapports » est complet** (étapes 32-34) : liens
publics signés, PDF des quatre feuilles, bouton par fiche, écran de gestion.
Sa documentation de référence est à jour (étape 35). **Reste à ouvrir la PR
et à déployer** — avec `PUBLIC_BASE_URL` dans les variables Railway AVANT le
déploiement.

**Chantier documentation utilisateur (étape 31)** : Samuel doit lancer
`python manage.py seed_demo` localement, puis commiter/pousser depuis son
poste — les fichiers sont livrés mais jamais exécutés ni versionnés.

**Saga géocodage toujours ouverte** : Samuel doit resauvegarder une fiche
Lieu avec adresse puis recliquer « Réestimer les distances », et consulter
les logs Railway (`inventory`, niveau INFO, PR #34). Ne pas proposer de
nouveau correctif avant d'avoir lu ces logs.


## Points de vigilance

- **🔴 Saga géocodage non résolue après 3 correctifs (PR #31, #32, #33)** :
  Samuel rapporte à répétition que ses lieux ont bien adresse et
  coordonnées, mais le backend voit toujours `lat=None` au moment de
  réestimer les distances, et les logs Railway ne montraient jusqu'ici
  aucun appel Google (même pas un échec) — signe que la config `LOGGING`
  elle-même était en cause (seul WARNING+ sortait en prod). La PR #34
  ajoute l'instrumentation nécessaire pour trancher entre trois
  hypothèses : la base (coordonnées jamais sauvegardées), le géocodage
  (appel non tenté) ou Google (appel refusé/sans résultat). **Ne pas
  supposer que c'est réglé tant que Samuel n'a pas confirmé après relecture
  des logs.**
- **🟡 Doc de référence en retard sur le lot 21 et sur le chantier transport
  (étapes 23-29)** : `transport_detach` (comportement de suppression), notes
  riches (`clean_notes`/nh3), `touched_shows`, `Venue.display_order`, l'entité
  `Truck`/conflits de camion, le module `transport_ordering.py` et tout le
  géocodage automatique sont absents d'`architecture.md`/
  `recapitulatif_projet.md`/`schema.md` — à rattraper dans une session
  interactive, comme pour les étapes 14-17 (étape 18). **Les sorties de
  rapports (étapes 32-34) sont documentées** (étape 35) : `schema.md` § 14,
  `security.md` § 6, `architecture.md` § 4octies + workflow 11.
- **`main` local en retard d'un merge sur GitHub** — vérifié le
  2026-08-07 via l'API Railway : le dernier déploiement SUCCESS
  (15 h 31 UTC) correspond au commit `51a8f87` (merge PR #35,
  `feat/autocomplete-adresse`), absent de ce clone qui pointe `769cc79`
  (merge PR #34). `git pull` depuis le poste de Samuel avant toute
  nouvelle branche. Règle générale : ne jamais supposer le `main` local à
  jour depuis le bac à sable — `git fetch`/`pull` y échoue systématiquement
  (« Host key verification failed »), seul l'historique de déploiement
  Railway permet de vérifier objectivement ce qui est réellement en ligne.
- **Fichier non suivi `restart-dev.sh`** (racine du repo, script de
  confort pour relancer backend+frontend en local) : présent dans l'arbre
  de travail de ce clone mais jamais committé — à vérifier avec Samuel si
  c'est voulu (utilitaire perso à garder hors dépôt) ou à ajouter au repo.
- **Un seul chantier de code à la fois dans ce dossier** — voir l'incident
  du 2026-08-04 en « Statut global ». Deux sessions Cowork simultanées sur
  le même dossier peuvent se marcher dessus (branche qui change seule,
  fichier modifié en double, lock git orphelin). Rien perdu cette fois, mais
  à éviter activement.
- **`wip/checkpoint-2026-08-04` entièrement vidé de ce qui était récupérable**
  — CSV import/export rapatrié dans l'étape 17, tooltip flottant dans
  l'étape 18. Le reste du checkpoint est périmé (prédate les tournées
  multi-arrêts) — plus rien à en extraire, la branche peut être nettoyée à
  l'occasion.
- **🟡 `schema.md`/`architecture.md`/`recapitulatif_projet.md` rattrapés sur
  la plupart des étapes 14-17** (étape 18, 2026-08-05) — accès par projet,
  tournées multi-arrêts, suppression cascade, export/import CSV+JSON,
  `Venue.color`, `Material.is_kit_parent`. **Reste volontairement non
  documenté** (fonctionnalités frontend pures, sans modèle backend à
  décrire) : puces ⌘+clic, fermeture des modales à Échap, zoom + défilement
  Dashboard/Parcours, thème clair, info-bulle flottante — `CLAUDE.md` reste
  la seule trace de ces détails d'implémentation Vue. Le renvoi cassé vers
  `transport_materials` (`architecture.md`, ~ligne 210) est corrigé (étape
  20) — `schema.md` garde volontairement son saut de numérotation (11 → 13,
  pas de section 12) puisque plus rien n'y renvoie, pas de raison de
  renuméroter.
- `HelloWorld.vue` : résidu du scaffold Vue, plus importé nulle part — à
  supprimer au passage.
- Railway ne supporte pas la phase `release:` — `migrate`/`collectstatic`
  restent dans le `CMD` du Dockerfile.
- Ne pas confondre `inventory.User` (modèle applicatif) et le superutilisateur
  Django (`django.contrib.auth`).
- Protection de branche `main` activée sur GitHub (confirmé le 2026-08-03,
  push direct refusé) — PR obligatoire + 2 status checks, y compris pour un
  changement documentation seule.
- L'estimation automatique de trajet (Google Routes API) reste non testable
  en conditions réelles dans le bac à sable Claude (pas de réseau) — se
  dégrade silencieusement sur la valeur par défaut si la clé est absente.
- Nettoyage de branches (2026-08-05, confirmé par Samuel) : toutes les
  branches `feature/*`/`docs/*` déjà mergées ont été supprimées sur GitHub,
  ainsi que les checkpoints périmés (`wip/checkpoint-2026-07-31`,
  `wip/checkpoint-2026-08-04`) et `chore/agents-ci-review-workflow` (la
  toute première PR du projet, #1, contenu déjà entièrement dans `main`).
  `chore/schema-xref-filter-tests-2026-08-05` (PR #25) n'apparaît plus dans
  les refs distantes locales — supprimée. La branche courante du dossier est
  maintenant `docs/suivi-etape20-2026-08-05` (commit de suivi `3311b20`
  poussé, PR à merger), et elle porte aussi tout le lot 21 non commité.

## Backlog

- **Invite à créer un projet quand aucun n'est actif** (trouvé le
  2026-08-03) : sur un compte neuf sans `Project`, le sélecteur de projet de
  `AppShell.vue` reste vide. Depuis l'écran d'onboarding (étape 16), ce cas
  précis est déjà couvert par un écran bloquant dédié — à revérifier si ce
  point est encore ouvert ou si l'onboarding l'a résolu.
- Listes de matériel par technicien (sortie terrain).
- Rôles admin/viewer une fois OAuth en place (OAuth est en place depuis
  l'étape 7 — les rôles par projet existent déjà via `ProjectMembership`,
  étape 14 ; à confirmer si ce point est encore distinct).
- Budget de location (explicitement reporté après V1).
- Géocodage automatique d'adresse pour `venues.latitude`/`longitude`
  (actuellement saisie manuelle uniquement).

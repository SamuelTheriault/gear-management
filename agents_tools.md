# Outils et agents — Développement de RégiStock

Ce document liste les outils/agents nécessaires à chaque phase du projet, du développement jusqu'à la documentation continue. À utiliser comme feuille de route de coordination (développement prévu avec Claude / Claude Code).

## 1. Planification

- **Claude (conversation)** : scoping fonctionnel, clarification des besoins, décisions d'architecture — déjà fait pour la V1 (voir `schema.md` et `architecture.md`).
- **Fichiers markdown dans le projet Cowork** : `schema.md`, `architecture.md`, `agents_tools.md` comme source de vérité partagée, à garder à jour à chaque décision structurante.

## 2. Développement

- **Claude Code** : génération du backend (API), du frontend, et des migrations de base de données à partir du schéma défini.
- **Base de données** : MySQL 8.0 managé (Railway). Migrations Django versionnées (pas de scripts SQL manuels), pour faciliter les ajustements futurs.
- **Contrôle de version** : Git, dépôt privé sur GitHub (`SamuelTheriault/gear-management`), pour permettre le suivi des changements de code et le retour en arrière si besoin.
- **Environnement local de dev** : SQLite en fallback automatique si `DB_ENGINE` n'est pas configuré — pratique pour tester sans affecter la production Railway.

## 3. Débogage / Tests

- **Claude Code** : écriture de tests pour la logique critique — en particulier la détection de conflits (matériel et techniciens), qui est le cœur fonctionnel de l'app.
- **Tests manuels ciblés** : valider les cas limites de chevauchement d'horaire (ex. buffer qui chevauche exactement la limite, matériel parent/enfant assigné en double).
- **Environnement de staging** : idéalement un environnement de test séparé de la production avant chaque déploiement de mise à jour.

## 4. Review

- **Claude (review de code)** : relecture du code généré avant déploiement, en particulier la logique de validation des conflits et l'intégration OAuth.
- **Revue fonctionnelle par Samuel** : valider que les workflows (création de fiche spectacle, assignation matériel/techniciens, sortie de listes) correspondent à l'usage réel sur le terrain.

## 5. Documentation

- **Fichiers markdown maintenus dans le projet Cowork** : garder `schema.md` et `architecture.md` synchronisés avec l'état réel de l'app à chaque évolution.
- **Documentation utilisateur légère** : un guide rapide (peut être un `usage.md`) pour les workflows courants — créer un spectacle, assigner du matériel, sortir les listes par technicien — utile si d'autres personnes doivent utiliser l'outil éventuellement.

## Résumé du cycle par itération

1. Décision fonctionnelle (Claude, conversation) → mise à jour de `schema.md` / `architecture.md`.
2. Implémentation (Claude Code).
3. Tests ciblés sur la logique de conflits.
4. Review de code + review fonctionnelle.
5. Déploiement sur Railway (automatique depuis `main`).
6. Mise à jour de la documentation.

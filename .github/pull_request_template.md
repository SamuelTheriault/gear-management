<!--
Gabarit de PR — gear-management. But : forcer une vraie pause de revue avant
de merger dans `main` (qui déploie automatiquement sur Railway), même en solo.
-->

## Résumé

<!-- Qu'est-ce que cette PR change, et pourquoi ? -->

## Checklist avant de merger

- [ ] J'ai invoqué le sous-agent `code-reviewer` sur ce diff et traité ses remarques bloquantes.
- [ ] Le code touché est commenté (docstrings sur le nouveau code public — vérifié automatiquement par le job `flake8` en CI, mais relire quand même).
- [ ] Si `Show`, `ShowMaterial`, `ShowTechnician` ou la logique de fenêtre effective/buffers a changé : tests ajoutés/mis à jour (`conflict-logic-tester`), `python manage.py test` passe.
- [ ] Si un modèle a changé : `schema.md`/`architecture.md` mis à jour (`docs-sync`), migrations incluses.
- [ ] Aucun secret en dur (voir `security.md`) — `.env` non commité.
- [ ] La CI est verte (lint docstrings, migrations, tests, build frontend).
- [ ] Si cette PR touche au déploiement : `railway-deploy-checker` passé en revue.

## Notes pour la revue

<!-- Points d'attention particuliers, décisions à valider, zones à risque. -->

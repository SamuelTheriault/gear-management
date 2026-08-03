"""Migration de données pour l'accès multi-tenant par projet (2026-08-02).

Trois choses, décidées avec Samuel (voir CLAUDE.md, note du même jour) :

1. Chaque `User` existant avec `role='admin'` reçoit `is_staff_global=True` —
   préserve l'accès complet qu'il avait de facto aujourd'hui via le bug
   `IsAuthenticated`-seul (voir `permissions.py`), plutôt que de le couper
   sec au déploiement de cette migration.
2. Le compte `samueltheriault@gmail.com` (le seul utilisateur ayant
   réellement utilisé l'outil jusqu'ici) est `get_or_create` puis forcé en
   `is_staff_global=True`, MÊME s'il existait déjà avec un rôle différent —
   Samuel garde un accès staff global séparé du rôle par projet.
3. Samuel devient `owner` actif de chaque `Project` existant
   (`ProjectMembership`, idempotent) — sans ça, aucun projet préexistant
   n'aurait de owner et `HasProjectAccess` (pour tout compte non-staff)
   bloquerait tout dessus.

Volontairement pas de retour en arrière significatif (`reverse_noop`) :
défaire ce provisioning romprait l'accès de Samuel à ses propres projets sans
bénéfice — voir la discussion équivalente sur d'autres migrations de données
du projet (ex. `0013_remove_department`).

**Garde `Project.objects.exists()`** : sans elle, cette migration insère
inconditionnellement une ligne `User` (Samuel) dans TOUTE base sur laquelle
elle tourne — y compris chaque base de test fraîchement créée par `manage.py
test` (les migrations de données s'exécutent aussi contre elle). Ça avait
fait échouer des tests qui comptent les `User` créés dans leur `setUp()`
(ex. `OAuthProvisioningTests`, qui vérifie `InventoryUser.objects.count() ==
1` après un login simulé). Une base neuve (de test ou une vraie nouvelle
installation) n'a par définition aucun `Project` préexistant à préserver —
le flux normal de premier login Google (`signals.py`) suffit pour elle ; pas
besoin d'y préprovisionner Samuel.
"""

from django.db import migrations

SAMUEL_EMAIL = 'samueltheriault@gmail.com'


def provisionner_acces_existants(apps, schema_editor):
    """Voir le docstring de module pour le détail des trois étapes."""
    User = apps.get_model('inventory', 'User')
    Project = apps.get_model('inventory', 'Project')
    ProjectMembership = apps.get_model('inventory', 'ProjectMembership')

    User.objects.filter(role='admin').update(is_staff_global=True)

    if not Project.objects.exists():
        # Rien à préserver sur une base neuve (dont chaque base de test) —
        # voir la note sur cette garde dans le docstring de module.
        return

    samuel, _created = User.objects.get_or_create(
        email=SAMUEL_EMAIL,
        defaults={'name': 'Samuel'},
    )
    if not samuel.is_staff_global:
        samuel.is_staff_global = True
        samuel.save(update_fields=['is_staff_global'])

    for project in Project.objects.all():
        ProjectMembership.objects.get_or_create(
            project=project,
            user=samuel,
            defaults={'role': 'owner', 'status': 'active', 'invited_by': None},
        )


def reverse_noop(apps, schema_editor):
    """Pas de retour en arrière significatif — voir le docstring de module."""


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0019_project_access'),
    ]

    operations = [
        migrations.RunPython(provisionner_acces_existants, reverse_noop),
    ]

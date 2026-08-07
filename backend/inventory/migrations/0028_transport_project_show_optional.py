"""Tournée : FK `project` directe + spectacle desservi OPTIONNEL (2026-08-06).

Décision de Samuel (option « — Aucun spectacle — » au formulaire de création,
pour les retours d'entrepôt et les déplacements logistiques) : une tournée
peut exister sans spectacle desservi. Ça révise le choix du 2026-08-05
documenté dans `transport_detach.py`, qui avait écarté la nullabilité de
`Transport.show` au profit d'un réancrage automatique — le réancrage reste,
mais son échec ne supprime plus la tournée : elle devient « sans spectacle ».

L'isolation par projet passait par `show__project` ; avec un `show` nullable
il faut une FK directe. Trois temps :

1. `AddField Transport.project` (nullable temporairement) ;
2. `RunPython` : `project = show.project` pour toutes les tournées existantes
   (toutes ont un spectacle avant cette migration) ;
3. `AlterField` : `project` non nullable (CASCADE — la suppression d'un
   projet emporte ses tournées, comme avant via le spectacle), `show`
   nullable (SET_NULL en filet de sécurité — la suppression explicite d'un
   spectacle passe par `transport_detach.py`).

Réversible : le sens inverse ne peut pas restaurer un `show` à une tournée
qui n'en a pas — il refuse s'il en existe (à traiter à la main), sinon
retire simplement la colonne `project`.
"""

import django.db.models.deletion
from django.db import migrations, models


def remplir_project(apps, schema_editor):
    """`Transport.project` = projet du spectacle desservi (toujours présent
    avant cette migration)."""
    Transport = apps.get_model('inventory', 'Transport')
    for transport in Transport.objects.select_related('show').all():
        transport.project_id = transport.show.project_id
        transport.save(update_fields=['project'])


def verifier_reversibilite(apps, schema_editor):
    """Refuse le retour arrière s'il existe des tournées sans spectacle — le
    schéma d'avant ne peut pas les représenter."""
    Transport = apps.get_model('inventory', 'Transport')
    orphelines = Transport.objects.filter(show__isnull=True).count()
    if orphelines:
        raise RuntimeError(
            f"{orphelines} tournée(s) sans spectacle : impossible de revenir à un "
            "Transport.show obligatoire sans perdre ces données. Rattache-les ou "
            "supprime-les d'abord."
        )


class Migration(migrations.Migration):
    """Voir le docstring de module."""

    dependencies = [
        ('inventory', '0027_alter_venue_options_venue_display_order'),
    ]

    operations = [
        # --- Temps 1 : FK temporairement nullable ---
        migrations.AddField(
            model_name='transport',
            name='project',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='transports', to='inventory.project'),
        ),
        # --- Temps 2 : données ---
        migrations.RunPython(remplir_project, verifier_reversibilite),
        # --- Temps 3 : resserrage + show optionnel ---
        migrations.AlterField(
            model_name='transport',
            name='project',
            field=models.ForeignKey(help_text="Production à laquelle cette tournée appartient — FK directe ajoutée le 2026-08-06 (migration 0028, remplie depuis show.project) : l'isolation par projet passait jusque-là par `show`, devenu OPTIONNEL (voir ci-dessous). CASCADE : la suppression d'un projet emporte ses tournées, comme avant via le spectacle.", on_delete=django.db.models.deletion.CASCADE, related_name='transports', to='inventory.project'),
        ),
        migrations.AlterField(
            model_name='transport',
            name='show',
            field=models.ForeignKey(blank=True, help_text="Spectacle desservi (l'ARRIVÉE de la tournée) — OPTIONNEL depuis le 2026-08-06 (décision de Samuel : option « Aucun spectacle » au formulaire, pour les retours d'entrepôt et les déplacements logistiques). Révise le choix documenté dans transport_detach.py (2026-08-05), qui avait écarté la nullabilité : une tournée dont le spectacle disparaît sans candidat de réancrage devient « sans spectacle » au lieu d'être supprimée. Sans spectacle, la fenêtre départ/arrivée (validate_transport_window) n'a pas de bornes et les propositions auto ne sont pas concernées (elles naissent toujours d'un spectacle). SET_NULL en filet de sécurité — la suppression EXPLICITE d'un spectacle passe par transport_detach.py, qui fait plus fin.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='transports', to='inventory.show'),
        ),
    ]

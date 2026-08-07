"""Camions de production + distances par segment (2026-08-06, chantier 2).

Décisions de Samuel : entité `Truck` par projet (un camion par défaut à la
création de projet), chaque tournée assignée à UN camion (conflit d'horaire
façon techniciens, voir `conflicts.get_truck_conflicts`), UNE période de
réservation par camion (n° de réservation + n° de contrat + notes), et km
estimé calculé depuis les trajets Google Routes — d'où
`TransportStop.travel_distance_meters`, rempli par le même appel Routes que
la durée (voir `maps.estimate_travel`).

Trois temps, comme les migrations 0025/0028 :

1. Créer `trucks` + le champ distance des arrêts + `Transport.truck`
   temporairement nullable ;
2. `RunPython` : un camion « Camion » par projet existant (les nouveaux
   passent par `signals.creer_camion_par_defaut`), puis chaque tournée
   existante assignée au camion de son projet ;
3. `Transport.truck` non nullable (PROTECT — un camion encore utilisé ne se
   supprime pas, garde lisible dans `TruckViewSet.destroy`).

Réversible : le sens inverse retire les colonnes (les camions et distances
disparaissent, aucune donnée d'un autre modèle n'en dépend).
"""

import django.db.models.deletion
from django.db import migrations, models


def creer_camions_et_assigner(apps, schema_editor):
    """Un camion par défaut par projet existant, et chaque tournée existante
    assignée au camion de son projet."""
    Project = apps.get_model('inventory', 'Project')
    Truck = apps.get_model('inventory', 'Truck')
    Transport = apps.get_model('inventory', 'Transport')

    for project in Project.objects.all():
        Truck.objects.get_or_create(project=project, name='Camion')

    for transport in Transport.objects.all():
        camion = Truck.objects.filter(project_id=transport.project_id).order_by('id').first()
        transport.truck_id = camion.id
        transport.save(update_fields=['truck'])


class Migration(migrations.Migration):
    """Voir le docstring de module."""

    dependencies = [
        ('inventory', '0028_transport_project_show_optional'),
    ]

    operations = [
        # --- Temps 1 : nouvelle table + champs ---
        migrations.CreateModel(
            name='Truck',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(default='Camion', help_text="Nom d'usage (ex. « Cube 16 pi », « Van Catimini »).", max_length=255)),
                ('reservation_start', models.DateField(blank=True, help_text='Début de la période de réservation/location (optionnel).', null=True)),
                ('reservation_end', models.DateField(blank=True, help_text='Fin de la période de réservation/location (optionnel).', null=True)),
                ('reservation_number', models.CharField(blank=True, help_text='Numéro de réservation chez le loueur.', max_length=100)),
                ('contract_number', models.CharField(blank=True, help_text='Numéro de contrat de location.', max_length=100)),
                ('notes', models.TextField(blank=True)),
                ('project', models.ForeignKey(help_text='Production à laquelle ce camion appartient.', on_delete=django.db.models.deletion.CASCADE, related_name='trucks', to='inventory.project')),
            ],
            options={
                'db_table': 'trucks',
                'ordering': ['project', 'name'],
            },
        ),
        migrations.AddField(
            model_name='transportstop',
            name='travel_distance_meters',
            field=models.PositiveIntegerField(blank=True, help_text="Distance du segment depuis l'arrêt précédent, en mètres — remplie par Google Routes en même temps que la durée (2026-08-06, migration 0029). NULL = inconnue (lieux sans GPS, durée saisie à la main, ou segment antérieur à cette migration) : le km estimé du camion (Truck.estimated_distance) l'exclut et le signale plutôt que de compter 0. Toujours NULL sur le premier arrêt.", null=True),
        ),
        migrations.AddField(
            model_name='transport',
            name='truck',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='transports', to='inventory.truck'),
        ),
        # --- Temps 2 : données ---
        migrations.RunPython(creer_camions_et_assigner, migrations.RunPython.noop),
        # --- Temps 3 : resserrage ---
        migrations.AlterField(
            model_name='transport',
            name='truck',
            field=models.ForeignKey(help_text="Camion qui fait cette tournée (ajouté le 2026-08-06, migration 0029). Défaut à la création : le premier camion du projet (voir TransportSerializer). PROTECT : un camion encore assigné à des tournées ne peut pas être supprimé — garde lisible dans TruckViewSet.destroy. Conflit d'horaire entre tournées du même camion : voir conflicts.get_truck_conflicts (bloquant + force).", on_delete=django.db.models.deletion.PROTECT, related_name='transports', to='inventory.truck'),
        ),
    ]

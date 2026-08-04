"""Refonte du module transport en tournées multi-arrêts (2026-08-04).

L'ancien modèle « lieu A → lieu B » de `Transport` (`origin_venue`,
`destination_venue`, `estimated_duration_minutes`, `transport_type`) est
remplacé par une séquence ordonnée d'arrêts (`TransportStop`) : chaque arrêt
porte son lieu et la durée du segment qui l'y amène ; chaque ligne de matériel
(`TransportMaterial`) pointe son arrêt de chargement et de déchargement.
`transport_type` (livraison/ramassage) disparaît sans équivalent — décision de
Samuel du 2026-08-04, il n'avait plus de sens au niveau d'une tournée.

Migration en trois temps, sur le modèle de `0014_material_category` :

1. Créer la table `transport_stops` et les FK temporairement nullables
   `TransportMaterial.load_stop`/`unload_stop`.
2. `RunPython` : chaque transport existant devient une tournée à 2 arrêts —
   arrêt 0 = `origin_venue` (segment 0 min), arrêt 1 = `destination_venue`
   (segment = `estimated_duration_minutes`) — et chacune de ses lignes de
   matériel est rattachée chargement=arrêt 0 / déchargement=arrêt 1. Les
   fenêtres dérivées (`effective_end` = départ + somme des segments) restent
   donc identiques au pixel près à l'ancien calcul.
3. Rendre les FK non nullables, remplacer le `unique_together` de
   `TransportMaterial` (le quadruplet transport/matériel/chargement/
   déchargement — un même matériel peut apparaître sur deux portions
   distinctes d'une même tournée), puis supprimer les quatre anciens champs.

Irréversible (comme 0014) : le sens inverse devrait aplatir une tournée
multi-arrêts en un seul segment, ce qui perdrait des données.
"""

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


def creer_arrets_et_remapper(apps, schema_editor):
    """Transforme chaque transport A → B en tournée à 2 arrêts et rattache ses
    lignes de matériel aux deux arrêts."""
    Transport = apps.get_model('inventory', 'Transport')
    TransportStop = apps.get_model('inventory', 'TransportStop')
    TransportMaterial = apps.get_model('inventory', 'TransportMaterial')

    for transport in Transport.objects.all():
        depart = TransportStop.objects.create(
            transport=transport,
            venue_id=transport.origin_venue_id,
            order=0,
            travel_minutes_from_previous=0,
        )
        arrivee = TransportStop.objects.create(
            transport=transport,
            venue_id=transport.destination_venue_id,
            order=1,
            travel_minutes_from_previous=transport.estimated_duration_minutes,
        )
        TransportMaterial.objects.filter(transport=transport).update(
            load_stop=depart, unload_stop=arrivee,
        )


class Migration(migrations.Migration):
    """Voir le docstring de module."""

    dependencies = [
        ('inventory', '0024_settings_event_type_order'),
    ]

    operations = [
        # --- Temps 1 : nouvelle table + FK temporairement nullables ---
        migrations.CreateModel(
            name='TransportStop',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('order', models.PositiveIntegerField(help_text="Position de l'arrêt dans la séquence (0 = départ de la tournée).")),
                ('travel_minutes_from_previous', models.PositiveIntegerField(default=0, help_text="Durée du segment depuis l'arrêt précédent (trajet + chargement/déchargement), en minutes. Toujours 0 sur le premier arrêt. Pré-remplie via l'API Google Routes quand les deux lieux ont des coordonnées GPS (voir TransportSerializer et inventory/maps.py) ; sinon, valeur par défaut tirée de Settings.")),
                ('transport', models.ForeignKey(help_text='Tournée à laquelle cet arrêt appartient.', on_delete=django.db.models.deletion.CASCADE, related_name='stops', to='inventory.transport')),
                ('venue', models.ForeignKey(help_text='Lieu de cet arrêt.', on_delete=django.db.models.deletion.PROTECT, related_name='transport_stops', to='inventory.venue')),
            ],
            options={
                'db_table': 'transport_stops',
                'ordering': ['transport', 'order'],
                'unique_together': {('transport', 'order')},
            },
        ),
        migrations.AddField(
            model_name='transportmaterial',
            name='load_stop',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='loaded_materials', to='inventory.transportstop'),
        ),
        migrations.AddField(
            model_name='transportmaterial',
            name='unload_stop',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='unloaded_materials', to='inventory.transportstop'),
        ),
        # --- Temps 2 : données ---
        migrations.RunPython(creer_arrets_et_remapper),
        # --- Temps 3 : resserrage + suppression des anciens champs ---
        migrations.AlterField(
            model_name='transportmaterial',
            name='load_stop',
            field=models.ForeignKey(help_text="Arrêt où ce matériel monte dans le camion. Doit précéder `unload_stop` dans la séquence (validé par TransportSerializer) et appartenir à la même tournée. CASCADE : le serializer refuse de supprimer un arrêt encore référencé par une ligne — la cascade ne joue qu'à la suppression de la tournée entière.", on_delete=django.db.models.deletion.CASCADE, related_name='loaded_materials', to='inventory.transportstop'),
        ),
        migrations.AlterField(
            model_name='transportmaterial',
            name='unload_stop',
            field=models.ForeignKey(help_text='Arrêt où ce matériel descend du camion.', on_delete=django.db.models.deletion.CASCADE, related_name='unloaded_materials', to='inventory.transportstop'),
        ),
        migrations.AlterUniqueTogether(
            name='transportmaterial',
            unique_together={('transport', 'material', 'load_stop', 'unload_stop')},
        ),
        migrations.AlterField(
            model_name='transport',
            name='scheduled_datetime',
            field=models.DateTimeField(blank=True, help_text="Heure de départ de la tournée (départ du premier arrêt). Nullable depuis le 2026-07-24 : une proposition auto (status='to_approve') n'a pas encore d'heure tant que l'utilisateur ne l'a pas complétée. Obligatoire pour un déplacement 'confirmed' (imposé par TransportSerializer).", null=True),
        ),
        migrations.AlterField(
            model_name='transportmaterial',
            name='quantity',
            field=models.PositiveIntegerField(default=1, help_text='Quantité de ce matériel transportée sur cette portion de la tournée (ex. 8 des 20 rallonges en inventaire). Voir Material.quantity et transport_coherence.py pour le suivi des emplacements.', validators=[django.core.validators.MinValueValidator(1)]),
        ),
        migrations.AlterField(
            model_name='settings',
            name='default_transport_duration_minutes',
            field=models.PositiveIntegerField(default=60, help_text="Durée de segment par défaut (TransportStop.travel_minutes_from_previous) quand l'estimation Google Routes n'est pas disponible."),
        ),
        migrations.RemoveField(model_name='transport', name='transport_type'),
        migrations.RemoveField(model_name='transport', name='origin_venue'),
        migrations.RemoveField(model_name='transport', name='destination_venue'),
        migrations.RemoveField(model_name='transport', name='estimated_duration_minutes'),
    ]

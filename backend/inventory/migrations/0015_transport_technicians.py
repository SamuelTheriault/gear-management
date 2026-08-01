"""Plusieurs techniciens par déplacement (`TransportTechnician`).

`Transport.technician` était une FK unique : un déplacement ne pouvait
mobiliser qu'une personne. Samuel a demandé le 2026-07-30 de pouvoir en
affecter plusieurs, comme `ShowTechnician` le permet déjà pour un spectacle.

Ordre des opérations : on crée la table de liaison, on y recopie les
affectations existantes, puis seulement ensuite on supprime l'ancien champ —
sinon les données seraient perdues.
"""

import django.db.models.deletion
from django.db import migrations, models


def reprendre_les_affectations(apps, schema_editor):
    """Recopie chaque `Transport.technician` renseigné dans la table de liaison."""
    Transport = apps.get_model('inventory', 'Transport')
    TransportTechnician = apps.get_model('inventory', 'TransportTechnician')

    for transport in Transport.objects.filter(technician__isnull=False):
        TransportTechnician.objects.get_or_create(
            transport=transport, technician_id=transport.technician_id,
        )


def remettre_le_technicien_unique(apps, schema_editor):
    """Inverse : remet la première affectation dans le champ unique.

    Perte de données assumée si un déplacement avait plusieurs techniciens —
    c'est la nature même d'un retour arrière vers un champ unique.
    """
    Transport = apps.get_model('inventory', 'Transport')
    TransportTechnician = apps.get_model('inventory', 'TransportTechnician')

    for transport in Transport.objects.all():
        premier = TransportTechnician.objects.filter(transport=transport).first()
        if premier is not None:
            transport.technician_id = premier.technician_id
            transport.save(update_fields=['technician'])


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0014_material_category'),
    ]

    operations = [
        migrations.CreateModel(
            name='TransportTechnician',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('technician', models.ForeignKey(help_text='Technicien affecté.', on_delete=django.db.models.deletion.CASCADE, related_name='transport_technicians', to='inventory.technician')),
                ('transport', models.ForeignKey(help_text='Déplacement auquel ce technicien est affecté.', on_delete=django.db.models.deletion.CASCADE, related_name='transport_technicians', to='inventory.transport')),
            ],
            options={
                'db_table': 'transport_technicians',
                'ordering': ['transport'],
                'unique_together': {('transport', 'technician')},
            },
        ),
        migrations.RunPython(reprendre_les_affectations, remettre_le_technicien_unique),
        migrations.RemoveField(
            model_name='transport',
            name='technician',
        ),
    ]

"""Transforme `Material.category` en vraie table (`MaterialCategory`).

Avant le 2026-07-30, `category` était un `CharField` restreint à 9 slugs
codés en dur dans le modèle (`CATEGORY_CHOICES`) — impossible d'ajouter une
catégorie sans redéployer. Cette migration crée la table, dote chaque projet
existant des 9 catégories historiques, remappe le matériel vers la ligne
correspondante, puis remplace le champ texte par la FK.

Le passage CharField -> ForeignKey ne peut pas se faire en un seul
`AlterField` : la base tenterait de convertir « audio » en identifiant
entier. On passe donc par un champ temporaire (`category_ref`), rempli par
une migration de données, avant de supprimer l'ancien champ et de renommer.
"""

import django.db.models.deletion
from django.db import migrations, models

# Reprises de MaterialCategory.DEFAULTS / LEGACY_SLUGS — recopiées ici parce
# qu'une migration ne doit pas importer le modèle réel (il évoluera, la
# migration doit rester rejouable telle quelle).
DEFAULTS = [
    ('Audio', 'oklch(0.75 0.13 200)'),
    ('Éclairage', 'oklch(0.78 0.13 85)'),
    ('Vidéo', 'oklch(0.72 0.13 255)'),
    ('Réseau', 'oklch(0.75 0.13 165)'),
    ('Rigging', 'oklch(0.75 0.13 320)'),
    ('Mobilier', 'oklch(0.72 0.13 145)'),
    ('Décor', 'oklch(0.72 0.13 105)'),
    ('Costumes', 'oklch(0.75 0.13 20)'),
    ('Autre', 'rgba(255,255,255,.5)'),
]

LEGACY_SLUGS = {
    'audio': 'Audio',
    'eclairage': 'Éclairage',
    'video': 'Vidéo',
    'reseau': 'Réseau',
    'rigging': 'Rigging',
    'mobilier': 'Mobilier',
    'decor': 'Décor',
    'costumes': 'Costumes',
    'autre': 'Autre',
}


def creer_et_remapper(apps, schema_editor):
    """Crée les catégories par défaut de chaque projet et y rattache le matériel."""
    Project = apps.get_model('inventory', 'Project')
    Material = apps.get_model('inventory', 'Material')
    MaterialCategory = apps.get_model('inventory', 'MaterialCategory')

    for project in Project.objects.all():
        par_nom = {}
        for name, color in DEFAULTS:
            categorie, _ = MaterialCategory.objects.get_or_create(
                project=project, name=name, defaults={'color': color},
            )
            par_nom[name] = categorie

        for material in Material.objects.filter(project=project):
            # `category` vide (jamais renseignée) reste vide : la FK est
            # nullable, on ne force personne dans « Autre ».
            nom = LEGACY_SLUGS.get(material.category)
            if nom is None:
                continue
            material.category_ref = par_nom[nom]
            material.save(update_fields=['category_ref'])


def remettre_les_slugs(apps, schema_editor):
    """Inverse : réécrit le slug historique dans le champ texte."""
    Material = apps.get_model('inventory', 'Material')
    noms_vers_slugs = {nom: slug for slug, nom in LEGACY_SLUGS.items()}

    for material in Material.objects.select_related('category_ref'):
        if material.category_ref_id is None:
            continue
        # Une catégorie créée après la migration n'a pas de slug historique —
        # on retombe sur 'autre' plutôt que de perdre l'information de
        # classement.
        material.category = noms_vers_slugs.get(material.category_ref.name, 'autre')
        material.save(update_fields=['category'])


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0013_remove_department'),
    ]

    operations = [
        migrations.CreateModel(
            name='MaterialCategory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('color', models.CharField(default='rgba(255,255,255,.5)', help_text="Couleur d'affichage (pastille dans les listes, point de couleur sur les assignations). Chaîne CSS libre — les valeurs par défaut sont en oklch(), format déjà utilisé partout dans le frontend.", max_length=64)),
                ('project', models.ForeignKey(help_text='Production à laquelle cette catégorie appartient — voir Project.', on_delete=django.db.models.deletion.PROTECT, related_name='material_categories', to='inventory.project')),
            ],
            options={
                'verbose_name_plural': 'material categories',
                'db_table': 'material_categories',
                'ordering': ['name'],
            },
        ),
        migrations.AddConstraint(
            model_name='materialcategory',
            constraint=models.UniqueConstraint(fields=('project', 'name'), name='unique_material_category_name_per_project'),
        ),
        migrations.AddField(
            model_name='material',
            name='category_ref',
            field=models.ForeignKey(blank=True, help_text="Catégorie de matériel — devenue une FK vers MaterialCategory le 2026-07-30 (c'était une liste de choix figée avant). PROTECT : supprimer une catégorie encore utilisée passe par une réassignation explicite du matériel concerné, voir MaterialCategoryViewSet.destroy.", null=True, on_delete=django.db.models.deletion.PROTECT, related_name='materials', to='inventory.materialcategory'),
        ),
        migrations.RunPython(creer_et_remapper, remettre_les_slugs),
        migrations.RemoveField(
            model_name='material',
            name='category',
        ),
        migrations.RenameField(
            model_name='material',
            old_name='category_ref',
            new_name='category',
        ),
    ]

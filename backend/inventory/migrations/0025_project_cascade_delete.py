# Migration écrite à la main (2026-08-04) — pas de `makemigrations` disponible
# dans ce bac à sable (le venv `backend/venv/` est un binaire macOS,
# incompatible avec ce pont Linux ; voir device_bash). Opérations simples
# (5x `AlterField`, aucune donnée touchée) reproduites à l'identique du
# format que `makemigrations` aurait généré — Samuel : lance
# `python manage.py makemigrations --check --dry-run` pour confirmer qu'elle
# correspond exactement à ce que Django aurait produit avant de l'appliquer.
#
# Change `on_delete` de PROTECT à CASCADE sur les 5 FK `project` (Venue,
# MaterialCategory, Material, Show, Technician) — voir la note « Suppression »
# sur `Project` dans models.py : supprimer un projet doit effacer toute la
# production plutôt que de lever un `ProtectedError` (500). Aucune donnée
# n'est modifiée par cette migration elle-même ; le changement ne prend effet
# qu'au moment où un `Project` est réellement supprimé (nouveau bouton dans
# ProjetDetailView.vue).

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0024_settings_event_type_order'),
    ]

    operations = [
        migrations.AlterField(
            model_name='venue',
            name='project',
            field=models.ForeignKey(help_text='Production à laquelle ce lieu appartient — voir Project.', on_delete=django.db.models.deletion.CASCADE, related_name='venues', to='inventory.project'),
        ),
        migrations.AlterField(
            model_name='materialcategory',
            name='project',
            field=models.ForeignKey(help_text='Production à laquelle cette catégorie appartient — voir Project.', on_delete=django.db.models.deletion.CASCADE, related_name='material_categories', to='inventory.project'),
        ),
        migrations.AlterField(
            model_name='material',
            name='project',
            field=models.ForeignKey(help_text='Production à laquelle ce matériel appartient — voir Project.', on_delete=django.db.models.deletion.CASCADE, related_name='materials', to='inventory.project'),
        ),
        migrations.AlterField(
            model_name='show',
            name='project',
            field=models.ForeignKey(help_text='Production à laquelle ce spectacle appartient — voir Project. Doit correspondre au projet de `venue`.', on_delete=django.db.models.deletion.CASCADE, related_name='shows', to='inventory.project'),
        ),
        migrations.AlterField(
            model_name='technician',
            name='project',
            field=models.ForeignKey(help_text='Production à laquelle ce technicien appartient — voir Project.', on_delete=django.db.models.deletion.CASCADE, related_name='technicians', to='inventory.project'),
        ),
    ]

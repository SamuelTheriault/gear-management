"""
Configuration de l'admin Django — Gestion de matériel.

Sert de back-office minimal (accès `/admin/login/`) pour consulter et
modifier les tables de `schema.md` sans passer par l'API DRF. `ShowMaterial`
et `ShowTechnician` sont éditées en inline sur `Show`/`Material` plutôt que
comme modèles autonomes — voir note en bas de fichier. `Transport` a, lui, un
admin autonome (`TransportAdmin`) : contrairement aux tables d'association,
une vue globale des déplacements (filtrable par technicien/date) a une valeur
propre pour la planification logistique.

Isolation par projet (voir `Project` dans models.py, ajouté le 2026-07-19) :
`VenueAdmin`, `MaterialAdmin`, `TechnicianAdmin` et `ShowAdmin` exposent tous
une colonne/filtre `project` — utile pour naviguer l'admin production par
production tant que le frontend n'a pas de sélecteur de projet dédié.
"""

from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Department,
    Material,
    Project,
    Settings,
    Show,
    ShowMaterial,
    ShowTechnician,
    Technician,
    Transport,
    User,
    Venue,
)


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    """Admin pour les comptes applicatifs (distincts du superutilisateur Django)."""

    list_display = ('name', 'email', 'role', 'created_at')
    list_filter = ('role',)
    search_fields = ('name', 'email')


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    """Admin pour les productions — voir `Project` (models.py) pour la logique d'isolation."""

    list_display = ('name', 'client_name', 'status', 'start_date', 'end_date', 'created_at')
    list_filter = ('status',)
    search_fields = ('name', 'client_name')


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    """Admin pour les lieux (salles, théâtres, sites de représentation, entrepôts), isolés par projet."""

    list_display = (
        'name', 'code', 'project', 'address', 'contact_name', 'contact_info', 'is_storage', 'latitude', 'longitude',
    )
    list_filter = ('project', 'is_storage')
    search_fields = ('name', 'code', 'address', 'contact_name')
    autocomplete_fields = ('project',)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    """Admin pour les départements responsables du matériel, couleur d'identification incluse."""

    list_display = ('name', 'color_swatch', 'contact_name', 'contact_info')
    search_fields = ('name', 'contact_name')

    @admin.display(description='Couleur')
    def color_swatch(self, obj):
        """Aperçu visuel de `Department.color` dans la liste admin."""
        return format_html(
            '<span style="display:inline-block;width:14px;height:14px;'
            'border-radius:3px;border:1px solid #0002;background:{}"></span> {}',
            obj.color, obj.color,
        )


class MaterialInline(admin.TabularInline):
    """Liste les composants (matériel enfant) directement sur la fiche du matériel parent."""

    model = Material
    fk_name = 'parent_material'
    extra = 0
    fields = ('name', 'category', 'ownership_status')
    show_change_link = True


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    """Admin pour l'inventaire de matériel, isolé par projet, avec hiérarchie parent/enfant en inline."""

    list_display = (
        'name', 'project', 'category', 'quantity', 'is_active', 'parent_material', 'venue', 'department',
        'ownership_status',
    )
    list_filter = ('project', 'is_active', 'category', 'ownership_status', 'venue', 'department')
    search_fields = ('name', 'description')
    autocomplete_fields = ('project', 'parent_material', 'venue', 'department')
    inlines = [MaterialInline]
    actions = ['mark_active', 'mark_inactive']

    @admin.action(description="Activer le matériel sélectionné")
    def mark_active(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description="Désactiver le matériel sélectionné")
    def mark_inactive(self, request, queryset):
        queryset.update(is_active=False)


class ShowMaterialInline(admin.TabularInline):
    """Assignations de matériel affichées directement sur la fiche du spectacle."""

    model = ShowMaterial
    extra = 0
    autocomplete_fields = ('material',)


class ShowTechnicianInline(admin.TabularInline):
    """Assignations de techniciens affichées directement sur la fiche du spectacle."""

    model = ShowTechnician
    extra = 0
    autocomplete_fields = ('technician',)


class TransportInline(admin.TabularInline):
    """Déplacements (livraison/ramassage) affichés directement sur la fiche du spectacle."""

    model = Transport
    extra = 0
    autocomplete_fields = ('origin_venue', 'destination_venue', 'technician')


@admin.register(Show)
class ShowAdmin(admin.ModelAdmin):
    """Admin pour les fiches spectacles, isolées par projet, avec matériel, techniciens et
    déplacements assignés en inline."""

    list_display = (
        'title', 'project', 'venue', 'event_type', 'start_datetime', 'end_datetime',
        'buffer_before_minutes', 'buffer_after_minutes',
    )
    list_filter = ('project', 'event_type', 'venue')
    search_fields = ('title', 'notes')
    autocomplete_fields = ('project', 'venue')
    inlines = [ShowMaterialInline, ShowTechnicianInline, TransportInline]


@admin.register(Technician)
class TechnicianAdmin(admin.ModelAdmin):
    """Admin pour les techniciens disponibles pour assignation, isolés par projet."""

    list_display = ('name', 'project', 'specialty', 'contact_info')
    list_filter = ('project',)
    search_fields = ('name', 'specialty')
    autocomplete_fields = ('project',)


@admin.register(Transport)
class TransportAdmin(admin.ModelAdmin):
    """Admin pour les déplacements (livraison/ramassage) — vue globale utile pour la logistique."""

    list_display = (
        'show', 'transport_type', 'origin_venue', 'destination_venue',
        'scheduled_datetime', 'estimated_duration_minutes', 'technician',
    )
    list_filter = ('transport_type', 'technician', 'origin_venue', 'destination_venue')
    search_fields = ('show__title', 'notes')
    autocomplete_fields = ('show', 'origin_venue', 'destination_venue', 'technician')


@admin.register(Settings)
class SettingsAdmin(admin.ModelAdmin):
    """Admin pour les réglages globaux — singleton (une seule ligne, non supprimable).

    `has_add_permission` empêche de créer une deuxième ligne ; `has_delete_permission`
    empêche de supprimer la seule qui existe (voir aussi `Settings.delete()`,
    qui est déjà un no-op par sécurité).
    """

    list_display = (
        'default_buffer_before_minutes', 'default_buffer_after_minutes',
        'default_transport_duration_minutes', 'date_format', 'time_format',
    )

    def has_add_permission(self, request):
        return not Settings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


# ShowMaterial et ShowTechnician sont gérés via les inlines ci-dessus (sur Show
# et Material) plutôt qu'en tant que modèles autonomes dans le menu admin — ce
# sont de simples tables d'association sans intérêt à consulter isolément.
admin.site.register(ShowMaterial)
admin.site.register(ShowTechnician)

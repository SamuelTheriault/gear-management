"""
Configuration de l'admin Django — Gestion de matériel.

Sert de back-office minimal (accès `/admin/login/`) pour consulter et
modifier les 8 tables de `schema.md` sans passer par l'API DRF. `ShowMaterial`
et `ShowTechnician` sont éditées en inline sur `Show`/`Material` plutôt que
comme modèles autonomes — voir note en bas de fichier.
"""

from django.contrib import admin

from .models import (
    Department,
    Material,
    Show,
    ShowMaterial,
    ShowTechnician,
    Technician,
    User,
    Venue,
)


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    """Admin pour les comptes applicatifs (distincts du superutilisateur Django)."""

    list_display = ('name', 'email', 'role', 'created_at')
    list_filter = ('role',)
    search_fields = ('name', 'email')


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    """Admin pour les lieux (salles, théâtres, sites de représentation)."""

    list_display = ('name', 'address', 'contact_name', 'contact_info')
    search_fields = ('name', 'address', 'contact_name')


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    """Admin pour les départements responsables du matériel."""

    list_display = ('name', 'contact_name', 'contact_info')
    search_fields = ('name', 'contact_name')


class MaterialInline(admin.TabularInline):
    """Liste les composants (matériel enfant) directement sur la fiche du matériel parent."""

    model = Material
    fk_name = 'parent_material'
    extra = 0
    fields = ('name', 'category', 'ownership_status')
    show_change_link = True


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    """Admin pour l'inventaire de matériel, avec hiérarchie parent/enfant en inline."""

    list_display = ('name', 'category', 'parent_material', 'venue', 'department', 'ownership_status')
    list_filter = ('category', 'ownership_status', 'venue', 'department')
    search_fields = ('name', 'description')
    autocomplete_fields = ('parent_material', 'venue', 'department')
    inlines = [MaterialInline]


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


@admin.register(Show)
class ShowAdmin(admin.ModelAdmin):
    """Admin pour les fiches spectacles, avec matériel et techniciens assignés en inline."""

    list_display = (
        'title', 'venue', 'event_type', 'start_datetime', 'end_datetime',
        'buffer_before_minutes', 'buffer_after_minutes',
    )
    list_filter = ('event_type', 'venue')
    search_fields = ('title', 'notes')
    autocomplete_fields = ('venue',)
    inlines = [ShowMaterialInline, ShowTechnicianInline]


@admin.register(Technician)
class TechnicianAdmin(admin.ModelAdmin):
    """Admin pour les techniciens disponibles pour assignation."""

    list_display = ('name', 'specialty', 'contact_info')
    search_fields = ('name', 'specialty')


# ShowMaterial et ShowTechnician sont gérés via les inlines ci-dessus (sur Show
# et Material) plutôt qu'en tant que modèles autonomes dans le menu admin — ce
# sont de simples tables d'association sans intérêt à consulter isolément.
admin.site.register(ShowMaterial)
admin.site.register(ShowTechnician)

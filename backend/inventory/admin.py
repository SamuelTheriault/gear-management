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

from .models import (
    Material,
    MaterialCategory,
    Project,
    Settings,
    Show,
    ShowMaterial,
    ShowTechnician,
    Technician,
    Transport,
    TransportStop,
    TransportTechnician,
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


class MaterialInline(admin.TabularInline):
    """Liste les composants (matériel enfant) directement sur la fiche du matériel parent."""

    model = Material
    fk_name = 'parent_material'
    extra = 0
    fields = ('name', 'category', 'ownership_status')
    show_change_link = True


@admin.register(MaterialCategory)
class MaterialCategoryAdmin(admin.ModelAdmin):
    """Admin pour les catégories de matériel (une liste par projet — voir MaterialCategory)."""

    list_display = ('name', 'project', 'color')
    list_filter = ('project',)
    search_fields = ('name',)
    autocomplete_fields = ('project',)


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    """Admin pour l'inventaire de matériel, isolé par projet, avec hiérarchie parent/enfant en inline."""

    list_display = (
        'name', 'project', 'category', 'quantity', 'is_active', 'parent_material', 'venue',
        'ownership_status',
    )
    list_filter = ('project', 'is_active', 'category', 'ownership_status', 'venue')
    search_fields = ('name', 'description')
    autocomplete_fields = ('project', 'parent_material', 'venue', 'category')
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
    """Tournées de matériel affichées directement sur la fiche du spectacle.

    Les arrêts de la séquence ne sont pas éditables ici (un inline ne peut pas
    imbriquer un second inline) — ils se gèrent sur la fiche `TransportAdmin`
    dédiée, via `TransportStopInline`.
    """

    model = Transport
    extra = 0


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


class TransportTechnicianInline(admin.TabularInline):
    """Techniciens affectés à un déplacement (voir TransportTechnician, 2026-07-30)."""

    model = TransportTechnician
    extra = 0
    autocomplete_fields = ('technician',)


class TransportStopInline(admin.TabularInline):
    """Arrêts de la tournée (voir TransportStop, 2026-08-04) — la séquence de
    lieux, dans l'ordre, avec la durée de chaque segment."""

    model = TransportStop
    extra = 0
    autocomplete_fields = ('venue',)
    ordering = ('order',)


@admin.register(Transport)
class TransportAdmin(admin.ModelAdmin):
    """Admin pour les tournées de matériel — vue globale utile pour la logistique.

    Depuis la refonte multi-arrêts (2026-08-04), le trajet s'affiche via la
    séquence d'arrêts (`route`, dérivé) plutôt que les anciens champs
    origine/destination, et s'édite via `TransportStopInline`.
    """

    list_display = ('show', 'route', 'scheduled_datetime', 'total_duration')
    list_filter = ('status', 'stops__venue')
    search_fields = ('show__title', 'notes')
    autocomplete_fields = ('show',)
    # Les techniciens affectés sont passés en inline le 2026-07-30 : un
    # déplacement peut en mobiliser plusieurs (voir TransportTechnician).
    inlines = [TransportStopInline, TransportTechnicianInline]

    @admin.display(description='Trajet')
    def route(self, obj):
        """Séquence des lieux de la tournée, jointe par des flèches."""
        return ' → '.join(str(stop.venue) for stop in obj.ordered_stops) or '—'

    @admin.display(description='Durée totale (min)')
    def total_duration(self, obj):
        """Somme des durées de segment — voir Transport.total_duration_minutes."""
        return obj.total_duration_minutes


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
    # Les 6 champs de couleur (transport + types de spectacle, 2026-08-02)
    # sont éditables via le formulaire de changement par défaut (tous les
    # champs du modèle y apparaissent sans `fields`/`fieldsets` explicite) —
    # pas ajoutés à `list_display`, cette page n'affiche qu'une seule ligne.

    def has_add_permission(self, request):
        return not Settings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


# ShowMaterial et ShowTechnician sont gérés via les inlines ci-dessus (sur Show
# et Material) plutôt qu'en tant que modèles autonomes dans le menu admin — ce
# sont de simples tables d'association sans intérêt à consulter isolément.
admin.site.register(ShowMaterial)
admin.site.register(ShowTechnician)

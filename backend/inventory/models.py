"""
Modèles Django — Gestion de matériel.

Correspond aux tables décrites dans /schema.md (source de vérité fonctionnelle,
à garder synchronisé avec ce fichier à chaque décision structurante) : les 8
tables initiales, plus `transports` (2026-07-18) et `settings` (2026-07-18,
singleton — voir la classe `Settings` ci-dessous).

Note d'architecture : `User` ci-dessous est un modèle applicatif distinct du
superutilisateur Django (django.contrib.auth.models.User) utilisé pour
/admin/login/. Ce dernier reste inchangé. `User` représente les comptes qui
se connectent via Google OAuth (django-allauth + dj-rest-auth) : le champ
`django_user` fait le lien vers le `django.contrib.auth.User` créé par
allauth lors du login social, pour retrouver le bon profil applicatif depuis
la session Django authentifiée (voir inventory/signals.py pour le
provisioning automatique).
"""

from django.conf import settings
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models

#: Valide un code couleur hexadécimal complet (#RRGGBB), tel qu'attendu par
#: un `<input type="color">` HTML — utilisé par `Department.color`.
hex_color_validator = RegexValidator(
    regex=r'^#[0-9A-Fa-f]{6}$',
    message="La couleur doit être un code hexadécimal complet, ex. #3B82F6.",
)


class User(models.Model):
    """Comptes ayant accès à l'outil (login prévu via Google OAuth — voir note de module)."""

    ROLE_ADMIN = 'admin'
    ROLE_VIEWER = 'viewer'
    ROLE_CHOICES = [
        (ROLE_ADMIN, 'Admin'),
        (ROLE_VIEWER, 'Viewer'),
    ]

    email = models.EmailField(unique=True, help_text="Email Google (identifiant de connexion)")
    name = models.CharField(max_length=255)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_VIEWER)
    created_at = models.DateTimeField(auto_now_add=True)
    django_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='inventory_profile',
        help_text=(
            "Compte django.contrib.auth.User associé, créé automatiquement par "
            "django-allauth lors du premier login Google réussi. Permet de "
            "retrouver ce profil applicatif depuis la session Django "
            "authentifiée. Nullable : distinct du superutilisateur Django "
            "(/admin/), qui n'a pas besoin de ce lien."
        ),
    )

    class Meta:
        db_table = 'users'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.email})"


class Settings(models.Model):
    """Réglages globaux de l'application — singleton (une seule ligne, pk=1).

    Ajoutée le 2026-07-18 à la demande de Samuel : centraliser des valeurs
    par défaut et des préférences d'affichage plutôt que de les coder en dur,
    pour pouvoir les ajuster depuis une future page de réglages (frontend
    Vue, pas encore branché) sans redéployer le backend. Les valeurs par
    défaut de `Show.buffer_before_minutes`/`buffer_after_minutes` et de
    `Transport.estimated_duration_minutes` sont lues ici via des callables
    (voir plus bas) plutôt que codées en dur sur ces modèles.
    """

    DATE_FORMAT_DMY = 'DMY'
    DATE_FORMAT_MDY = 'MDY'
    DATE_FORMAT_CHOICES = [
        (DATE_FORMAT_DMY, 'JJ/MM/AAAA'),
        (DATE_FORMAT_MDY, 'MM/DD/YYYY'),
    ]

    TIME_FORMAT_24H = '24h'
    TIME_FORMAT_12H = '12h'
    TIME_FORMAT_CHOICES = [
        (TIME_FORMAT_24H, '24 heures'),
        (TIME_FORMAT_12H, '12 heures (AM/PM)'),
    ]

    default_buffer_before_minutes = models.PositiveIntegerField(
        default=60,
        help_text="Valeur proposée par défaut pour buffer_before_minutes à la création d'un Show.",
    )
    default_buffer_after_minutes = models.PositiveIntegerField(
        default=60,
        help_text="Valeur proposée par défaut pour buffer_after_minutes à la création d'un Show.",
    )
    default_transport_duration_minutes = models.PositiveIntegerField(
        default=60,
        help_text="Valeur proposée par défaut pour estimated_duration_minutes à la création d'un Transport.",
    )
    date_format = models.CharField(max_length=3, choices=DATE_FORMAT_CHOICES, default=DATE_FORMAT_DMY)
    time_format = models.CharField(max_length=3, choices=TIME_FORMAT_CHOICES, default=TIME_FORMAT_24H)

    class Meta:
        db_table = 'settings'
        verbose_name = 'Réglages'
        verbose_name_plural = 'Réglages'

    def __str__(self):
        return "Réglages de l'application"

    def save(self, *args, **kwargs):
        """Force une seule ligne : toujours pk=1, quel que soit l'appelant."""
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Empêche la suppression du singleton — il doit toujours en exister un."""
        return

    @classmethod
    def load(cls):
        """Retourne l'unique ligne de réglages, la crée avec les valeurs par défaut si absente."""
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj


def _default_buffer_before_minutes():
    """Callable de default pour `Show.buffer_before_minutes` — lit `Settings`."""
    return Settings.load().default_buffer_before_minutes


def _default_buffer_after_minutes():
    """Callable de default pour `Show.buffer_after_minutes` — lit `Settings`."""
    return Settings.load().default_buffer_after_minutes


def _default_transport_duration_minutes():
    """Callable de default pour `Transport.estimated_duration_minutes` — lit `Settings`."""
    return Settings.load().default_transport_duration_minutes


class Venue(models.Model):
    """Lieux (salles, théâtres, sites de représentation, entrepôts)."""

    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255, blank=True)
    contact_name = models.CharField(max_length=255, blank=True)
    contact_info = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    is_storage = models.BooleanField(
        default=False,
        help_text=(
            "Lieu d'entreposage (entrepôt) plutôt qu'un vrai lieu de "
            "spectacle. Le matériel assigné (via show_materials) à un Show "
            "dont le venue a is_storage=True est considéré disponible et "
            "ignoré par la détection de conflits — voir conflicts.py."
        ),
    )
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        help_text=(
            "Coordonnée GPS (ex. copiée depuis Google Maps) — utilisée avec "
            "longitude pour estimer automatiquement les temps de trajet des "
            "Transport via l'API Google Routes (voir inventory/maps.py)."
        ),
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        help_text="Coordonnée GPS — voir latitude.",
    )

    class Meta:
        db_table = 'venues'
        ordering = ['name']

    def __str__(self):
        return self.name


class Department(models.Model):
    """Départements responsables du matériel (son, éclairage, décor, costumes...).

    `color` (ajouté le 2026-07-18 à la demande de Samuel) permet d'associer une
    couleur générale à chaque département depuis les réglages ; cette couleur
    est ensuite reflétée dans les sous-sections où le département apparaît
    (ex. `department_color` exposé sur `MaterialSerializer` pour colorer le
    matériel par département dans les listes/plannings du frontend, une fois
    celui-ci branché à l'API).
    """

    DEFAULT_COLOR = '#64748B'  # gris ardoise neutre — utilisé tant qu'aucune couleur n'est choisie

    name = models.CharField(max_length=255)
    contact_name = models.CharField(max_length=255, blank=True)
    contact_info = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    color = models.CharField(
        max_length=7,
        default=DEFAULT_COLOR,
        validators=[hex_color_validator],
        help_text="Code hexadécimal complet (#RRGGBB) utilisé pour identifier visuellement ce département dans l'app.",
    )

    class Meta:
        db_table = 'departments'
        ordering = ['name']

    def __str__(self):
        return self.name


class Material(models.Model):
    """Inventaire de matériel — hiérarchie parent/enfant (kits) + catégorisation."""

    CATEGORY_AUDIO = 'audio'
    CATEGORY_ECLAIRAGE = 'eclairage'
    CATEGORY_VIDEO = 'video'
    CATEGORY_RESEAU = 'reseau'
    CATEGORY_RIGGING = 'rigging'
    CATEGORY_MOBILIER = 'mobilier'
    CATEGORY_DECOR = 'decor'
    CATEGORY_COSTUMES = 'costumes'
    CATEGORY_AUTRE = 'autre'
    CATEGORY_CHOICES = [
        (CATEGORY_AUDIO, 'Audio'),
        (CATEGORY_ECLAIRAGE, 'Éclairage'),
        (CATEGORY_VIDEO, 'Vidéo'),
        (CATEGORY_RESEAU, 'Réseau'),
        (CATEGORY_RIGGING, 'Rigging'),
        (CATEGORY_MOBILIER, 'Mobilier'),
        (CATEGORY_DECOR, 'Décor'),
        (CATEGORY_COSTUMES, 'Costumes'),
        (CATEGORY_AUTRE, 'Autre'),
    ]

    OWNERSHIP_OWNED = 'owned'
    OWNERSHIP_RENTAL = 'rental'
    OWNERSHIP_CHOICES = [
        (OWNERSHIP_OWNED, 'Propriété'),
        (OWNERSHIP_RENTAL, 'Location'),
    ]

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, blank=True)
    parent_material = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='components',
        help_text="Matériel parent (ex. 'Kit Audio' est parent de 'Micro sans fil')",
    )
    venue = models.ForeignKey(
        Venue,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='materials',
        help_text="Lieu physique où le matériel est entreposé",
    )
    department = models.ForeignKey(
        Department,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='materials',
        help_text="Département responsable d'apporter ce matériel sur le lieu du spectacle",
    )
    ownership_status = models.CharField(max_length=10, choices=OWNERSHIP_CHOICES, default=OWNERSHIP_OWNED)
    is_active = models.BooleanField(
        default=True,
        help_text=(
            "Permet de désactiver un matériel qu'on n'utilise plus (ex. un "
            "vieux rideau) sans le supprimer — masqué des listes d'inventaire "
            "par défaut (voir MaterialViewSet), mais reste consultable "
            "individuellement et dans l'historique des assignations "
            "existantes. Ajouté le 2026-07-19."
        ),
    )
    quantity = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text=(
            "Quantité totale possédée de ce matériel identique (ex. 20 rallonges "
            "électriques). Permet d'assigner une partie seulement de l'inventaire "
            "à un spectacle (voir ShowMaterial.quantity) sans créer un item par "
            "unité physique. Doit rester à 1 pour un matériel qui fait partie "
            "d'une hiérarchie kit — parent_material renseigné, ou qui a lui-même "
            "des composants (imposé par MaterialSerializer.validate(), pas ici : "
            "un kit reste une unité conceptuelle unique, ajouté le 2026-07-19)."
        ),
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'materials'
        ordering = ['name']

    def __str__(self):
        return self.name


class Show(models.Model):
    """Fiches spectacles — répétitions et représentations, avec horaires et lieu."""

    EVENT_REHEARSAL = 'rehearsal'
    EVENT_PERFORMANCE = 'performance'
    EVENT_STORAGE = 'storage'
    EVENT_TYPE_CHOICES = [
        (EVENT_REHEARSAL, 'Répétition'),
        (EVENT_PERFORMANCE, 'Représentation'),
        (EVENT_STORAGE, 'Entreposage'),
    ]

    title = models.CharField(max_length=255)
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name='shows')
    event_type = models.CharField(max_length=15, choices=EVENT_TYPE_CHOICES)
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    buffer_before_minutes = models.PositiveIntegerField(default=_default_buffer_before_minutes)
    buffer_after_minutes = models.PositiveIntegerField(default=_default_buffer_after_minutes)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'shows'
        ordering = ['start_datetime']

    def __str__(self):
        return f"{self.title} ({self.get_event_type_display()})"

    @property
    def effective_start(self):
        """Début de la fenêtre effective = start_datetime - buffer_before_minutes.

        Utilisé pour la détection de conflits (voir architecture.md, section 4).
        """
        from datetime import timedelta
        return self.start_datetime - timedelta(minutes=self.buffer_before_minutes)

    @property
    def effective_end(self):
        """Fin de la fenêtre effective = end_datetime + buffer_after_minutes."""
        from datetime import timedelta
        return self.end_datetime + timedelta(minutes=self.buffer_after_minutes)


class ShowMaterial(models.Model):
    """Assignation de matériel à un spectacle/répétition (+ location ponctuelle)."""

    show = models.ForeignKey(Show, on_delete=models.CASCADE, related_name='show_materials')
    material = models.ForeignKey(Material, on_delete=models.CASCADE, related_name='show_materials')
    quantity = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text=(
            "Quantité de ce matériel assignée à ce spectacle (ex. 5 des 20 "
            "rallonges en inventaire). Voir Material.quantity et conflicts.py "
            "pour le calcul de capacité (ajouté le 2026-07-19)."
        ),
    )
    is_rental = models.BooleanField(default=False)
    rental_vendor = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = 'show_materials'
        unique_together = ('show', 'material')
        ordering = ['show']

    def __str__(self):
        return f"{self.material} → {self.show}"


class Technician(models.Model):
    """Techniciens disponibles pour assignation aux spectacles."""

    name = models.CharField(max_length=255)
    contact_info = models.CharField(max_length=255, blank=True)
    specialty = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'technicians'
        ordering = ['name']

    def __str__(self):
        return self.name


class ShowTechnician(models.Model):
    """Assignation de techniciens à un spectacle/répétition."""

    show = models.ForeignKey(Show, on_delete=models.CASCADE, related_name='show_technicians')
    technician = models.ForeignKey(Technician, on_delete=models.CASCADE, related_name='show_technicians')

    class Meta:
        db_table = 'show_technicians'
        unique_together = ('show', 'technician')
        ordering = ['show']

    def __str__(self):
        return f"{self.technician} → {self.show}"


class Transport(models.Model):
    """Livraison ou ramassage de matériel entre deux lieux, pour un spectacle donné.

    Table ajoutée le 2026-07-18 (hors des 8 tables initiales de schema.md) suite
    à un besoin exprimé par Samuel : tracer QUAND le matériel se déplace vers/depuis
    un lieu de spectacle et QUEL technicien s'en charge. Un `Transport` a sa propre
    fenêtre de temps (`scheduled_datetime` + `estimated_duration_minutes`), utilisée
    pour la détection de conflit du technicien assigné — au même titre qu'un
    `ShowTechnician` (voir `conflicts.py`, `get_transport_conflicts` et
    `get_technician_conflicts`, qui vérifient désormais l'un contre l'autre).
    """

    TYPE_DELIVERY = 'delivery'
    TYPE_PICKUP = 'pickup'
    TRANSPORT_TYPE_CHOICES = [
        (TYPE_DELIVERY, 'Livraison'),
        (TYPE_PICKUP, 'Ramassage'),
    ]

    show = models.ForeignKey(
        Show,
        on_delete=models.CASCADE,
        related_name='transports',
        help_text="Spectacle desservi par ce déplacement.",
    )
    transport_type = models.CharField(max_length=10, choices=TRANSPORT_TYPE_CHOICES)
    origin_venue = models.ForeignKey(
        Venue,
        on_delete=models.PROTECT,
        related_name='transports_from',
        help_text="Lieu de départ (souvent un entrepôt pour une livraison).",
    )
    destination_venue = models.ForeignKey(
        Venue,
        on_delete=models.PROTECT,
        related_name='transports_to',
        help_text="Lieu d'arrivée (souvent le lieu du spectacle pour une livraison).",
    )
    scheduled_datetime = models.DateTimeField(help_text="Heure prévue du déplacement.")
    estimated_duration_minutes = models.PositiveIntegerField(
        default=_default_transport_duration_minutes,
        help_text=(
            "Durée estimée du déplacement (trajet + chargement/déchargement). "
            "Pré-remplie automatiquement via l'API Google Routes si les deux "
            "venues ont des coordonnées GPS (voir TransportSerializer et "
            "inventory/maps.py) ; sinon, valeur par défaut tirée de Settings."
        ),
    )
    technician = models.ForeignKey(
        Technician,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='transports',
        help_text="Technicien assigné au déplacement (peut être laissé vide tant que non confirmé).",
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'transports'
        ordering = ['scheduled_datetime']

    def __str__(self):
        return f"{self.get_transport_type_display()} — {self.show} ({self.origin_venue} → {self.destination_venue})"

    @property
    def effective_end(self):
        """Fin de la fenêtre = scheduled_datetime + estimated_duration_minutes."""
        from datetime import timedelta
        return self.scheduled_datetime + timedelta(minutes=self.estimated_duration_minutes)

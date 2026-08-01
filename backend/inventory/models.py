"""
Modèles Django — Gestion de matériel.

Correspond aux tables décrites dans /schema.md (source de vérité fonctionnelle,
à garder synchronisé avec ce fichier à chaque décision structurante) : les 8
tables initiales, plus `transports` (2026-07-18), `settings` (2026-07-18,
singleton — voir la classe `Settings` ci-dessous), et `projects` (2026-07-19,
voir la classe `Project` — isole `Venue`/`Material`/`Technician`/`Show` par
production ; `Settings` reste global).

Le modèle `Department` (responsable/contact par type de matériel) a été
retiré le 2026-07-29 à la demande de Samuel : `Material.category` suffisait
déjà à classer le matériel, et faisait doublon avec les noms de département
en pratique (Son/Éclairage/etc. des deux côtés) — voir migration
`0013_remove_department`.

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
from django.core.validators import MinValueValidator
from django.db import models


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


class Project(models.Model):
    """Une production — regroupe lieux, matériel, techniciens et spectacles propres
    à un engagement précis (ajouté le 2026-07-19 à la demande de Samuel).

    Samuel travaille en parallèle sur plusieurs productions qui n'ont rien en
    commun entre elles (différentes compagnies de danse, musées, biennales
    comme CINARS/Parcours Danse/Furies). `Project` isole donc les données :
    `Venue`, `Material`, `Technician` et `Show` portent chacun un FK
    `project` obligatoire (voir plus bas). `Settings` reste une préférence
    d'affichage globale, pas une donnée de production.

    Pas de vue « tous projets confondus » pour l'instant (décision validée
    avec Samuel) : chaque vue de l'app est toujours filtrée par le projet
    actif (voir `?project=<id>` sur les ViewSets concernés dans `views.py`).
    Conséquence assumée : aucune détection de conflit entre deux projets
    différents (un même technicien réel entré dans deux projets isolés n'est
    jamais reconnu comme la même personne).

    `status` permet d'archiver une production terminée plutôt que de la
    supprimer — basculer d'un projet à l'autre (actif ou archivé) doit rester
    possible à tout moment sans recharger/exporter de fichier, contrairement
    à une sauvegarde classique.
    """

    STATUS_ACTIVE = 'active'
    STATUS_ARCHIVED = 'archived'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Actif'),
        (STATUS_ARCHIVED, 'Archivé'),
    ]

    name = models.CharField(max_length=255)
    client_name = models.CharField(
        max_length=255, blank=True,
        help_text="Compagnie ou organisation cliente, si pertinent (ex. une compagnie de danse, un musée).",
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'projects'
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class Venue(models.Model):
    """Lieux (salles, théâtres, sites de représentation, entrepôts) — isolés par projet."""

    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name='venues',
        help_text="Production à laquelle ce lieu appartient — voir Project.",
    )
    name = models.CharField(max_length=255)
    code = models.CharField(
        max_length=4,
        blank=True,
        help_text=(
            "Code court (jusqu'à 4 caractères, ex. CHAP pour Chapelle) saisi "
            "à la création du lieu — sert d'identifiant rapide, notamment pour "
            "afficher le départ/arrivée d'un Transport de façon compacte (voir "
            "TransportSerializer). Normalisé en majuscules à l'enregistrement. "
            "Unique par projet si renseigné (validé par VenueSerializer, pas "
            "en base — plusieurs lieux sans code coexistent normalement). "
            "Ajouté le 2026-07-19."
        ),
    )
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

    def save(self, *args, **kwargs):
        """Normalise `code` en majuscules (ex. "chap" saisi -> "CHAP" stocké)."""
        if self.code:
            self.code = self.code.upper()
        super().save(*args, **kwargs)


class MaterialCategory(models.Model):
    """Catégories de matériel (Audio, Éclairage, Décor…) — isolées par projet.

    Ajoutée le 2026-07-30 à la demande de Samuel : jusque-là, `Material.category`
    était une liste figée de 9 valeurs codées en dur dans le modèle
    (`CATEGORY_CHOICES`), avec leurs couleurs codées en dur côté Vue — donc
    impossible d'ajouter « Machinerie » ou « Pyrotechnie » sans redéployer.

    Ce n'est PAS un retour du modèle `Department` retiré le 2026-07-29 : une
    catégorie ne porte ni responsable ni contact, seulement un nom et une
    couleur d'affichage. C'est le champ `category` d'avant, rendu éditable.

    **Par projet** (décision de Samuel du 2026-07-30) plutôt que commun à
    toutes les productions : chaque mandat a ses propres besoins de
    classement. `duplicate_project` recopie donc les catégories et remappe le
    matériel copié (voir duplication.py).

    Les 9 valeurs historiques sont créées automatiquement pour chaque nouveau
    projet (voir `DEFAULTS` et le signal dans signals.py), pour ne pas
    démarrer sur une liste vide.
    """

    # Nom + couleur des 9 catégories historiques (ex-`CATEGORY_CHOICES`), dans
    # l'ordre d'affichage du frontend. Les couleurs sont celles qui étaient
    # codées en dur dans les vues Vue (`categoryMeta`), reprises telles quelles
    # pour que rien ne change à l'œil après la migration.
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

    # Correspondance ancien slug -> nom, utilisée par la migration de données
    # 0014 et par la duplication de projet.
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

    DEFAULT_COLOR = 'rgba(255,255,255,.5)'

    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name='material_categories',
        help_text="Production à laquelle cette catégorie appartient — voir Project.",
    )
    name = models.CharField(max_length=100)
    color = models.CharField(
        max_length=64,
        default=DEFAULT_COLOR,
        help_text=(
            "Couleur d'affichage (pastille dans les listes, point de couleur "
            "sur les assignations). Chaîne CSS libre — les valeurs par défaut "
            "sont en oklch(), format déjà utilisé partout dans le frontend."
        ),
    )

    class Meta:
        db_table = 'material_categories'
        ordering = ['name']
        # Unicité en base, contrairement à Venue.code : une catégorie a
        # toujours un nom, il n'y a donc pas de cas « plusieurs lignes vides »
        # à ménager.
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'name'],
                name='unique_material_category_name_per_project',
            ),
        ]
        verbose_name_plural = 'material categories'

    def __str__(self):
        return self.name


class Material(models.Model):
    """Inventaire de matériel — hiérarchie parent/enfant (kits) + catégorisation. Isolé par projet."""

    OWNERSHIP_OWNED = 'owned'
    OWNERSHIP_RENTAL = 'rental'
    OWNERSHIP_CHOICES = [
        (OWNERSHIP_OWNED, 'Propriété'),
        (OWNERSHIP_RENTAL, 'Location'),
    ]

    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name='materials',
        help_text="Production à laquelle ce matériel appartient — voir Project.",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    category = models.ForeignKey(
        MaterialCategory,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='materials',
        help_text=(
            "Catégorie de matériel — devenue une FK vers MaterialCategory le "
            "2026-07-30 (c'était une liste de choix figée avant). PROTECT : "
            "supprimer une catégorie encore utilisée passe par une "
            "réassignation explicite du matériel concerné, voir "
            "MaterialCategoryViewSet.destroy."
        ),
    )
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
    """Fiches spectacles — répétitions et représentations, avec horaires et lieu. Isolées par projet."""

    EVENT_REHEARSAL = 'rehearsal'
    EVENT_PERFORMANCE = 'performance'
    EVENT_STORAGE = 'storage'
    # Ajoutés le 2026-07-31 avec les blocs rattachés (voir `parent_show`) :
    # un montage ou un démontage est un événement à part entière — il occupe
    # le lieu, mobilise une équipe et du matériel — simplement rattaché à
    # l'événement qu'il sert.
    EVENT_SETUP = 'setup'
    EVENT_TEARDOWN = 'teardown'
    EVENT_TYPE_CHOICES = [
        (EVENT_REHEARSAL, 'Répétition'),
        (EVENT_PERFORMANCE, 'Représentation'),
        (EVENT_STORAGE, 'Entreposage'),
        (EVENT_SETUP, 'Montage'),
        (EVENT_TEARDOWN, 'Démontage'),
    ]

    # Types de blocs qui HÉRITENT des ressources de leur événement (2026-07-31,
    # précision de Samuel). Un montage et un démontage manipulent forcément le
    # matériel du spectacle avec son équipe : les assigner séparément serait
    # une deuxième vérité à maintenir. Une répétition rattachée, elle, est un
    # vrai temps de travail autonome — on n'y utilise pas nécessairement tout
    # le matériel du spectacle, ni la même équipe. Elle reçoit donc une COPIE
    # des assignations de l'événement à sa création (voir
    # `ShowSerializer.create`), qu'on ajuste ensuite librement.
    INHERITING_PHASE_TYPES = (EVENT_SETUP, EVENT_TEARDOWN)

    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name='shows',
        help_text="Production à laquelle ce spectacle appartient — voir Project. Doit correspondre au projet de `venue`.",
    )
    title = models.CharField(max_length=255)
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name='shows')
    event_type = models.CharField(max_length=15, choices=EVENT_TYPE_CHOICES)
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    buffer_before_minutes = models.PositiveIntegerField(default=_default_buffer_before_minutes)
    buffer_after_minutes = models.PositiveIntegerField(default=_default_buffer_after_minutes)
    parent_show = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='phases',
        help_text=(
            "Événement principal auquel ce bloc est rattaché — montage ou "
            "répétition en amont, démontage en aval (ajouté le 2026-07-31). "
            "Un bloc rattaché est un `Show` à part entière : il a son lieu, "
            "ses horaires, et participe à la détection de conflits comme "
            "n'importe quel événement. Ses ressources dépendent de son type — "
            "voir `INHERITING_PHASE_TYPES` et `inherits_resources`. Un seul "
            "niveau — un bloc ne peut pas lui-même en avoir (validé par "
            "ShowSerializer). CASCADE : supprimer l'événement principal "
            "supprime ses blocs, ils n'ont pas de sens seuls."
        ),
    )
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

    @property
    def engagement_start(self):
        """Début de la fenêtre d'ENGAGEMENT des ressources de cet événement.

        Le matériel et les techniciens d'un événement sont mobilisés dès son
        montage et jusqu'à la fin de son démontage (décision de Samuel du
        2026-07-31 : « pour le montage et le démontage, le matériel et le
        technicien sont les mêmes que le spectacle »). La fenêtre s'étend donc
        sur l'événement ET ses blocs de montage/démontage.

        Elle ne couvre PAS un bloc de répétition rattaché (précision du
        2026-07-31) : celui-ci porte ses propres assignations, copiées de
        l'événement à sa création puis ajustables. L'étendre jusqu'à lui
        mettrait l'événement en conflit avec sa propre répétition, les deux
        réclamant le même matériel sur une période commune.

        Distincte de `effective_start`, qui reste la fenêtre du seul créneau
        et sert au conflit de LIEU — un bloc occupe la salle pour son propre
        compte, en tant qu'événement.

        Sur un bloc, cette propriété renvoie sa propre fenêtre effective : un
        bloc hérité n'a pas d'assignation à défendre, un bloc de répétition
        répond pour les siennes sur son seul créneau.
        """
        if self.parent_show_id is not None:
            return self.effective_start
        debuts = [self.effective_start]
        debuts += [p.effective_start for p in self.phases.all() if p.inherits_resources]
        return min(debuts)

    @property
    def engagement_end(self):
        """Fin de la fenêtre d'engagement — voir `engagement_start`."""
        if self.parent_show_id is not None:
            return self.effective_end
        fins = [self.effective_end]
        fins += [p.effective_end for p in self.phases.all() if p.inherits_resources]
        return max(fins)

    @property
    def inherits_resources(self):
        """Ce bloc utilise-t-il le matériel et l'équipe de son événement ?

        Vrai pour un montage ou un démontage rattaché, faux partout ailleurs —
        y compris pour un bloc de répétition, qui est autonome (voir
        `INHERITING_PHASE_TYPES`). Un événement principal répond faux : il ne
        tient ses ressources de personne.
        """
        return self.parent_show_id is not None and self.event_type in self.INHERITING_PHASE_TYPES

    @property
    def family_ids(self):
        """Ids de l'événement, de son parent et de tous les blocs de la fratrie.

        Un événement et ses blocs rattachés (montage/démontage) occupent le
        même lieu à la suite. Leurs fenêtres EFFECTIVES se touchent, et se
        chevauchent dès qu'un buffer est renseigné : sans cette exclusion, un
        montage collé à son spectacle serait signalé comme conflit de lieu
        avec lui — voir `get_venue_conflicts` (décision du 2026-07-31, « les
        buffers restent mais sans double comptage »).
        """
        racine = self.parent_show_id or self.id
        ids = {racine}
        ids.update(
            Show.objects.filter(parent_show_id=racine).values_list('id', flat=True)
        )
        ids.add(self.id)
        return ids


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
    """Techniciens disponibles pour assignation aux spectacles. Isolés par projet."""

    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name='technicians',
        help_text="Production à laquelle ce technicien appartient — voir Project.",
    )
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

    STATUS_CONFIRMED = 'confirmed'
    STATUS_TO_APPROVE = 'to_approve'
    STATUS_CHOICES = [
        (STATUS_CONFIRMED, 'Confirmé'),
        (STATUS_TO_APPROVE, 'À approuver'),
    ]

    status = models.CharField(
        max_length=12,
        choices=STATUS_CHOICES,
        default=STATUS_CONFIRMED,
        help_text=(
            "Cycle de vie du déplacement. 'confirmed' : créé/complété par "
            "l'utilisateur, participe à la timeline de position et à la "
            "détection de conflit du technicien. 'to_approve' : proposition "
            "générée automatiquement (voir transport_autogen.py) quand du "
            "matériel est requis à un lieu où rien ne l'amène — pré-remplie "
            "(lieux + matériel) mais incomplète (heure/technicien à saisir), "
            "affichée en orange. Une proposition NE compte PAS comme livraison "
            "tant qu'elle n'est pas confirmée. Ajouté le 2026-07-24."
        ),
    )
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
    scheduled_datetime = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Heure prévue du déplacement. Nullable depuis le 2026-07-24 : une "
            "proposition auto (status='to_approve') n'a pas encore d'heure "
            "tant que l'utilisateur ne l'a pas complétée. Obligatoire pour un "
            "déplacement 'confirmed' (imposé par TransportSerializer)."
        ),
    )
    estimated_duration_minutes = models.PositiveIntegerField(
        default=_default_transport_duration_minutes,
        help_text=(
            "Durée estimée du déplacement (trajet + chargement/déchargement). "
            "Pré-remplie automatiquement via l'API Google Routes si les deux "
            "venues ont des coordonnées GPS (voir TransportSerializer et "
            "inventory/maps.py) ; sinon, valeur par défaut tirée de Settings."
        ),
    )
    # Le champ `technician` (FK unique) a été remplacé le 2026-07-30 par la
    # table de liaison `TransportTechnician` ci-dessous — un déplacement peut
    # mobiliser plusieurs personnes. Voir migration `0015_transport_technicians`.
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'transports'
        ordering = ['scheduled_datetime']

    def __str__(self):
        return f"{self.get_transport_type_display()} — {self.show} ({self.origin_venue} → {self.destination_venue})"

    @property
    def effective_end(self):
        """Fin de la fenêtre = scheduled_datetime + estimated_duration_minutes.

        `None` si `scheduled_datetime` n'est pas encore renseigné (proposition
        auto 'to_approve' non complétée) — un tel déplacement n'a pas de fenêtre
        exploitable et est ignoré par les timelines/conflits jusqu'à sa
        confirmation.
        """
        from datetime import timedelta
        if self.scheduled_datetime is None:
            return None
        return self.scheduled_datetime + timedelta(minutes=self.estimated_duration_minutes)

    @property
    def is_confirmed(self):
        """True si le déplacement est confirmé ET a une heure — donc réellement
        exploitable dans les timelines de position et la détection de conflit."""
        return self.status == self.STATUS_CONFIRMED and self.scheduled_datetime is not None


class TransportTechnician(models.Model):
    """Techniciens affectés à un `Transport` (table de liaison, ajoutée le 2026-07-30).

    Remplace l'ancien champ `Transport.technician` (FK unique) : Samuel a
    demandé de pouvoir affecter plusieurs personnes à un même déplacement,
    exactement comme `ShowTechnician` le permet déjà pour un spectacle.

    Volontairement **sans hiérarchie ni rôle** (décision de Samuel du
    2026-07-30) : pas de chauffeur/responsable distingué des renforts, et pas
    de champ de rôle par assignation — le rôle reste la spécialité du
    technicien (`Technician.specialty`), comme pour `ShowTechnician`.

    Chaque personne affectée compte individuellement dans la détection de
    conflit (voir `conflicts.py`) : un technicien ne peut pas conduire un
    déplacement et être en salle au même moment.
    """

    transport = models.ForeignKey(
        Transport,
        on_delete=models.CASCADE,
        related_name='transport_technicians',
        help_text="Déplacement auquel ce technicien est affecté.",
    )
    technician = models.ForeignKey(
        Technician,
        on_delete=models.CASCADE,
        related_name='transport_technicians',
        help_text="Technicien affecté.",
    )

    class Meta:
        db_table = 'transport_technicians'
        unique_together = ('transport', 'technician')
        ordering = ['transport']

    def __str__(self):
        return f"{self.technician} → {self.transport}"


class TransportMaterial(models.Model):
    """Matériel transporté par un `Transport` (table de liaison, ajoutée le 2026-07-24).

    Ajoutée à la demande de Samuel pour le module transport : jusqu'ici un
    `Transport` savait QUAND et OÙ le matériel se déplaçait, mais pas QUEL
    matériel montait dans le camion. Cette table relie explicitement chaque
    déplacement au matériel (et à la quantité) qu'il transporte, ce qui permet
    au module de cohérence (voir `transport_coherence.py`) de vérifier deux
    choses : (1) que le matériel requis à un lieu de spectacle y est bien amené
    par un transport — « tout déplacement de matériel est associé à un
    transport » ; (2) que l'origine d'un transport est cohérente — le matériel
    qu'il prétend transporter se trouve bien au lieu de départ à ce moment.

    `quantity` permet de ne transporter qu'une partie du matériel possédé en
    plusieurs exemplaires (ex. 8 des 20 rallonges). Un même matériel n'apparaît
    qu'une fois par transport (`unique_together`) — regrouper la quantité sur
    une seule ligne plutôt que d'empiler des doublons.
    """

    transport = models.ForeignKey(
        Transport,
        on_delete=models.CASCADE,
        related_name='transport_materials',
        help_text="Déplacement qui transporte ce matériel.",
    )
    material = models.ForeignKey(
        Material,
        on_delete=models.CASCADE,
        related_name='transport_materials',
        help_text="Matériel transporté.",
    )
    quantity = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text=(
            "Quantité de ce matériel transportée par ce déplacement (ex. 8 des "
            "20 rallonges en inventaire). Voir Material.quantity et "
            "transport_coherence.py pour le suivi des emplacements."
        ),
    )

    class Meta:
        db_table = 'transport_materials'
        unique_together = ('transport', 'material')
        ordering = ['transport']

    def __str__(self):
        return f"{self.material} × {self.quantity} → {self.transport}"

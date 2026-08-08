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

import secrets

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


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
    is_staff_global = models.BooleanField(
        default=False,
        help_text=(
            "Accès de dépannage/support réservé à l'exploitant de la "
            "plateforme (Samuel), ajouté le 2026-08-02 quand l'app est "
            "devenue multi-tenant (abonnements vendus à d'autres directeurs "
            "techniques/compagnies). Distinct de `role` ci-dessus, qui reste "
            "un rôle global purement d'affichage côté frontend "
            "(UtilisateursView.vue) et ne gate rien côté API. "
            "`is_staff_global` COURT-CIRCUITE entièrement le contrôle "
            "d'accès par projet (voir `ProjectMembership` et "
            "`HasProjectAccess` dans permissions.py) — utile pour le "
            "support/dépannage sur les projets clients une fois l'outil "
            "vendu. Ne pas confondre avec un rôle `owner` de "
            "`ProjectMembership`, qui ne donne accès qu'à SES projets."
        ),
    )
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
        help_text="Durée de segment par défaut (TransportStop.travel_minutes_from_previous) quand l'estimation Google Routes n'est pas disponible.",
    )
    date_format = models.CharField(max_length=3, choices=DATE_FORMAT_CHOICES, default=DATE_FORMAT_DMY)
    time_format = models.CharField(max_length=3, choices=TIME_FORMAT_CHOICES, default=TIME_FORMAT_24H)

    # Couleurs des bandes qui ne sont rattachées à aucune fiche éditable
    # (contrairement à `Venue.color`/`MaterialCategory.color`) — ajoutées le
    # 2026-08-02 à la demande de Samuel. `transport_color` couvrait déjà tout
    # déplacement confirmé (Dashboard + Parcours Matériel) via le jeton CSS
    # fixe `--transport` ; les 5 couleurs `event_color_*` couvrent
    # `Show.EVENT_TYPE_CHOICES`, jusqu'ici dupliquées en dur dans 4 fichiers
    # Vue distincts (voir CLAUDE.md, 2026-08-02). Même convention que
    # `Venue.color`/`MaterialCategory.color` : chaîne CSS libre, pas de
    # validation de format — les défauts reprennent tels quels les valeurs
    # « badge » qui étaient codées en dur (pas les teintes plus foncées que
    # `DashboardView.vue` appliquait spécifiquement à Montage/Démontage sur
    # sa timeline : cette nuance devient une déclinaison calculée par
    # `color-mix()` côté frontend à partir de cette même couleur de base,
    # plutôt qu'une deuxième valeur stockée — une seule source par type).
    transport_color = models.CharField(
        max_length=64,
        default='oklch(0.64 0.21 340)',
        help_text="Couleur des déplacements confirmés (Dashboard, Parcours Matériel).",
    )
    event_color_rehearsal = models.CharField(
        max_length=64,
        default='oklch(0.8 0.13 85)',
        help_text="Couleur du type de spectacle Répétition.",
    )
    event_color_performance = models.CharField(
        max_length=64,
        default='oklch(0.75 0.13 320)',
        help_text="Couleur du type de spectacle Représentation.",
    )
    event_color_storage = models.CharField(
        max_length=64,
        default='rgba(var(--fg-rgb),.6)',
        help_text="Couleur du type de spectacle Entreposage.",
    )
    event_color_setup = models.CharField(
        max_length=64,
        default='oklch(0.75 0.13 165)',
        help_text="Couleur du type de bloc Montage.",
    )
    event_color_teardown = models.CharField(
        max_length=64,
        default='oklch(0.7 0.11 255)',
        help_text="Couleur du type de bloc Démontage.",
    )
    # Ordre d'affichage des types (2026-08-02, demande de Samuel : pouvoir le
    # changer depuis les Réglages, ce qui réordonne aussi les puces de filtre
    # du Tableau de bord et de Spectacles). Stocké en CSV plutôt qu'en table
    # dédiée : c'est une préférence d'affichage globale à 6 valeurs, du même
    # ordre de grandeur que `date_format` juste au-dessus.
    #
    # Chaîne vide = ordre par défaut. La lecture passe TOUJOURS par
    # `event_type_order_list` : un type inconnu y est ignoré et un type
    # manquant rajouté à sa place canonique, pour qu'une valeur écrite par une
    # version antérieure (ou un futur 7e type) ne fasse jamais disparaître une
    # ligne de l'écran.
    event_type_order = models.CharField(
        max_length=200,
        blank=True,
        default='',
        help_text=(
            "Ordre d'affichage des types, séparés par des virgules (ex. "
            "'rehearsal,setup,performance,teardown,transport,storage'). Vide "
            "= ordre par défaut."
        ),
    )

    class Meta:
        db_table = 'settings'
        verbose_name = 'Réglages'
        verbose_name_plural = 'Réglages'

    # Ordre canonique : le déroulement réel d'une production (répétition,
    # montage, représentation, démontage), puis les deux types qui ne sont pas
    # des moments de plateau. Sert de défaut ET de référence pour compléter un
    # ordre enregistré incomplet. `transport` n'est pas un `Show.event_type` —
    # c'est un `Transport`, mais il partage la même liste de puces côté
    # frontend, donc le même ordre.
    EVENT_TYPE_ORDER_DEFAULT = (
        'rehearsal', 'setup', 'performance', 'teardown', 'transport', 'storage',
    )

    def __str__(self):
        return "Réglages de l'application"

    @property
    def event_type_order_list(self):
        """Ordre d'affichage des types, toujours complet et sans doublon.

        Les clés inconnues sont ignorées et les manquantes ajoutées à leur
        place canonique : une valeur enregistrée par une version antérieure
        (ou l'ajout d'un 7e type plus tard) ne peut donc pas faire disparaître
        une ligne de l'écran de réglages ni une puce de filtre.
        """
        connus = list(self.EVENT_TYPE_ORDER_DEFAULT)
        enregistres = [cle.strip() for cle in (self.event_type_order or '').split(',')]
        ordre = []
        for cle in enregistres:
            if cle in connus and cle not in ordre:
                ordre.append(cle)
        ordre += [cle for cle in connus if cle not in ordre]
        return ordre

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

    **Suppression** (2026-08-04, décision de Samuel — jusque-là volontairement
    non implémentée, voir historique de `ProjetDetailView.vue`) : `Venue`,
    `MaterialCategory`, `Material`, `Show` et `Technician` référencent tous ce
    modèle en `CASCADE` plutôt qu'en `PROTECT` — supprimer un `Project`
    efface donc TOUTE la production (lieux, matériel, catégories, techniciens,
    spectacles, et par ricochet leurs transports/assignations, déjà en
    CASCADE plus bas dans la chaîne). Irréversible, sans corbeille. Le
    frontend (`ProjetDetailView.vue`) exige de retaper le nom du projet avant
    d'activer le bouton — friction purement côté UI, la permission réelle
    reste `HasProjectAccess` + `owner_only_actions` (`ProjectViewSet`).

    `status` permet d'archiver une production terminée plutôt que de la
    supprimer — basculer d'un projet à l'autre (actif ou archivé) doit rester
    possible à tout moment sans recharger/exporter de fichier, contrairement
    à une sauvegarde classique.

    **Accès** (2026-08-02, quand l'app est devenue multi-tenant — abonnements
    vendus à d'autres directeurs techniques/compagnies) : un `Project` n'a
    plus « pas de propriétaire » comme documenté avant cette date — voir
    `ProjectMembership` ci-dessous, qui relie chaque `User` ayant accès à ce
    projet avec un rôle (`owner`/`editor`/`viewer`). Le contrôle réel se fait
    côté API via `HasProjectAccess` (permissions.py), pas par une contrainte
    de ce modèle.
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


class ProjectMembership(models.Model):
    """Accès d'un `User` applicatif à un `Project`, avec un rôle (ajouté le
    2026-08-02, quand l'app est devenue multi-tenant — abonnements vendus à
    d'autres directeurs techniques/compagnies, plus seulement Samuel).

    Trois rôles, **par projet** (décision de Samuel — ne pas rouvrir) :
    - `owner` : gère les accès du projet (cette table) + édite tout le reste.
    - `editor` : édite tout SAUF la gestion des accès.
    - `viewer` : lecture seule.

    Le contrôle réel est fait par `HasProjectAccess` (permissions.py), pas
    par ce modèle lui-même — cette table n'est que la source de vérité que
    cette permission interroge. `User.is_staff_global` (voir plus haut)
    contourne entièrement ce contrôle : un accès de dépannage plateforme,
    distinct d'un accès `owner` qui reste limité à SES projets.

    **Flux d'invitation** (décision de Samuel : pas d'envoi de courriel
    automatique pour l'instant, aucune infra SMTP configurée) :
    `ProjectMembershipViewSet.create` (réservé owner/staff) réutilise ou crée
    un `User` par email — `status='pending'` tant que cette personne ne s'est
    jamais connectée via Google (`User.django_user_id` encore nul),
    `status='active'` d'emblée si elle a déjà un compte lié. Un `status`
    `pending` NE COMPTE PAS comme un accès actif — voir `HasProjectAccess`.
    `signals.py` (`provisionner_utilisateur_inventory`) active automatiquement
    les memberships `pending` de l'email qui vient de compléter son premier
    login Google, exactement comme le pré-provisioning global déjà en place
    pour `User` lui-même.
    """

    ROLE_OWNER = 'owner'
    ROLE_EDITOR = 'editor'
    ROLE_VIEWER = 'viewer'
    ROLE_CHOICES = [
        (ROLE_OWNER, 'Owner'),
        (ROLE_EDITOR, 'Editor'),
        (ROLE_VIEWER, 'Viewer'),
    ]

    STATUS_PENDING = 'pending'
    STATUS_ACTIVE = 'active'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'En attente'),
        (STATUS_ACTIVE, 'Actif'),
    ]

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='memberships',
        help_text="Projet auquel cet accès donne droit.",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='project_memberships',
        help_text="Compte applicatif qui reçoit l'accès (jamais nullable — voir le flux d'invitation ci-dessus).",
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_VIEWER)
    invited_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='invitations_sent',
        help_text="Utilisateur qui a envoyé l'invitation — nul pour l'appartenance créée automatiquement (ex. le créateur d'un projet).",
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'project_memberships'
        unique_together = ('project', 'user')
        ordering = ['project_id', 'role']

    def __str__(self):
        return f"{self.user} → {self.project} ({self.role}, {self.status})"


class Venue(models.Model):
    """Lieux (salles, théâtres, sites de représentation, entrepôts) — isolés par projet."""

    # CASCADE (2026-08-04, était PROTECT) : voir la note « Suppression » sur
    # Project ci-dessus — supprimer le projet efface ce lieu avec lui.
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
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
    color = models.CharField(
        max_length=64,
        blank=True,
        default='',
        help_text=(
            "Couleur d'affichage optionnelle pour les bandes représentant ce "
            "lieu (Parcours Matériel) — chaîne CSS libre (ex. oklch(...)). "
            "Vide par défaut : la couleur reste générée automatiquement "
            "(palette cyclée par ordre d'apparition, voir ParcoursMaterielView.vue) "
            "— ce champ ne fait que permettre de la fixer manuellement pour un "
            "lieu donné. Ajouté le 2026-08-02 à la demande de Samuel."
        ),
    )

    # Ordre d'affichage choisi par l'utilisateur (2026-08-05, demande de
    # Samuel : réordonner les lieux depuis la page Lieux, ce qui réordonne
    # aussi les puces de filtre du Tableau de bord — même principe que
    # `Settings.event_type_order` pour les types).
    #
    # Tous les lieux existants restent à 0 : le tri secondaire par nom
    # reproduit alors exactement l'ordre d'avant, aucune migration de données
    # n'est nécessaire.
    display_order = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Rang d'affichage dans le projet (0 = non classé). À égalité, le "
            "tri se fait par nom — c'est l'ordre par défaut."
        ),
    )

    class Meta:
        db_table = 'venues'
        ordering = ['display_order', 'name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        """Normalise `code` en majuscules et place un nouveau lieu EN FIN de
        liste si le projet a déjà été réordonné.

        Sans ça, un lieu créé après un réordonnancement naîtrait à
        `display_order = 0` et passerait donc devant tous les autres —
        exactement l'inverse de ce que promet `VenueViewSet.reorder`
        (relecture du 2026-08-05).

        La condition « déjà réordonné » compte : sur un projet qui ne l'a
        jamais été, tous les lieux restent à 0 et le tri secondaire par nom
        garde l'ordre alphabétique d'origine. Attribuer un rang dès la
        création ferait basculer ces projets-là en ordre de création, ce qui
        n'est pas ce qu'on veut.
        """
        if self.code:
            self.code = self.code.upper()
        if self._state.adding and not self.display_order and self.project_id:
            dernier = (
                Venue.objects
                .filter(project_id=self.project_id)
                .aggregate(models.Max('display_order'))['display_order__max']
            )
            if dernier:
                self.display_order = dernier + 1
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

    # CASCADE (2026-08-04, était PROTECT) : voir Project — supprimer le
    # projet efface cette catégorie avec lui.
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
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

    # CASCADE (2026-08-04, était PROTECT) : voir Project — supprimer le
    # projet efface ce matériel avec lui.
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
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
    is_kit_parent = models.BooleanField(
        default=False,
        help_text=(
            "Active ce matériel comme parent de kit possible — limite la liste "
            "affichée dans le sélecteur « Fait partie du kit » d'un autre "
            "matériel (MaterialSerializer.validate_parent_material refuse un "
            "parent qui n'a pas ce drapeau) et fait apparaître sur sa fiche une "
            "section pour lui ajouter directement des composants. Un matériel "
            "à quantity > 1 ne peut pas être marqué ainsi (voir "
            "MaterialSerializer.validate(), même esprit que la contrainte sur "
            "quantity ci-dessous). Ajouté le 2026-08-02 à la demande de Samuel "
            "— décision actée avec lui : pas de bascule automatique sur les "
            "kits existants (déjà des composants), à réactiver manuellement au "
            "cas par cas."
        ),
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

    # CASCADE (2026-08-04, était PROTECT) : voir Project — supprimer le
    # projet efface ce spectacle (et ses transports/assignations, déjà en
    # CASCADE) avec lui.
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='shows',
        help_text="Production à laquelle ce spectacle appartient — voir Project. Doit correspondre au projet de `venue`.",
    )
    # Nullable au sens Django (`blank=True`) depuis le 2026-08-02 : pour un
    # bloc rattaché, ce champ n'est plus le nom complet mais une précision
    # optionnelle — voir `display_title`. Reste obligatoire (validé par
    # `ShowSerializer`) pour un événement top-level.
    title = models.CharField(max_length=255, blank=True)
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
        if self.parent_show_id is not None:
            return self.display_title
        return f"{self.title} ({self.get_event_type_display()})"

    @property
    def display_title(self):
        """Titre à afficher — dynamique pour un bloc, stocké tel quel sinon.

        Signalé par Samuel (2026-08-02) : le titre d'un bloc rattaché était
        généré UNE FOIS à sa création (« Répétition — Nom du spectacle »,
        recopié dans `title`) et ne bougeait plus si l'événement était
        renommé ensuite — un doublon qui divergeait. Ici, rien n'est stocké :
        le nom de l'événement est relu à chaque fois sur `parent_show.title`,
        qui reste la seule vérité.

        Pour un bloc, `title` n'est donc plus le nom complet mais une
        précision optionnelle ajoutée après le type (ex. `title="technique"`
        → « Répétition technique — Vertiges » ; `title=""` → « Répétition —
        Vertiges »). Pour un événement top-level, `title` reste le nom
        complet et `display_title` lui est identique.
        """
        if self.parent_show_id is None:
            return self.title
        label = self.get_event_type_display()
        if self.title:
            label = f"{label} {self.title}"
        return f"{label} — {self.parent_show.title}"

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

    # CASCADE (2026-08-04, était PROTECT) : voir Project — supprimer le
    # projet efface ce technicien avec lui.
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
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


class Truck(models.Model):
    """Camion de production — ajouté le 2026-08-06 (décision de Samuel,
    chantier 2 des travaux transport ; migration `0029`).

    Chaque projet reçoit UN camion par défaut à sa création (« Camion », voir
    `signals.creer_camion_par_defaut` — même pattern que les catégories de
    matériel), et la migration en a doté les projets existants. Chaque
    tournée (`Transport.truck`) est assignée à un camion, avec détection de
    conflit d'horaire comme pour les techniciens : un camion ne peut pas
    faire deux tournées qui se chevauchent (bloquant + `force`, voir
    `conflicts.get_truck_conflicts`).

    Réservation : UNE période par camion (décision de Samuel — une deuxième
    location = une deuxième fiche camion, ex. « Cube 16 pi — semaine 2 »),
    avec numéro de réservation et de contrat. Une tournée planifiée hors de
    la période déclenche un AVERTISSEMENT non bloquant côté API/frontend
    (`TransportSerializer.truck_reservation_warning`) — c'est un rappel de
    logistique, pas une règle d'horaire.

    Km estimé : somme des distances des segments (voir
    `TransportStop.travel_distance_meters`, rempli par Google Routes en même
    temps que la durée) des tournées CONFIRMÉES et horodatées du camion —
    « le km estimé calculé selon les trajets Google Maps approuvés »
    (Samuel). Les segments sans distance connue (lieux sans GPS, durée
    saisie à la main) ne comptent pas : `estimated_distance()` retourne
    aussi ce décompte pour que l'affichage dise « au moins X km » plutôt que
    de faire passer un total partiel pour complet.
    """

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='trucks',
        help_text="Production à laquelle ce camion appartient.",
    )
    name = models.CharField(
        max_length=255,
        default='Camion',
        help_text="Nom d'usage (ex. « Cube 16 pi », « Van Catimini »).",
    )
    reservation_start = models.DateField(
        null=True,
        blank=True,
        help_text="Début de la période de réservation/location (optionnel).",
    )
    reservation_end = models.DateField(
        null=True,
        blank=True,
        help_text="Fin de la période de réservation/location (optionnel).",
    )
    reservation_number = models.CharField(
        max_length=100,
        blank=True,
        help_text="Numéro de réservation chez le loueur.",
    )
    contract_number = models.CharField(
        max_length=100,
        blank=True,
        help_text="Numéro de contrat de location.",
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'trucks'
        ordering = ['project', 'name']

    def __str__(self):
        return f"{self.name} ({self.project})"

    def estimated_distance(self):
        """Distance estimée parcourue par ce camion, d'après les tournées
        confirmées et horodatées qui lui sont assignées.

        Retourne `(meters, missing_segments)` : la somme des
        `travel_distance_meters` connus des segments (arrêts d'ordre > 0), et
        le nombre de segments SANS distance connue — pour afficher un total
        honnête (« au moins X km ») quand l'estimation Routes n'a pas couvert
        toute la route.
        """
        stops = TransportStop.objects.filter(
            transport__truck=self,
            transport__status=Transport.STATUS_CONFIRMED,
            transport__scheduled_datetime__isnull=False,
            order__gt=0,
        )
        meters = 0
        missing = 0
        for stop in stops:
            if stop.travel_distance_meters is None:
                missing += 1
            else:
                meters += stop.travel_distance_meters
        return meters, missing


class Transport(models.Model):
    """Tournée de matériel : une séquence ordonnée d'arrêts (voir `TransportStop`),
    pour un spectacle donné.

    Table ajoutée le 2026-07-18 (hors des 8 tables initiales de schema.md) suite
    à un besoin exprimé par Samuel : tracer QUAND le matériel se déplace vers/depuis
    un lieu de spectacle et QUEL(S) technicien(s) s'en chargent.

    **Refonte en tournées multi-arrêts (2026-08-04, décision de Samuel)** :
    l'ancien modèle « lieu A → lieu B » (`origin_venue`/`destination_venue` +
    `estimated_duration_minutes`) est remplacé par une liste ordonnée d'arrêts
    (`TransportStop`) — arrêt 1 on ramasse du matériel, arrêt 2 on en ajoute,
    arrêt 3 on décharge, etc. Chaque ligne de matériel (`TransportMaterial`)
    pointe son arrêt de chargement ET de déchargement : « quel matériel monte
    où et descend où » est une donnée stockée, pas une reconstruction. Un
    ancien transport A → B est simplement une tournée à 2 arrêts (voir la
    migration `0025_transport_stops`). `transport_type` (livraison/ramassage)
    a été retiré en même temps — Samuel n'en voyait pas l'utilité, et il
    n'avait plus de sens au niveau d'une tournée.

    Horaire (décision de Samuel du 2026-08-04) : UNE heure d'ancrage
    (`scheduled_datetime`, le départ du premier arrêt) + une durée par segment
    (`TransportStop.travel_minutes_from_previous`, trajet + chargement) — les
    heures d'arrivée aux arrêts sont dérivées (`arrival_at`), et décaler toute
    la tournée reste un seul champ à changer (le glisser-déposer du Dashboard
    en dépend). La fenêtre d'engagement des techniciens couvre toute la
    tournée : `[scheduled_datetime, effective_end]` — voir `conflicts.py`.
    """

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
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='transports',
        help_text=(
            "Production à laquelle cette tournée appartient — FK directe "
            "ajoutée le 2026-08-06 (migration 0028, remplie depuis "
            "show.project) : l'isolation par projet passait jusque-là par "
            "`show`, devenu OPTIONNEL (voir ci-dessous). CASCADE : la "
            "suppression d'un projet emporte ses tournées, comme avant via "
            "le spectacle."
        ),
    )
    truck = models.ForeignKey(
        Truck,
        on_delete=models.PROTECT,
        related_name='transports',
        help_text=(
            "Camion qui fait cette tournée (ajouté le 2026-08-06, migration "
            "0029). Défaut à la création : le premier camion du projet (voir "
            "TransportSerializer). PROTECT : un camion encore assigné à des "
            "tournées ne peut pas être supprimé — garde lisible dans "
            "TruckViewSet.destroy. Conflit d'horaire entre tournées du même "
            "camion : voir conflicts.get_truck_conflicts (bloquant + force)."
        ),
    )
    show = models.ForeignKey(
        Show,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='transports',
        help_text=(
            "Spectacle desservi (l'ARRIVÉE de la tournée) — OPTIONNEL depuis "
            "le 2026-08-06 (décision de Samuel : option « Aucun spectacle » "
            "au formulaire, pour les retours d'entrepôt et les déplacements "
            "logistiques). Révise le choix documenté dans transport_detach.py "
            "(2026-08-05), qui avait écarté la nullabilité : une tournée dont "
            "le spectacle disparaît sans candidat de réancrage devient « sans "
            "spectacle » au lieu d'être supprimée. Sans spectacle, la fenêtre "
            "départ/arrivée (validate_transport_window) n'a pas de bornes et "
            "les propositions auto ne sont pas concernées (elles naissent "
            "toujours d'un spectacle). SET_NULL en filet de sécurité — la "
            "suppression EXPLICITE d'un spectacle passe par "
            "transport_detach.py, qui fait plus fin."
        ),
    )
    scheduled_datetime = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Heure de départ de la tournée (départ du premier arrêt). Nullable "
            "depuis le 2026-07-24 : une proposition auto (status='to_approve') "
            "n'a pas encore d'heure tant que l'utilisateur ne l'a pas "
            "complétée. Obligatoire pour un déplacement 'confirmed' (imposé "
            "par TransportSerializer)."
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
        stops = self.ordered_stops
        trajet = ' → '.join(str(stop.venue) for stop in stops) if stops else '(sans arrêt)'
        rattachement = self.show if self.show_id is not None else 'sans spectacle'
        return f"Tournée — {rattachement} ({trajet})"

    @property
    def ordered_stops(self):
        """Arrêts de la tournée, triés par `order`.

        Trie en Python plutôt qu'en SQL pour profiter du cache de
        `prefetch_related('stops__venue')` quand il est présent (listes,
        serializers) — un `.order_by()` relancerait une requête par tournée.
        """
        return sorted(self.stops.all(), key=lambda stop: stop.order)

    @property
    def first_stop(self):
        """Premier arrêt de la tournée (le point de départ), ou None si la
        tournée n'a encore aucun arrêt (état transitoire à la création)."""
        stops = self.ordered_stops
        return stops[0] if stops else None

    @property
    def last_stop(self):
        """Dernier arrêt de la tournée (la destination finale), ou None."""
        stops = self.ordered_stops
        return stops[-1] if stops else None

    @property
    def origin_venue(self):
        """Lieu du premier arrêt — équivalent de l'ancien champ `origin_venue`
        (retiré le 2026-08-04), dérivé des arrêts. `None` sans arrêt."""
        stop = self.first_stop
        return stop.venue if stop is not None else None

    @property
    def origin_venue_id(self):
        """Id du lieu du premier arrêt — pendant de la propriété `origin_venue`."""
        stop = self.first_stop
        return stop.venue_id if stop is not None else None

    @property
    def destination_venue(self):
        """Lieu du dernier arrêt — équivalent de l'ancien champ
        `destination_venue` (retiré le 2026-08-04), dérivé des arrêts."""
        stop = self.last_stop
        return stop.venue if stop is not None else None

    @property
    def destination_venue_id(self):
        """Id du lieu du dernier arrêt — pendant de la propriété `destination_venue`."""
        stop = self.last_stop
        return stop.venue_id if stop is not None else None

    @property
    def total_duration_minutes(self):
        """Durée totale de la tournée : somme des durées de segment de tous les
        arrêts (`travel_minutes_from_previous`, 0 sur le premier arrêt).

        Remplace l'ancien champ `estimated_duration_minutes` (retiré le
        2026-08-04) — une tournée à 2 arrêts donne exactement la même valeur.
        """
        return sum(stop.travel_minutes_from_previous for stop in self.stops.all())

    def arrival_at(self, stop):
        """Heure d'arrivée dérivée à un arrêt : `scheduled_datetime` + cumul des
        durées de segment jusqu'à cet arrêt inclus. `None` si la tournée n'a
        pas encore d'heure (proposition non complétée)."""
        from datetime import timedelta
        if self.scheduled_datetime is None:
            return None
        cumul = sum(
            s.travel_minutes_from_previous
            for s in self.ordered_stops
            if s.order <= stop.order
        )
        return self.scheduled_datetime + timedelta(minutes=cumul)

    @property
    def effective_end(self):
        """Fin de la fenêtre = arrivée au dernier arrêt (`scheduled_datetime` +
        somme des durées de segment).

        `None` si `scheduled_datetime` n'est pas encore renseigné (proposition
        auto 'to_approve' non complétée) — une telle tournée n'a pas de fenêtre
        exploitable et est ignorée par les timelines/conflits jusqu'à sa
        confirmation.
        """
        from datetime import timedelta
        if self.scheduled_datetime is None:
            return None
        return self.scheduled_datetime + timedelta(minutes=self.total_duration_minutes)

    @property
    def is_confirmed(self):
        """True si le déplacement est confirmé ET a une heure — donc réellement
        exploitable dans les timelines de position et la détection de conflit."""
        return self.status == self.STATUS_CONFIRMED and self.scheduled_datetime is not None


class TransportStop(models.Model):
    """Arrêt d'une tournée (`Transport`), ajouté le 2026-08-04 avec la refonte
    en tournées multi-arrêts — voir le docstring de `Transport`.

    Chaque arrêt porte son lieu, sa position dans la séquence (`order`, 0 pour
    le départ) et la durée du segment qui l'amène depuis l'arrêt précédent
    (`travel_minutes_from_previous` — trajet + chargement/déchargement,
    toujours 0 sur le premier arrêt, imposé par `TransportSerializer`).
    L'heure d'arrivée n'est PAS stockée : elle est dérivée
    (`Transport.arrival_at`) de l'heure de départ de la tournée + le cumul des
    segments — décision de Samuel du 2026-08-04 (une seule heure d'ancrage).

    Deux arrêts consécutifs doivent avoir des lieux différents (validé par le
    serializer), mais un même lieu peut revenir plus loin dans la séquence —
    c'est ce qui permet une tournée aller-retour (entrepôt → salle → entrepôt)
    en une seule fiche.
    """

    transport = models.ForeignKey(
        Transport,
        on_delete=models.CASCADE,
        related_name='stops',
        help_text="Tournée à laquelle cet arrêt appartient.",
    )
    venue = models.ForeignKey(
        Venue,
        on_delete=models.PROTECT,
        related_name='transport_stops',
        help_text="Lieu de cet arrêt.",
    )
    order = models.PositiveIntegerField(
        help_text="Position de l'arrêt dans la séquence (0 = départ de la tournée).",
    )
    travel_minutes_from_previous = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Durée du segment depuis l'arrêt précédent (trajet + "
            "chargement/déchargement), en minutes. Toujours 0 sur le premier "
            "arrêt. Pré-remplie via l'API Google Routes quand les deux lieux "
            "ont des coordonnées GPS (voir TransportSerializer et "
            "inventory/maps.py) ; sinon, valeur par défaut tirée de Settings."
        ),
    )
    travel_distance_meters = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Distance du segment depuis l'arrêt précédent, en mètres — "
            "remplie par Google Routes en même temps que la durée (2026-08-06, "
            "migration 0029). NULL = inconnue (lieux sans GPS, durée saisie à "
            "la main, ou segment antérieur à cette migration) : le km estimé "
            "du camion (Truck.estimated_distance) l'exclut et le signale "
            "plutôt que de compter 0. Toujours NULL sur le premier arrêt."
        ),
    )

    class Meta:
        db_table = 'transport_stops'
        unique_together = ('transport', 'order')
        ordering = ['transport', 'order']

    def __str__(self):
        return f"Arrêt {self.order} — {self.venue} ({self.transport_id})"

    @property
    def arrival_datetime(self):
        """Heure d'arrivée dérivée à cet arrêt — voir `Transport.arrival_at`."""
        return self.transport.arrival_at(self)


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
    plusieurs exemplaires (ex. 8 des 20 rallonges).

    **Tournées multi-arrêts (2026-08-04)** : chaque ligne pointe maintenant son
    arrêt de chargement (`load_stop`) et de déchargement (`unload_stop`) — le
    matériel monte dans le camion à l'arrivée au premier et en descend à
    l'arrivée au second. C'est LA donnée qui associe chaque bloc de matériel à
    sa portion de la séquence (demande de Samuel) : rien n'est reconstruit
    côté affichage. Le `unique_together` couvre le quadruplet — le même
    matériel peut légitimement apparaître deux fois dans une tournée pour une
    répartition (ex. 8 rallonges chargées au départ, 3 déposées à l'arrêt 1 et
    5 à l'arrêt 2 = deux lignes), mais pas deux lignes identiques (regrouper
    la quantité).
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
            "Quantité de ce matériel transportée sur cette portion de la "
            "tournée (ex. 8 des 20 rallonges en inventaire). Voir "
            "Material.quantity et transport_coherence.py pour le suivi des "
            "emplacements."
        ),
    )
    load_stop = models.ForeignKey(
        'TransportStop',
        on_delete=models.CASCADE,
        related_name='loaded_materials',
        help_text=(
            "Arrêt où ce matériel monte dans le camion. Doit précéder "
            "`unload_stop` dans la séquence (validé par TransportSerializer) "
            "et appartenir à la même tournée. CASCADE : le serializer refuse "
            "de supprimer un arrêt encore référencé par une ligne — la "
            "cascade ne joue qu'à la suppression de la tournée entière."
        ),
    )
    unload_stop = models.ForeignKey(
        'TransportStop',
        on_delete=models.CASCADE,
        related_name='unloaded_materials',
        help_text="Arrêt où ce matériel descend du camion.",
    )

    class Meta:
        db_table = 'transport_materials'
        unique_together = ('transport', 'material', 'load_stop', 'unload_stop')
        ordering = ['transport']

    def __str__(self):
        return f"{self.material} × {self.quantity} → {self.transport}"


# ---------------------------------------------------------------------------
# Partage public en lecture seule (2026-08-08, chantier « sorties de rapports »)
# ---------------------------------------------------------------------------


def generate_share_token():
    """Jeton d'URL d'un `ReportShare` — 16 octets d'aléa cryptographique, soit
    22 caractères URL-safe et 128 bits d'entropie.

    C'est LE secret qui protège la fiche : il n'y a pas de mot de passe
    derrière. 128 bits rend l'énumération sans objet (comparer aux ~2^128
    essais nécessaires), et `secrets` — pas `random` — garantit un générateur
    non prédictible même en connaissant des jetons déjà émis.

    Longueur volontairement modeste : le jeton finit encodé dans un code QR
    imprimé, et chaque caractère ajoute des modules donc réduit la taille de
    chaque module à surface constante. 22 caractères tiennent dans un QR de
    version raisonnable, lisible à 25 mm même photocopié.
    """
    return secrets.token_urlsafe(16)


class ReportShare(models.Model):
    """Lien public, en lecture seule, vers UNE sortie de rapport imprimable.

    Ajouté le 2026-08-08 avec le chantier des sorties de rapports. Le besoin
    vient du code QR imprimé en pied de feuille : un technicien pigiste ou le
    directeur technique d'une salle partenaire doit pouvoir scanner et lire la
    version à jour en deux secondes, sur son téléphone, sans compte. Or toute
    l'API est derrière `IsAuthenticated` + `HasProjectAccess`, et la garde du
    routeur Vue renvoie vers `/bienvenue` tout compte sans `ProjectMembership`
    actif : sans ce modèle, un QR mènerait à un écran de login puis à un
    cul-de-sac.

    **Le jeton EST l'authentification** (voir `generate_share_token`). Qui
    détient l'URL lit la fiche. C'est un choix assumé, pas un oubli — le
    scénario réel est une feuille papier qui circule sur un quai de
    déchargement, et exiger un mot de passe la rendrait inutilisable. Trois
    garde-fous compensent :

    1. **Portée d'un seul objet.** Un partage pointe UNE tournée, UN
       spectacle, UN technicien ou UNE journée — jamais le projet entier.
       Un lien qui fuite expose une feuille, pas la production.
    2. **Révocable et expirable.** `revoked_at` coupe l'accès immédiatement ;
       `expires_at` (optionnel) le fait expirer tout seul.
    3. **Lecture seule et non indexable.** Les vues publiques (voir
       `public_views.py`) n'exposent aucune écriture et envoient
       `X-Robots-Tag: noindex`.

    **Un partage par cible, réutilisé** (décision structurante) : demander
    deux fois le lien d'une même tournée renvoie le MÊME jeton, tant qu'il
    n'est pas révoqué — d'où les contraintes d'unicité partielles ci-dessous.
    Sans ça, réimprimer une feuille émettrait un nouveau jeton et périmerait
    silencieusement toutes les copies déjà distribuées sur le terrain. C'est
    exactement ce qu'il ne faut pas : le QR d'une feuille imprimée en août
    doit encore fonctionner en octobre. Corollaire assumé : révoquer un lien
    parce qu'il a fuité invalide aussi toutes les copies papier légitimes —
    c'est le comportement voulu, et la raison pour laquelle la révocation est
    une action explicite et non automatique.

    **Suppression de la cible** : chaque FK est en CASCADE. Supprimer une
    tournée efface son partage, et le QR déjà imprimé répond 404 plutôt que
    de pointer vers une fiche fantôme ou, pire, vers un objet recréé plus tard
    avec le même identifiant.
    """

    KIND_TRANSPORT = 'transport'
    KIND_SHOW = 'show'
    KIND_TECHNICIAN = 'technician'
    KIND_DAY = 'day'
    KIND_CHOICES = [
        (KIND_TRANSPORT, 'Fiche de transport'),
        (KIND_SHOW, 'Fiche spectacle'),
        (KIND_TECHNICIAN, 'Parcours technicien'),
        (KIND_DAY, 'Horaire de la journée'),
    ]

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='report_shares',
        help_text=(
            "Production à laquelle ce partage appartient. Redondant avec le "
            "projet de la cible pour les trois types qui en ont une, mais "
            "indispensable pour `day` (qui n'a pas de FK) et pour lister les "
            "partages d'un projet sans quatre jointures."
        ),
    )
    kind = models.CharField(
        max_length=12,
        choices=KIND_CHOICES,
        help_text="Type de sortie — détermine laquelle des cibles ci-dessous est renseignée.",
    )
    token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        default=generate_share_token,
        editable=False,
        help_text="Secret d'URL — voir generate_share_token(). Jamais réémis pour une même cible.",
    )

    # --- Cibles (exactement une renseignée, selon `kind` — voir CheckConstraint) ---
    transport = models.ForeignKey(
        'Transport', on_delete=models.CASCADE, null=True, blank=True,
        related_name='report_shares',
        help_text="Tournée partagée (kind='transport').",
    )
    show = models.ForeignKey(
        'Show', on_delete=models.CASCADE, null=True, blank=True,
        related_name='report_shares',
        help_text="Spectacle partagé (kind='show').",
    )
    technician = models.ForeignKey(
        'Technician', on_delete=models.CASCADE, null=True, blank=True,
        related_name='report_shares',
        help_text="Technicien dont le parcours est partagé (kind='technician').",
    )
    day = models.DateField(
        null=True, blank=True,
        help_text="Journée partagée (kind='day') — l'horaire de tout le projet ce jour-là.",
    )

    # --- Cycle de vie ---
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_report_shares',
        help_text="Compte qui a émis le lien. SET_NULL : retirer une personne du projet ne doit pas casser les feuilles déjà imprimées.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(
        null=True, blank=True,
        help_text=(
            "Expiration optionnelle. Laissé vide par défaut : une feuille de "
            "tournée doit rester lisible pendant toute la production, et une "
            "date d'expiration mal choisie transforme un QR en cul-de-sac au "
            "pire moment (sur le quai, sans réseau pour appeler Samuel)."
        ),
    )
    revoked_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Révocation manuelle — coupe l'accès immédiatement, y compris pour les copies papier déjà distribuées.",
    )

    # --- Traces d'accès (diagnostic, pas analytique) ---
    last_accessed_at = models.DateTimeField(null=True, blank=True)
    access_count = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Nombre de consultations. Sert à répondre à « est-ce que le monde "
            "scanne vraiment le code ? » et à repérer un lien anormalement "
            "sollicité. Incrémenté en base via F() — voir public_views.py."
        ),
    )

    class Meta:
        db_table = 'report_shares'
        ordering = ['-created_at']
        constraints = [
            # Exactement une cible renseignée, cohérente avec `kind`.
            models.CheckConstraint(
                name='report_share_cible_coherente',
                condition=(
                    models.Q(kind='transport', transport__isnull=False, show__isnull=True,
                             technician__isnull=True, day__isnull=True)
                    | models.Q(kind='show', show__isnull=False, transport__isnull=True,
                               technician__isnull=True, day__isnull=True)
                    | models.Q(kind='technician', technician__isnull=False, transport__isnull=True,
                               show__isnull=True, day__isnull=True)
                    | models.Q(kind='day', day__isnull=False, transport__isnull=True,
                               show__isnull=True, technician__isnull=True)
                ),
            ),
            # Un seul partage ACTIF par cible — voir le docstring de classe.
            models.UniqueConstraint(
                fields=['transport'], condition=models.Q(revoked_at__isnull=True),
                name='report_share_unique_actif_transport',
            ),
            models.UniqueConstraint(
                fields=['show'], condition=models.Q(revoked_at__isnull=True),
                name='report_share_unique_actif_show',
            ),
            models.UniqueConstraint(
                fields=['technician'], condition=models.Q(revoked_at__isnull=True),
                name='report_share_unique_actif_technician',
            ),
            models.UniqueConstraint(
                fields=['project', 'day'], condition=models.Q(revoked_at__isnull=True),
                name='report_share_unique_actif_day',
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} — {self.token[:6]}…"

    @property
    def is_active(self):
        """True si le lien répond encore : ni révoqué, ni expiré."""
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None and self.expires_at <= timezone.now():
            return False
        return True

    @property
    def path(self):
        """Chemin public de la page à jour — c'est CE chemin qu'encode le QR.

        `/p/<token>` et non `/api/...` : le QR est scanné par un humain avec
        un téléphone, il doit tomber sur une page lisible, pas sur du JSON.
        Le catch-all SPA de `config/urls.py` sert le build Vue sur ce chemin
        (voir `frontend_views.spa_index`), et la route `/p/:token` du routeur
        Vue est exemptée de la garde d'authentification.
        """
        return f'/p/{self.token}'

"""
Modèles Django — Gestion de matériel.

Correspond aux 8 tables décrites dans /schema.md (source de vérité fonctionnelle,
à garder synchronisé avec ce fichier à chaque décision structurante).

Note d'architecture : `User` ci-dessous est un modèle applicatif distinct du
superutilisateur Django (django.contrib.auth.models.User) utilisé pour
/admin/login/. Ce dernier reste inchangé pour l'instant. `User` représente les
comptes qui se connecteront éventuellement via Google OAuth (voir
recapitulatif_projet.md, étape 7 — hors scope de cette tâche). Le lien entre
les deux (le cas échéant) sera fait lors de l'implémentation de l'OAuth.
"""

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

    class Meta:
        db_table = 'users'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.email})"


class Venue(models.Model):
    """Lieux (salles, théâtres, sites de représentation)."""

    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255, blank=True)
    contact_name = models.CharField(max_length=255, blank=True)
    contact_info = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'venues'
        ordering = ['name']

    def __str__(self):
        return self.name


class Department(models.Model):
    """Départements responsables du matériel (son, éclairage, décor, costumes...)."""

    name = models.CharField(max_length=255)
    contact_name = models.CharField(max_length=255, blank=True)
    contact_info = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

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
    EVENT_TYPE_CHOICES = [
        (EVENT_REHEARSAL, 'Répétition'),
        (EVENT_PERFORMANCE, 'Représentation'),
    ]

    title = models.CharField(max_length=255)
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name='shows')
    event_type = models.CharField(max_length=15, choices=EVENT_TYPE_CHOICES)
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    buffer_before_minutes = models.PositiveIntegerField(default=60)
    buffer_after_minutes = models.PositiveIntegerField(default=60)
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

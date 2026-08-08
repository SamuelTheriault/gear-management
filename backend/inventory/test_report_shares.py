"""Tests des liens publics de rapport (`ReportShare`, chantier 2026-08-08).

Trois familles, dans l'ordre de ce qui ferait le plus mal si ça cassait :

1. **Sécurité** — un lien public expose UNE feuille et rien d'autre, un
   membre d'un projet ne peut pas partager la production d'un autre, et un
   jeton révoqué ou expiré ne répond plus.
2. **Durabilité du QR imprimé** — la promesse « réimprimer ne périme pas les
   copies déjà distribuées » repose entièrement sur la réutilisation du
   jeton. Si ça régresse, des feuilles papier meurent en silence sur le
   terrain, et personne ne s'en aperçoit avant le quai de déchargement.
3. **Contenu** — le manifeste éclaté par arrêt, qui est la seule lecture
   utile au déchargement.

Suit les conventions de `test_project_access.py` (APIClient +
`force_authenticate`, helper `_make_member`).
"""

from datetime import timedelta

from django.contrib.auth.models import User as DjangoUser
from django.db.utils import IntegrityError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import (
    Material,
    MaterialCategory,
    Project,
    ProjectMembership,
    ReportShare,
    Show,
    Technician,
    Transport,
    TransportMaterial,
    TransportStop,
    Venue,
)
from .models import User as InventoryUser
from .report_shares import get_or_create_share, qr_svg, resolve_share


def _make_member(email, project=None, role=ProjectMembership.ROLE_EDITOR):
    django_user = DjangoUser.objects.create_user(username=email, email=email, password='pw')
    profile = InventoryUser.objects.create(email=email, name=email, django_user=django_user)
    if project is not None:
        ProjectMembership.objects.create(
            project=project, user=profile, role=role,
            status=ProjectMembership.STATUS_ACTIVE,
        )
    return django_user, profile


def _dt(hour, minute=0, day=14):
    return timezone.make_aware(timezone.datetime(2026, 9, day, hour, minute))


class _Fixture(TestCase):
    """Une production minimale mais réaliste : un entrepôt, deux salles, une
    tournée à trois arrêts dont du matériel qui monte et descend à des
    arrêts différents (le cas que le manifeste par arrêt doit démêler)."""

    def setUp(self):
        self.project = Project.objects.create(name="Vertiges")
        self.entrepot = Venue.objects.create(
            project=self.project, name="Entrepôt Saint-Roch", code="ESR", is_storage=True,
        )
        self.multi = Venue.objects.create(project=self.project, name="Salle Multi", code="SM")
        self.periscope = Venue.objects.create(project=self.project, name="Théâtre Périscope", code="TP")

        # `get_or_create` et non `create` : la création d'un `Project`
        # provisionne déjà un jeu de catégories par défaut (voir
        # signals.py), dont « Éclairage ».
        self.categorie, _ = MaterialCategory.objects.get_or_create(
            project=self.project, name="Éclairage",
        )
        self.console = Material.objects.create(
            project=self.project, name="Console ETC Ion", category=self.categorie, quantity=2,
        )
        self.micros = Material.objects.create(
            project=self.project, name="Malle de micros HF", category=self.categorie, quantity=1,
        )

        self.show = Show.objects.create(
            project=self.project, title="Vertiges", venue=self.multi,
            event_type=Show.EVENT_PERFORMANCE,
            start_datetime=_dt(20), end_datetime=_dt(22),
        )
        self.technicien = Technician.objects.create(
            project=self.project, name="Marianne Côté", specialty="Éclairage",
        )

        # Chaque projet reçoit un camion par défaut à sa création (signals.py) ;
        # `Transport.truck` est obligatoire depuis le chantier Camion.
        self.camion = self.project.trucks.first()
        self.transport = Transport.objects.create(
            project=self.project, show=self.show, truck=self.camion,
            scheduled_datetime=_dt(8),
        )
        self.a0 = TransportStop.objects.create(
            transport=self.transport, venue=self.entrepot, order=0,
            travel_minutes_from_previous=0,
        )
        self.a1 = TransportStop.objects.create(
            transport=self.transport, venue=self.periscope, order=1,
            travel_minutes_from_previous=35, travel_distance_meters=4200,
        )
        self.a2 = TransportStop.objects.create(
            transport=self.transport, venue=self.multi, order=2,
            travel_minutes_from_previous=25, travel_distance_meters=9800,
        )
        # La console fait tout le trajet ; les micros descendent au Périscope.
        TransportMaterial.objects.create(
            transport=self.transport, material=self.console, quantity=1,
            load_stop=self.a0, unload_stop=self.a2,
        )
        TransportMaterial.objects.create(
            transport=self.transport, material=self.micros, quantity=1,
            load_stop=self.a0, unload_stop=self.a1,
        )

        self.django_user, self.profile = _make_member('dt@example.com', self.project)
        self.client = APIClient()
        self.client.force_authenticate(user=self.django_user)


class TokenDurabilityTests(_Fixture):
    """La promesse la plus fragile du chantier : un QR imprimé reste valide."""

    def test_reemettre_renvoie_le_meme_jeton(self):
        premier, cree = get_or_create_share(
            project=self.project, kind=ReportShare.KIND_TRANSPORT, target=self.transport,
        )
        second, cree_encore = get_or_create_share(
            project=self.project, kind=ReportShare.KIND_TRANSPORT, target=self.transport,
        )
        self.assertTrue(cree)
        self.assertFalse(cree_encore)
        self.assertEqual(premier.token, second.token)
        self.assertEqual(ReportShare.objects.count(), 1)

    def test_post_deux_fois_renvoie_200_et_le_meme_jeton(self):
        """L'écran d'impression appelle l'endpoint sans savoir si le lien
        existe : le deuxième appel doit être un 200 idempotent, pas un 400
        de contrainte violée."""
        corps = {
            'project': self.project.id, 'kind': ReportShare.KIND_TRANSPORT,
            'transport': self.transport.id,
        }
        premier = self.client.post('/api/report-shares/', corps, format='json')
        second = self.client.post('/api/report-shares/', corps, format='json')
        self.assertEqual(premier.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(premier.data['token'], second.data['token'])

    def test_revoquer_puis_reemettre_donne_un_nouveau_jeton(self):
        ancien, _ = get_or_create_share(
            project=self.project, kind=ReportShare.KIND_TRANSPORT, target=self.transport,
        )
        ancien.revoked_at = timezone.now()
        ancien.save(update_fields=['revoked_at'])

        nouveau, cree = get_or_create_share(
            project=self.project, kind=ReportShare.KIND_TRANSPORT, target=self.transport,
        )
        self.assertTrue(cree)
        self.assertNotEqual(ancien.token, nouveau.token)
        # L'ancien reste en base, avec ses traces d'accès.
        self.assertEqual(ReportShare.objects.count(), 2)

    def test_un_seul_partage_actif_par_cible_en_base(self):
        get_or_create_share(
            project=self.project, kind=ReportShare.KIND_TRANSPORT, target=self.transport,
        )
        with self.assertRaises(IntegrityError):
            ReportShare.objects.create(
                project=self.project, kind=ReportShare.KIND_TRANSPORT, transport=self.transport,
            )

    def test_cible_incoherente_avec_le_type_refusee_en_base(self):
        with self.assertRaises(IntegrityError):
            ReportShare.objects.create(
                project=self.project, kind=ReportShare.KIND_TRANSPORT, show=self.show,
            )


class ResolutionTests(_Fixture):
    """`resolve_share` : les quatre façons dont un jeton peut ne plus répondre."""

    def test_jeton_inconnu(self):
        self.assertIsNone(resolve_share('jeton-qui-nexiste-pas'))

    def test_jeton_vide(self):
        self.assertIsNone(resolve_share(''))

    def test_jeton_revoque(self):
        share, _ = get_or_create_share(
            project=self.project, kind=ReportShare.KIND_TRANSPORT, target=self.transport,
        )
        share.revoked_at = timezone.now()
        share.save(update_fields=['revoked_at'])
        self.assertIsNone(resolve_share(share.token))

    def test_jeton_expire(self):
        share, _ = get_or_create_share(
            project=self.project, kind=ReportShare.KIND_TRANSPORT, target=self.transport,
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        self.assertIsNone(resolve_share(share.token))

    def test_expiration_future_reste_valide(self):
        share, _ = get_or_create_share(
            project=self.project, kind=ReportShare.KIND_TRANSPORT, target=self.transport,
            expires_at=timezone.now() + timedelta(days=30),
        )
        self.assertIsNotNone(resolve_share(share.token))


class PublicEndpointTests(_Fixture):
    """L'endpoint public lui-même : ce qu'il sert, ce qu'il refuse, ce qu'il
    ne laisse pas deviner."""

    def _url(self, share):
        return f'/api/public/reports/{share.token}/'

    def _share(self):
        share, _ = get_or_create_share(
            project=self.project, kind=ReportShare.KIND_TRANSPORT, target=self.transport,
        )
        return share

    def test_lisible_sans_aucune_authentification(self):
        share = self._share()
        anonyme = APIClient()  # explicitement PAS authentifié
        reponse = anonyme.get(self._url(share))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.data['report']['id'], self.transport.id)

    def test_entetes_de_protection(self):
        share = self._share()
        reponse = APIClient().get(self._url(share))
        self.assertIn('noindex', reponse['X-Robots-Tag'])
        self.assertIn('no-store', reponse['Cache-Control'])
        self.assertEqual(reponse['Referrer-Policy'], 'no-referrer')

    def test_404_identique_pour_inconnu_revoque_et_expire(self):
        """Aucune des trois situations ne doit être distinguable : sinon la
        vue confirme à un curieux qu'un jeton a existé."""
        revoque = self._share()
        revoque.revoked_at = timezone.now()
        revoque.save(update_fields=['revoked_at'])

        expire, _ = get_or_create_share(
            project=self.project, kind=ReportShare.KIND_SHOW, target=self.show,
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        reponses = [
            APIClient().get('/api/public/reports/inexistant/'),
            APIClient().get(self._url(revoque)),
            APIClient().get(self._url(expire)),
        ]
        for reponse in reponses:
            self.assertEqual(reponse.status_code, 404)
        self.assertEqual(len({r.data['detail'] for r in reponses}), 1)

    def test_ecriture_refusee(self):
        share = self._share()
        for methode in ('post', 'put', 'patch', 'delete'):
            reponse = getattr(APIClient(), methode)(self._url(share))
            self.assertEqual(reponse.status_code, 405, methode)

    def test_consultation_horodatee_et_comptee(self):
        share = self._share()
        APIClient().get(self._url(share))
        APIClient().get(self._url(share))
        share.refresh_from_db()
        self.assertEqual(share.access_count, 2)
        self.assertIsNotNone(share.last_accessed_at)

    def test_ne_fuit_que_la_cible(self):
        """Un lien de tournée ne doit rien dire des autres tournées ni du
        reste du projet."""
        autre = Transport.objects.create(
            project=self.project, show=self.show, truck=self.camion,
            scheduled_datetime=_dt(15),
        )
        TransportStop.objects.create(transport=autre, venue=self.entrepot, order=0)
        TransportStop.objects.create(
            transport=autre, venue=self.multi, order=1, travel_minutes_from_previous=20,
        )
        reponse = APIClient().get(self._url(self._share()))
        rapport = reponse.data['report']
        self.assertEqual(rapport['id'], self.transport.id)
        # Les arrêts servis sont exactement ceux de CETTE tournée.
        self.assertEqual(
            [a['venue']['name'] for a in rapport['stops']],
            ["Entrepôt Saint-Roch", "Théâtre Périscope", "Salle Multi"],
        )
        # Et la réponse ne contient aucune trace de l'autre tournée : ni son
        # heure de départ (15 h, absente de celle-ci), ni sa clé primaire à un
        # endroit qui identifierait une tournée.
        self.assertNotIn('15:00', str(rapport))
        self.assertNotEqual(rapport['id'], autre.id)


class ProjectIsolationTests(_Fixture):
    """Le trou le plus tentant : émettre un lien PUBLIC vers la production
    d'un autre client en postant simplement son id de cible."""

    def setUp(self):
        super().setUp()
        self.autre_projet = Project.objects.create(name="Production d'un autre client")
        self.autre_lieu = Venue.objects.create(project=self.autre_projet, name="Salle X")
        self.autre_show = Show.objects.create(
            project=self.autre_projet, title="Confidentiel", venue=self.autre_lieu,
            event_type=Show.EVENT_PERFORMANCE,
            start_datetime=_dt(20, day=15), end_datetime=_dt(22, day=15),
        )

    def test_impossible_de_partager_la_cible_d_un_autre_projet(self):
        reponse = self.client.post('/api/report-shares/', {
            'project': self.project.id,       # projet où j'ai le droit…
            'kind': ReportShare.KIND_SHOW,
            'show': self.autre_show.id,       # …cible qui appartient à un autre
        }, format='json')
        self.assertEqual(reponse.status_code, 400)
        self.assertIn('show', reponse.data)
        self.assertEqual(ReportShare.objects.count(), 0)

    def test_non_membre_ne_peut_pas_emettre(self):
        etranger, _ = _make_member('etranger@example.com')  # aucun membership
        client = APIClient()
        client.force_authenticate(user=etranger)
        reponse = client.post('/api/report-shares/', {
            'project': self.project.id, 'kind': ReportShare.KIND_TRANSPORT,
            'transport': self.transport.id,
        }, format='json')
        self.assertIn(reponse.status_code, (403, 404))
        self.assertEqual(ReportShare.objects.count(), 0)

    def test_la_liste_ne_montre_que_ses_projets(self):
        get_or_create_share(
            project=self.autre_projet, kind=ReportShare.KIND_SHOW, target=self.autre_show,
        )
        get_or_create_share(
            project=self.project, kind=ReportShare.KIND_TRANSPORT, target=self.transport,
        )
        reponse = self.client.get('/api/report-shares/')
        self.assertEqual(reponse.status_code, 200)
        projets = {ligne['project'] for ligne in reponse.data}
        self.assertEqual(projets, {self.project.id})

    def test_destroy_revoque_sans_supprimer(self):
        share, _ = get_or_create_share(
            project=self.project, kind=ReportShare.KIND_TRANSPORT, target=self.transport,
        )
        reponse = self.client.delete(f'/api/report-shares/{share.id}/')
        self.assertEqual(reponse.status_code, 200)
        share.refresh_from_db()
        self.assertIsNotNone(share.revoked_at)
        self.assertFalse(share.is_active)
        self.assertEqual(ReportShare.objects.count(), 1)


class CascadeTests(_Fixture):
    """Ce qu'il advient d'un lien quand sa cible disparaît."""

    def test_supprimer_la_tournee_supprime_le_partage(self):
        """Un QR déjà imprimé doit répondre 404, pas pointer vers un objet
        recréé plus tard avec le même identifiant."""
        share, _ = get_or_create_share(
            project=self.project, kind=ReportShare.KIND_TRANSPORT, target=self.transport,
        )
        jeton = share.token
        self.transport.delete()
        self.assertIsNone(resolve_share(jeton))
        self.assertEqual(APIClient().get(f'/api/public/reports/{jeton}/').status_code, 404)


class TransportPayloadTests(_Fixture):
    """Contenu de la feuille de tournée — le manifeste éclaté par arrêt et
    les heures dérivées, les deux endroits où une erreur se verrait sur le
    quai plutôt qu'à l'écran."""

    def test_manifeste_eclate_par_arret(self):
        contenu = APIClient().get(
            f'/api/public/reports/{self._make().token}/',
        ).data['report']
        arrets = contenu['stops']
        self.assertEqual(len(arrets), 3)

        # Arrêt 0 : tout monte, rien ne descend.
        self.assertEqual(len(arrets[0]['load']), 2)
        self.assertEqual(arrets[0]['unload'], [])
        # Arrêt 1 : les micros descendent, rien ne monte.
        self.assertEqual(arrets[1]['load'], [])
        self.assertEqual([l['material'] for l in arrets[1]['unload']], ["Malle de micros HF"])
        # Arrêt 2 : la console descend.
        self.assertEqual([l['material'] for l in arrets[2]['unload']], ["Console ETC Ion"])

    def test_heures_derivees_de_l_ancrage(self):
        contenu = APIClient().get(f'/api/public/reports/{self._make().token}/').data['report']
        heures = [a['arrival_at'] for a in contenu['stops']]
        self.assertEqual(heures[0], _dt(8))
        self.assertEqual(heures[1], _dt(8, 35))
        self.assertEqual(heures[2], _dt(9, 0))

    def test_distance_marquee_partielle_si_un_segment_manque(self):
        self.a2.travel_distance_meters = None
        self.a2.save(update_fields=['travel_distance_meters'])
        contenu = APIClient().get(f'/api/public/reports/{self._make().token}/').data['report']
        self.assertTrue(contenu['distance_is_partial'])
        self.assertEqual(contenu['distance_meters'], 4200)

    def test_destination_affichee_seulement_en_multi_arrets(self):
        contenu = APIClient().get(f'/api/public/reports/{self._make().token}/').data['report']
        self.assertTrue(all(l['to'] for l in contenu['stops'][0]['load']))

    def _make(self):
        share, _ = get_or_create_share(
            project=self.project, kind=ReportShare.KIND_TRANSPORT, target=self.transport,
        )
        return share


class QrTests(TestCase):
    """Le code QR lui-même. Deux propriétés qui ont réellement lâché pendant
    le portage des maquettes, d'où ces tests de non-régression."""

    def test_svg_dimensionne_en_mm_avec_viewbox(self):
        """Sans `viewBox`, WeasyPrint ignore la largeur CSS et sort un QR de
        ~9 mm, illisible. Vérifié dans le bac à sable le 2026-08-08 — ce test
        est là pour que la régression ne repasse pas en silence."""
        svg = qr_svg('https://exemple.test/p/abcdefghijklmnopqrstuv')
        self.assertIn('viewBox="0 0 ', svg)
        self.assertIn('width="25mm"', svg)
        self.assertIn('height="25mm"', svg)

    def test_aucun_appel_reseau_dans_le_svg(self):
        """Le QR doit être auto-porté : aucune référence externe, sinon la
        feuille dépend d'un service tiers au moment du rendu (et lui divulgue
        l'URL privée de partage)."""
        svg = qr_svg('https://exemple.test/p/abcdefghijklmnopqrstuv')
        for interdit in ('http://', 'https://', 'qrserver'):
            self.assertNotIn(interdit, svg)


class ShareTokenTests(TestCase):
    """Entropie et unicité du jeton — le seul secret qui protège la feuille."""

    def test_jetons_uniques_et_assez_longs(self):
        from .models import generate_share_token
        jetons = {generate_share_token() for _ in range(500)}
        self.assertEqual(len(jetons), 500)
        self.assertTrue(all(len(j) >= 22 for j in jetons))


class AutresRapportsTests(_Fixture):
    """Les trois autres types de feuille. Moins critiques que le transport
    côté sécurité (même socle de partage), mais leur assemblage de données a
    ses propres pièges — surtout la journée, qui mélange deux modèles sur une
    fenêtre temporelle."""

    def _partage(self, kind, target):
        share, _ = get_or_create_share(project=self.project, kind=kind, target=target)
        return APIClient().get(f'/api/public/reports/{share.token}/')

    def test_fiche_spectacle(self):
        reponse = self._partage(ReportShare.KIND_SHOW, self.show)
        self.assertEqual(reponse.status_code, 200)
        rapport = reponse.data['report']
        self.assertEqual(rapport['title'], "Vertiges")
        self.assertEqual(rapport['venue']['name'], "Salle Multi")
        # La tournée qui dessert ce spectacle doit y figurer : c'est ce que la
        # salle veut savoir (« qu'est-ce qui arrive, et quand »).
        self.assertEqual([t['id'] for t in rapport['transports']], [self.transport.id])

    def test_parcours_technicien_inclut_tournees_et_spectacles(self):
        from .models import ShowTechnician, TransportTechnician
        ShowTechnician.objects.create(show=self.show, technician=self.technicien)
        TransportTechnician.objects.create(transport=self.transport, technician=self.technicien)

        rapport = self._partage(ReportShare.KIND_TECHNICIAN, self.technicien).data['report']
        types = [e['type'] for e in rapport['engagements']]
        self.assertIn('show', types)
        self.assertIn('transport', types)
        # Trié chronologiquement : la tournée (8 h) avant le spectacle (20 h).
        self.assertEqual(rapport['engagements'][0]['type'], 'transport')

    def test_parcours_technicien_ignore_une_tournee_sans_heure(self):
        """Une proposition auto non complétée n'a pas de fenêtre exploitable
        — ignorée partout ailleurs (timelines, conflits), donc ici aussi."""
        from .models import TransportTechnician
        sans_heure = Transport.objects.create(
            project=self.project, show=self.show, truck=self.camion,
            scheduled_datetime=None, status=Transport.STATUS_TO_APPROVE,
        )
        TransportStop.objects.create(transport=sans_heure, venue=self.entrepot, order=0)
        TransportStop.objects.create(
            transport=sans_heure, venue=self.multi, order=1, travel_minutes_from_previous=20,
        )
        TransportTechnician.objects.create(transport=sans_heure, technician=self.technicien)

        rapport = self._partage(ReportShare.KIND_TECHNICIAN, self.technicien).data['report']
        self.assertEqual(rapport['engagements'], [])

    def test_horaire_de_la_journee_groupe_par_lieu(self):
        share, _ = get_or_create_share(
            project=self.project, kind=ReportShare.KIND_DAY, target=_dt(8).date(),
        )
        reponse = APIClient().get(f'/api/public/reports/{share.token}/')
        self.assertEqual(reponse.status_code, 200)
        rapport = reponse.data['report']
        lieux = {lane['venue']['name'] for lane in rapport['lanes'] if lane['venue']}
        # Le spectacle est à la Salle Multi, la tournée part de l'entrepôt.
        self.assertIn("Salle Multi", lieux)
        self.assertIn("Entrepôt Saint-Roch", lieux)
        self.assertEqual(rapport['item_count'], 2)

    def test_horaire_d_une_journee_vide(self):
        share, _ = get_or_create_share(
            project=self.project, kind=ReportShare.KIND_DAY, target=_dt(8, day=28).date(),
        )
        rapport = APIClient().get(f'/api/public/reports/{share.token}/').data['report']
        self.assertEqual(rapport['lanes'], [])
        self.assertEqual(rapport['item_count'], 0)


class SerializerApercuTests(_Fixture):
    """Ce que l'API renvoie au panneau de partage de l'app."""

    def test_le_partage_expose_url_et_qr_prets_a_afficher(self):
        """Le panneau ne doit rien avoir à recomposer : il reçoit l'URL
        publique et le QR déjà rendu, le MÊME que celui du PDF."""
        reponse = self.client.post('/api/report-shares/', {
            'project': self.project.id, 'kind': ReportShare.KIND_TRANSPORT,
            'transport': self.transport.id,
        }, format='json')
        self.assertEqual(reponse.status_code, 201)
        self.assertIn(reponse.data['token'], reponse.data['url'])
        self.assertIn('<svg', reponse.data['qr'])
        self.assertIn('width="25mm"', reponse.data['qr'])
        self.assertEqual(reponse.data['target_label'], str(self.transport))

    def test_le_jeton_n_est_pas_modifiable_par_l_api(self):
        """`token` est en lecture seule : personne ne choisit son secret."""
        share, _ = get_or_create_share(
            project=self.project, kind=ReportShare.KIND_TRANSPORT, target=self.transport,
        )
        ancien = share.token
        reponse = self.client.patch(
            f'/api/report-shares/{share.id}/', {'token': 'jeton-choisi-a-la-main'},
            format='json',
        )
        self.assertEqual(reponse.status_code, 200)
        share.refresh_from_db()
        self.assertEqual(share.token, ancien)

"""Tests du rendu PDF des sorties de rapport (WeasyPrint) — 2026-08-08.

Un PDF ne « casse » pas bruyamment : il sort, mais avec un QR de 9 mm, une
légende à l'envers ou une page vide. Ces tests visent donc les propriétés
mesurables qui ont effectivement lâché pendant le portage des maquettes.

Réutilise la fixture de `test_report_shares` (production complète avec une
tournée à trois arrêts).

`DUMP_PDF=1 python manage.py test inventory.test_report_pdf` écrit les quatre
PDF dans /tmp pour les regarder — c'est ce qui a servi à valider la mise en
page contre les maquettes.
"""

import os
import unittest

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .models import ReportShare, ShowTechnician, TransportTechnician
from .report_pdf import render_pdf
from .report_shares import get_or_create_share
from .test_report_shares import _Fixture, _dt

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    # Outil de mesure, pas de production : voir requirements-dev.txt. Sur une
    # installation sans dépendances de dev (ou en CI minimale), on saute ce
    # module plutôt que de faire échouer toute la suite.
    PdfReader = None

try:
    import weasyprint  # noqa: F401
    WEASYPRINT_DISPO = True
except (ImportError, OSError):  # pragma: no cover
    # `OSError` autant qu'`ImportError` : le paquet Python peut être installé
    # alors que les bibliothèques natives (Pango, HarfBuzz) manquent — cas
    # normal d'un poste macOS sans `brew install pango libffi`, ou d'une image
    # Linux sans les paquets apt du Dockerfile. Le reste de la suite doit
    # rester exécutable dans ces conditions : on saute la vérification du PDF
    # plutôt que de faire échouer 8 tests pour une dépendance système absente.
    WEASYPRINT_DISPO = False


# `PUBLIC_BASE_URL` explicite : hors cycle requête/réponse,
# `build_share_url` REFUSE de deviner une origine plutôt que d'imprimer un QR
# vers « http://testserver ». Ces tests appellent `render_pdf` directement, ils
# doivent donc fournir l'origine — exactement comme le fera une tâche
# planifiée en production.
@unittest.skipIf(PdfReader is None, "pypdf absent (requirements-dev.txt)")
@unittest.skipUnless(WEASYPRINT_DISPO, "WeasyPrint indisponible — voir les paquets système")
@override_settings(PUBLIC_BASE_URL='https://regi.example.app')
class RenduPdfTests(_Fixture):
    def setUp(self):
        super().setUp()
        ShowTechnician.objects.create(show=self.show, technician=self.technicien)
        TransportTechnician.objects.create(transport=self.transport, technician=self.technicien)

    def _pdf(self, kind, target):
        share, _ = get_or_create_share(project=self.project, kind=kind, target=target)
        octets, nom = render_pdf(share)
        if os.environ.get('DUMP_PDF'):
            with open(f'/tmp/{kind}.pdf', 'wb') as f:
                f.write(octets)
        return octets, nom, share

    def _lire(self, octets):
        import io
        return PdfReader(io.BytesIO(octets))

    def test_transport_sort_en_a4_portrait(self):
        octets, nom, _ = self._pdf(ReportShare.KIND_TRANSPORT, self.transport)
        page = self._lire(octets).pages[0].mediabox
        largeur_mm = round(float(page.width) / 72 * 25.4)
        hauteur_mm = round(float(page.height) / 72 * 25.4)
        self.assertEqual((largeur_mm, hauteur_mm), (210, 297))
        self.assertTrue(nom.endswith('.pdf'))

    def test_horaire_du_jour_sort_en_paysage(self):
        """Le seul des quatre en paysage — si la règle `@page` régresse, la
        grille à trois colonnes devient illisible sans que rien ne plante."""
        octets, _, _ = self._pdf(ReportShare.KIND_DAY, _dt(8).date())
        page = self._lire(octets).pages[0].mediabox
        self.assertGreater(float(page.width), float(page.height))

    def test_les_quatre_types_se_rendent(self):
        cas = [
            (ReportShare.KIND_TRANSPORT, self.transport),
            (ReportShare.KIND_SHOW, self.show),
            (ReportShare.KIND_TECHNICIAN, self.technicien),
            (ReportShare.KIND_DAY, _dt(8).date()),
        ]
        for kind, cible in cas:
            with self.subTest(kind=kind):
                octets, nom, _ = self._pdf(kind, cible)
                self.assertGreater(len(octets), 5000, "PDF suspicieusement petit")
                self.assertTrue(self._lire(octets).pages)

    def test_polices_embarquees_et_non_synthetisees(self):
        """Les quatre graisses de JetBrains Mono doivent être de VRAIES
        polices embarquées. Une graisse non déclarée est synthétisée par
        WeasyPrint en faux gras — visiblement plus baveux à l'impression."""
        octets, _, _ = self._pdf(ReportShare.KIND_TRANSPORT, self.transport)
        polices = set()
        for page in self._lire(octets).pages:
            # `get_object()` : pypdf renvoie des références indirectes, pas
            # les dictionnaires eux-mêmes.
            ressources = page['/Resources'].get_object()
            for valeur in ressources.get('/Font', {}).get_object().values():
                polices.add(str(valeur.get_object()['/BaseFont']))
        embarquees = [p for p in polices if '+' in p]  # préfixe de sous-ensemble
        self.assertTrue(embarquees, f"aucune police embarquée : {polices}")
        self.assertTrue(
            any('JetBrains' in p for p in embarquees),
            f"JetBrains Mono absente : {polices}",
        )

    def test_le_qr_est_lisible_a_25_mm(self):
        """Le test qui compte vraiment : on rastérise le PDF à 300 dpi (une
        laser courante) et on relit le code. Sans `viewBox`, le QR sortait à
        ~9 mm et ne se décodait pas — régression silencieuse à l'œil nu sur
        un aperçu écran."""
        try:
            import cv2
            import numpy as np
            import pypdfium2
        except ImportError:
            self.skipTest("cv2/pypdfium2 absents — vérification visuelle du QR ignorée")

        octets, _, share = self._pdf(ReportShare.KIND_TRANSPORT, self.transport)
        pdf = pypdfium2.PdfDocument(octets)
        image = pdf[0].render(scale=300 / 72).to_numpy()
        ok, decodes, _, _ = cv2.QRCodeDetector().detectAndDecodeMulti(
            cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR),
        )
        self.assertTrue(ok, "aucun QR détecté sur la page")
        self.assertTrue(
            any(share.token in d for d in decodes),
            f"le QR ne pointe pas vers le bon jeton : {decodes}",
        )

    def test_le_pied_est_repete_sur_toutes_les_pages(self):
        """Chaque page doit porter le QR : une feuille de tournée circule
        parfois désagrafée, et la page 2 seule doit rester scannable."""
        # On gonfle le manifeste pour forcer un débordement sur 2+ pages.
        from .models import Material, TransportMaterial
        for i in range(40):
            materiel = Material.objects.create(
                project=self.project, name=f"Projecteur d'essai {i:02d}",
                category=self.categorie, quantity=5,
            )
            TransportMaterial.objects.create(
                transport=self.transport, material=materiel, quantity=2,
                load_stop=self.a0, unload_stop=self.a2,
            )
        octets, _, _ = self._pdf(ReportShare.KIND_TRANSPORT, self.transport)
        lecteur = self._lire(octets)
        self.assertGreater(len(lecteur.pages), 1, "le manifeste gonflé tient encore sur une page ?")
        for numero, page in enumerate(lecteur.pages, start=1):
            with self.subTest(page=numero):
                self.assertIn('RégiStock', page.extract_text())

    def test_endpoint_pdf_public(self):
        share, _ = get_or_create_share(
            project=self.project, kind=ReportShare.KIND_TRANSPORT, target=self.transport,
        )
        reponse = APIClient().get(f'/api/public/reports/{share.token}/pdf/')
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse['Content-Type'], 'application/pdf')
        self.assertIn('inline', reponse['Content-Disposition'])
        self.assertIn('noindex', reponse['X-Robots-Tag'])

    def test_endpoint_pdf_404_sur_jeton_revoque(self):
        share, _ = get_or_create_share(
            project=self.project, kind=ReportShare.KIND_TRANSPORT, target=self.transport,
        )
        share.revoked_at = timezone.now()
        share.save(update_fields=['revoked_at'])
        self.assertEqual(
            APIClient().get(f'/api/public/reports/{share.token}/pdf/').status_code, 404,
        )

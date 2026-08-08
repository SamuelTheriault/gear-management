"""Routes API DRF — un router standard pour les ViewSets de `views.py`, plus
`SettingsView` (vue singleton, hors router — pas de liste/création)."""

from django.urls import path
from rest_framework.routers import DefaultRouter

from . import public_views, views

router = DefaultRouter()
router.register(r'users', views.UserViewSet)
router.register(r'projects', views.ProjectViewSet)
router.register(r'project-memberships', views.ProjectMembershipViewSet)
router.register(r'venues', views.VenueViewSet)
router.register(r'material-categories', views.MaterialCategoryViewSet)
router.register(r'materials', views.MaterialViewSet)
router.register(r'shows', views.ShowViewSet)
router.register(r'show-materials', views.ShowMaterialViewSet)
router.register(r'technicians', views.TechnicianViewSet)
router.register(r'show-technicians', views.ShowTechnicianViewSet)
router.register(r'trucks', views.TruckViewSet)
router.register(r'transports', views.TransportViewSet)
router.register(r'report-shares', views.ReportShareViewSet)

urlpatterns = router.urls + [
    path('settings/', views.SettingsView.as_view(), name='settings'),
    # --- Sorties de rapport, côté PUBLIC (hors router, hors session) ---
    # Seul endpoint de l'API joignable sans authentification : c'est ce que
    # consulte la page `/p/<token>` ouverte par le code QR imprimé. Voir
    # `public_views.py` pour les cinq règles qui s'y appliquent.
    path('public/reports/<str:token>/', public_views.public_report, name='public-report'),
    path('public/reports/<str:token>/pdf/', public_views.public_report_pdf, name='public-report-pdf'),
]

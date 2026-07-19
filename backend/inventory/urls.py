"""Routes API DRF — un router standard pour les ViewSets de `views.py`, plus
`SettingsView` (vue singleton, hors router — pas de liste/création)."""

from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r'users', views.UserViewSet)
router.register(r'projects', views.ProjectViewSet)
router.register(r'venues', views.VenueViewSet)
router.register(r'departments', views.DepartmentViewSet)
router.register(r'materials', views.MaterialViewSet)
router.register(r'shows', views.ShowViewSet)
router.register(r'show-materials', views.ShowMaterialViewSet)
router.register(r'technicians', views.TechnicianViewSet)
router.register(r'show-technicians', views.ShowTechnicianViewSet)
router.register(r'transports', views.TransportViewSet)

urlpatterns = router.urls + [
    path('settings/', views.SettingsView.as_view(), name='settings'),
]

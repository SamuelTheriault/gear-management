"""Routes API DRF — un router standard pour les 8 ViewSets de `views.py`."""

from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r'users', views.UserViewSet)
router.register(r'venues', views.VenueViewSet)
router.register(r'departments', views.DepartmentViewSet)
router.register(r'materials', views.MaterialViewSet)
router.register(r'shows', views.ShowViewSet)
router.register(r'show-materials', views.ShowMaterialViewSet)
router.register(r'technicians', views.TechnicianViewSet)
router.register(r'show-technicians', views.ShowTechnicianViewSet)

urlpatterns = router.urls

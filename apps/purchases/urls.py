from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PurchasesViewSet

# Create router and register viewsets
router = DefaultRouter()
router.register(r'purchases', PurchasesViewSet, basename='purchase')

# URL patterns
urlpatterns = [
    path('', include(router.urls)),
]

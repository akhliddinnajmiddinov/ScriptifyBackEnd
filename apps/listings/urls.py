from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ListingViewSet

# Create router and register viewsets
router = DefaultRouter()
router.register(r'listings', ListingViewSet, basename='listing')

# URL patterns
urlpatterns = [
    path('', include(router.urls)),
]
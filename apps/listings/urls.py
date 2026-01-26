from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ListingViewSet, ShelfViewSet, InventoryVendorViewSet, AsinViewSet

# Create router and register viewsets
router = DefaultRouter()
router.register(r'listings', ListingViewSet, basename='listing')
router.register(r'shelves', ShelfViewSet, basename='shelf')
router.register(r'inventory-vendors', InventoryVendorViewSet, basename='inventory-vendor')
router.register(r'asins', AsinViewSet, basename='asin')

# URL patterns
urlpatterns = [
    path('', include(router.urls)),
]
# urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TransactionViewSet, VendorViewSet

# Create router and register viewsets
router = DefaultRouter()
router.register(r'transactions', TransactionViewSet, basename='transaction')
router.register(r'vendors', VendorViewSet, basename='vendor')

# URL patterns
urlpatterns = [
    path('', include(router.urls)),
]

# Available endpoints:
# 
# TRANSACTION ENDPOINTS:
# Standard CRUD:
# GET    /transactions/                          - List all transactions (with filters & pagination)
# POST   /transactions/                          - Create a transaction
# GET    /transactions/{id}/                     - Retrieve a transaction
# PUT    /transactions/{id}/                     - Update a transaction (full)
# PATCH  /transactions/{id}/                     - Partial update a transaction
# DELETE /transactions/{id}/                     - Delete a transaction
#
# Custom actions:
# POST   /transactions/preview/                  - Preview transactions before bulk upload
# POST   /transactions/bulk_add/                 - Bulk add transactions
# DELETE /transactions/bulk_delete/              - Bulk delete transactions
# GET    /transactions/statistics/               - Get transaction statistics
# POST   /transactions/{id}/match_listing/       - Match listing for specific transaction

# VENDOR ENDPOINTS:
# Standard CRUD:
# GET    /vendors/                               - List all vendors (with filters & pagination)
# POST   /vendors/                               - Create a vendor
# GET    /vendors/{id}/                          - Retrieve a vendor
# PUT    /vendors/{id}/                          - Update vendor (updates all related transactions)
# PATCH  /vendors/{id}/                          - Partial update vendor (updates all related transactions)
# DELETE /vendors/{id}/                          - Delete vendor (only if no transactions)
#
# Custom actions:
# POST   /vendors/cleanup/                       - Delete all vendors with 0 transactions
# GET    /vendors/statistics/                    - Get vendor statistics
# GET    /vendors/{id}/transactions/             - Get all transactions for a vendor
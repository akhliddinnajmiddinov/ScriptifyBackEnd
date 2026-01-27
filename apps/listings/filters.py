from django_filters import rest_framework as filters
from .models import Listing, Shelf, InventoryVendor, Asin
from .serializers import ListingSerializer
from rest_framework.pagination import PageNumberPagination
import re
from django.db.models import Q


class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class ListingFilter(filters.FilterSet):
    """
    FilterSet for Listing model.
    """
    id = filters.NumberFilter(field_name='pk', lookup_expr='exact')
    min_price = filters.NumberFilter(field_name='price', lookup_expr='gte')
    max_price = filters.NumberFilter(field_name='price', lookup_expr='lte')
    start_date = filters.DateTimeFilter(field_name='timestamp', lookup_expr='gte')
    end_date = filters.DateTimeFilter(field_name='timestamp', lookup_expr='lte')
    listing_url = filters.CharFilter(field_name='listing_url', lookup_expr='icontains')
    tracking_number = filters.CharFilter(field_name='tracking_number', lookup_expr='icontains')
    
    class Meta:
        model = Listing
        fields = ['id', 'min_price', 'max_price', 'start_date', 'end_date', 'listing_url', 'tracking_number']


class ShelfFilter(filters.FilterSet):
    """
    FilterSet for Shelf model.
    """
    name = filters.CharFilter(field_name='name', lookup_expr='icontains')
    
    class Meta:
        model = Shelf
        fields = ['name']


class InventoryVendorFilter(filters.FilterSet):
    """
    FilterSet for InventoryVendor model.
    """
    name = filters.CharFilter(field_name='name', lookup_expr='icontains')
    
    class Meta:
        model = InventoryVendor
        fields = ['name']



class AsinFilter(filters.FilterSet):
    """
    FilterSet for Asin (inventory item) model.
    """
    # ASIN/SKU search
    id = filters.CharFilter(field_name='pk', lookup_expr='icontains')
    
    value = filters.CharFilter(field_name='value', lookup_expr='icontains')
    
    # Item name search
    name = filters.CharFilter(field_name='name', lookup_expr='icontains')
    
    # EAN search
    ean = filters.CharFilter(field_name='ean', lookup_expr='icontains')
    
    # Vendor search (now simple text field)
    vendor = filters.CharFilter(field_name='vendor', lookup_expr='icontains')
    
    # Shelf search (now simple text field)
    shelf = filters.CharFilter(field_name='shelf', lookup_expr='icontains')
    
    # Contains search (now simple text field)
    contains = filters.CharFilter(field_name='contains', lookup_expr='icontains')
    
    # Amount range filtering
    min_amount = filters.NumberFilter(field_name='amount', lookup_expr='gte')
    max_amount = filters.NumberFilter(field_name='amount', lookup_expr='lte')
    
    # Universal search
    search = filters.CharFilter(method='filter_search')
    
    class Meta:
        model = Asin
        fields = ['value', 'name', 'ean', 'vendor', 'shelf', 'contains', 'min_amount', 'max_amount', 'search']

    def _sanitize_and_tokenize(self, value: str) -> list[str]:
        if not value or not value.strip():
            return []
        sanitized = re.sub(r'[",*#]+', " ", value)
        return [t.strip() for t in sanitized.split() if t.strip()]
    
    def filter_search(self, queryset, name, value):
        """
        Optimized universal search with token-based searching.
        Each token is searched independently with AND logic.
        """
        tokens = self._sanitize_and_tokenize(value)
        
        # If no valid tokens (e.g. search cleared), return original queryset
        if not tokens:
            return queryset
        
        # Apply filters for each token with AND logic
        query = Q()
        for token in tokens:
            token_q = self._build_token_query(token)
            query &= token_q
        
        return queryset.filter(query).distinct()

    def _build_token_query(self, token):
        """
        Build Q object for a single token using icontains on all searchable fields.
        """
        return (
            Q(value__icontains=token) |
            Q(name__icontains=token) |
            Q(ean__icontains=token) |
            Q(vendor__icontains=token) |
            Q(shelf__icontains=token) |
            Q(contains__icontains=token)
        )

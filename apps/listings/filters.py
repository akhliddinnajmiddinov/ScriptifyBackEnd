from django_filters import rest_framework as filters
from .models import Listing, Shelf, InventoryVendor, Asin, InventoryColor, ListingAsin
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
    
    # EAN search (exact match)
    ean = filters.CharFilter(field_name='ean', lookup_expr='iexact')
    
    # Vendor search (now simple text field)
    vendor = filters.CharFilter(field_name='vendor', lookup_expr='icontains')
    
    # Shelf search (now simple text field)
    shelf = filters.CharFilter(field_name='shelf', lookup_expr='icontains')
    
    # Contains search (text field, kept for backwards compatibility)
    contains = filters.CharFilter(field_name='contains', lookup_expr='icontains')
    
    # Component search (searches component ASIN values via M2M)
    component = filters.CharFilter(method='filter_component')
    component_id = filters.CharFilter(method='filter_component_id')

    # Amount range filtering
    min_amount = filters.NumberFilter(field_name='amount', lookup_expr='gte')
    max_amount = filters.NumberFilter(field_name='amount', lookup_expr='lte')

    # Send direct filter
    send_direct = filters.ChoiceFilter(field_name='send_direct', choices=[(0, "Don't send"), (1, "Always send")])
    
    # Universal search
    search = filters.CharFilter(method='filter_search')
    # Strict phrase search used by purchase Add ASIN selector
    strict_search = filters.CharFilter(method='filter_strict_search')
    
    class Meta:
        model = Asin
        fields = ['value', 'name', 'ean', 'vendor', 'shelf', 'contains', 'component', 'min_amount', 'max_amount', 'send_direct', 'search', 'strict_search']

    def _sanitize_and_tokenize(self, value: str) -> list[str]:
        if not value or not value.strip():
            return []
        sanitized = re.sub(r'[",*#]+', " ", value)
        return [t.strip() for t in sanitized.split() if t.strip()]
    
    def filter_component(self, queryset, name, value):
        """
        Filter by component ASIN value (via M2M relationship).
        """
        if not value:
            return queryset
        return queryset.filter(component_set__component__value__icontains=value).distinct()
    
    def filter_component_id(self, queryset, name, value):
        """
        Filter by component ASIN ID (via M2M relationship).
        """
        if not value:
            return queryset
        return queryset.filter(component_set__component__pk=value).distinct()
    
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

    def filter_strict_search(self, queryset, name, value):
        """
        Strict phrase search (no tokenization) across Friendly name, EAN, and ASIN value.
        Example: "16 mag" -> SQL LIKE "%16 mag%" (case-insensitive).
        """
        if not value or not value.strip():
            return queryset

        phrase = re.sub(r"\s+", " ", value.strip())
        return queryset.filter(
            Q(value__icontains=phrase) |
            Q(name__icontains=phrase) |
            Q(ean__icontains=phrase)
        ).distinct()

    def _build_token_query(self, token):
        """
        Build Q object for a single token using icontains on all searchable fields.
        Includes both the legacy 'contains' text field and the new M2M component relationship.
        """
        return (
            Q(value__icontains=token) |
            Q(name__icontains=token) |
            Q(ean__icontains=token) |
            Q(vendor__icontains=token) |
            Q(shelf__icontains=token) |
            Q(contains__icontains=token) |
            Q(component_set__component__value__icontains=token)
        )


class InventoryColorFilter(filters.FilterSet):
    """
    FilterSet for InventoryColor model.
    """
    pattern = filters.CharFilter(field_name='pattern', lookup_expr='icontains')
    
    class Meta:
        model = InventoryColor
        fields = ['pattern']


class ListingAsinFilter(filters.FilterSet):
    """
    FilterSet for ListingAsin model.
    """
    listing = filters.NumberFilter(field_name='listing__id', lookup_expr='exact')
    asin = filters.NumberFilter(field_name='asin__id', lookup_expr='exact')
    purchase = filters.NumberFilter(field_name='purchase__id', lookup_expr='exact')

    # Universal ASIN search: same fields used in the inventory/ASIN page search
    # Searches across asin.value, asin.name, asin.ean, asin.vendor, asin.shelf, asin.contains
    asin_query = filters.CharFilter(method='filter_asin_query')

    # Universal purchase/conversation search: searches across purchase.external_id
    # and the listing's own tracking/url fields
    purchase_query = filters.CharFilter(method='filter_purchase_query')

    class Meta:
        model = ListingAsin
        fields = ['listing', 'asin', 'purchase', 'asin_query', 'purchase_query']

    def filter_asin_query(self, queryset, name, value):
        """
        Universal text search across the connected ASIN's fields.
        Mirrors the AsinFilter.filter_search logic.
        """
        if not value or not value.strip():
            return queryset
        # Tokenize on whitespace (same as AsinFilter)
        tokens = [t.strip() for t in value.split() if t.strip()]
        query = Q()
        for token in tokens:
            query &= (
                Q(asin__value__icontains=token) |
                Q(asin__name__icontains=token) |
                Q(asin__ean__icontains=token) |
                Q(asin__vendor__icontains=token) |
                Q(asin__shelf__icontains=token) |
                Q(asin__contains__icontains=token)
            )
        return queryset.filter(query).distinct()

    def filter_purchase_query(self, queryset, name, value):
        """
        Universal text search across the connected purchase's fields
        (external_id) and the listing's tracking/URL fields.
        """
        if not value or not value.strip():
            return queryset
        tokens = [t.strip() for t in value.split() if t.strip()]
        query = Q()
        for token in tokens:
            query &= (
                Q(purchase__product_title__icontains=token) |
                Q(purchase__primary_listing_url__icontains=token) |
                Q(purchase__tracking_code__icontains=token)
            )
        return queryset.filter(query).distinct()

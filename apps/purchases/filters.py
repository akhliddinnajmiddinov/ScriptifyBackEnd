from django_filters import rest_framework as filters
from django.db.models import Q
import re
from .models import Purchases


class PurchasesFilter(filters.FilterSet):
    """
    FilterSet for Purchases model.
    """
    platform = filters.CharFilter(field_name='platform', lookup_expr='exact')
    external_id = filters.CharFilter(field_name='external_id', lookup_expr='icontains')
    order_status = filters.CharFilter(field_name='order_status', lookup_expr='exact')
    approved_status = filters.CharFilter(field_name='approved_status', lookup_expr='exact')
    product_title = filters.CharFilter(field_name='product_title', lookup_expr='icontains')
    tracking_code = filters.CharFilter(field_name='tracking_code', lookup_expr='icontains')
    start_date = filters.DateTimeFilter(field_name='purchased_at', lookup_expr='gte')
    end_date = filters.DateTimeFilter(field_name='purchased_at', lookup_expr='lte')
    updated_start_date = filters.DateTimeFilter(field_name='updated_at', lookup_expr='gte')
    updated_end_date = filters.DateTimeFilter(field_name='updated_at', lookup_expr='lte')
    seller_name = filters.CharFilter(method='filter_seller_name')
    min_total_price = filters.NumberFilter(field_name='total_price', lookup_expr='gte')
    max_total_price = filters.NumberFilter(field_name='total_price', lookup_expr='lte')
    search = filters.CharFilter(method='filter_search')
    
    class Meta:
        model = Purchases
        fields = ['platform', 'external_id', 'order_status', 'approved_status', 'product_title', 'tracking_code', 'start_date', 'end_date', 'updated_start_date', 'updated_end_date', 'seller_name', 'min_total_price', 'max_total_price', 'search']
    
    def filter_seller_name(self, queryset, name, value):
        """
        Filter by seller name in seller_info JSONField.
        Searches in both seller_name and username fields within the JSON.
        """
        if not value:
            return queryset
        # Use PostgreSQL JSON field lookups (works with both JSONField and JSONB)
        return queryset.filter(
            Q(seller_info__seller_name__icontains=value) |
            Q(seller_info__username__icontains=value)
        )
    
    def _sanitize_and_tokenize(self, value: str) -> list[str]:
        """
        Sanitize and tokenize search input.
        Removes special characters and splits into tokens.
        """
        if not value or not value.strip():
            return []
        sanitized = re.sub(r'[",*#]+', " ", value)
        return [t.strip() for t in sanitized.split() if t.strip()]
    
    def filter_search(self, queryset, name, value):
        """
        Universal search across tracking_code, product_title, seller_name (in JSONField), and external_id.
        Uses token-based searching with AND logic (all tokens must match).
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
        Searches in: tracking_code, product_title, seller_name (JSONField), and external_id.
        """
        return (
            Q(tracking_code__icontains=token) |
            Q(product_title__icontains=token) |
            Q(external_id__icontains=token) |
            Q(seller_info__seller_name__icontains=token) |
            Q(seller_info__username__icontains=token)
        )

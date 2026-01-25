from django_filters import rest_framework as filters
from .models import Listing, Shelf, InventoryVendor, Asin
from .serializers import ListingSerializer
from rest_framework.pagination import PageNumberPagination


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
        fields = ['name', 'order']


class InventoryVendorFilter(filters.FilterSet):
    """
    FilterSet for InventoryVendor model.
    """
    name = filters.CharFilter(field_name='name', lookup_expr='icontains')
    
    class Meta:
        model = InventoryVendor
        fields = ['name', 'order']


class AsinFilter(filters.FilterSet):
    """
    FilterSet for Asin (inventory item) model.
    Supports filtering on all fields including M2M relationships.
    """
    value = filters.CharFilter(field_name='value', lookup_expr='icontains')
    name = filters.CharFilter(field_name='name', lookup_expr='icontains')
    ean = filters.CharFilter(field_name='ean', lookup_expr='icontains')
    
    # Vendor filtering
    vendor = filters.NumberFilter(field_name='vendor_id')
    vendor_name = filters.CharFilter(field_name='vendor__name', lookup_expr='icontains')
    
    # Amount range
    min_amount = filters.NumberFilter(field_name='amount', lookup_expr='gte')
    max_amount = filters.NumberFilter(field_name='amount', lookup_expr='lte')
    
    # Choice field
    multiple = filters.ChoiceFilter(choices=Asin.MULTIPLE_CHOICES)
    
    # Parent filtering
    parent = filters.NumberFilter(field_name='parent_id')
    parent_value = filters.CharFilter(field_name='parent__value', lookup_expr='icontains')
    has_parent = filters.BooleanFilter(field_name='parent', lookup_expr='isnull', exclude=True)
    
    # M2M shelf filtering - supports multiple shelf IDs
    shelf = filters.ModelMultipleChoiceFilter(
        queryset=Shelf.objects.all(),
        field_name='shelf',
        conjoined=False  # OR logic - matches if any shelf matches
    )
    shelf_name = filters.CharFilter(field_name='shelf__name', lookup_expr='icontains')
    
    class Meta:
        model = Asin
        fields = [
            'value', 'name', 'ean',
            'vendor', 'vendor_name',
            'min_amount', 'max_amount',
            'multiple',
            'parent', 'parent_value', 'has_parent',
            'shelf', 'shelf_name'
        ]
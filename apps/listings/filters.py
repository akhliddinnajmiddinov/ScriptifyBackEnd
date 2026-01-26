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
    
    class Meta:
        model = Asin
        fields = ['value', 'name', 'ean', 'vendor', 'shelf', 'contains', 'min_amount', 'max_amount']
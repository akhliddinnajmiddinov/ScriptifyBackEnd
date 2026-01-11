from django_filters import rest_framework as filters
from .models import Listing
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
# views.py
from django_filters import rest_framework as filters
from django.db.models import Q
from rest_framework.filters import OrderingFilter
from .models import Transaction, Vendor
from rest_framework.pagination import PageNumberPagination


class StableOrderingFilter(OrderingFilter):
    """
    Custom OrderingFilter that always adds -id as secondary sort for stability.
    Ensures consistent ordering when multiple records have the same primary sort value.
    """
    def filter_queryset(self, request, queryset, view):
        ordering = self.get_ordering(request, queryset, view)
        
        if ordering:
            # Convert to list if it's a tuple
            ordering_list = list(ordering) if ordering else []
            
            # Check if id or -id is already in the ordering
            has_id_ordering = any(field in ['id', '-id'] for field in ordering_list)
            
            # If no id ordering, add -id as secondary sort for stability
            if not has_id_ordering:
                ordering_list.append('-id')
            
            # Clear any existing ordering and apply new ordering
            return queryset.order_by(*ordering_list)
        
        # If no ordering specified, use default from view or model
        # But still ensure -id is included for stability
        default_ordering = getattr(view, 'ordering', None)
        if default_ordering:
            ordering_list = list(default_ordering) if isinstance(default_ordering, (list, tuple)) else [default_ordering]
            has_id_ordering = any(field in ['id', '-id'] for field in ordering_list)
            if not has_id_ordering:
                ordering_list.append('-id')
            return queryset.order_by(*ordering_list)
        
        return queryset

class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class VendorFilter(filters.FilterSet):
    """
    FilterSet for Vendor model.
    """
    vendor_name = filters.CharFilter(field_name='vendor_name', lookup_expr='icontains')
    vendor_vat = filters.CharFilter(field_name='vendor_vat', lookup_expr='icontains')
    has_image = filters.BooleanFilter(method='filter_has_image')
    
    class Meta:
        model = Vendor
        fields = ['vendor_name', 'vendor_vat', 'has_image']
    
    def filter_has_image(self, queryset, name, value):
        """Filter vendors that have or don't have an image."""
        if value:
            return queryset.exclude(Q(image='') | Q(image__isnull=True))
        else:
            return queryset.filter(Q(image='') | Q(image__isnull=True))


class TransactionFilter(filters.FilterSet):
    """
    FilterSet for Transaction model.
    """
    type = filters.ChoiceFilter(choices=Transaction.types)
    start_date = filters.DateTimeFilter(field_name='transaction_date', lookup_expr='gte')
    end_date = filters.DateTimeFilter(field_name='transaction_date', lookup_expr='lte')
    transaction_from = filters.CharFilter(field_name='transaction_from', lookup_expr='icontains')
    transaction_to = filters.CharFilter(field_name='transaction_to', lookup_expr='icontains')
    vendor = filters.CharFilter(method='filter_vendor')
    status = filters.ChoiceFilter(choices=Transaction.STATUS_CHOICES)
    currency = filters.CharFilter(field_name='currency', lookup_expr='icontains')
    min_amount = filters.NumberFilter(field_name='amount', lookup_expr='gte')
    max_amount = filters.NumberFilter(field_name='amount', lookup_expr='lte')
    transaction_id = filters.CharFilter(field_name='transaction_id', lookup_expr='icontains')
    
    class Meta:
        model = Transaction
        fields = ['type', 'start_date', 'end_date', 'transaction_from', 'transaction_to', 'vendor', 'status', 'currency', 'min_amount', 'max_amount', 'transaction_id']
    
    def filter_vendor(self, queryset, name, value):
        """
        Filter by vendor name in transaction_from or transaction_to.
        Note: For display purposes (vendor_img, vendor_vat), only transaction_to is used.
        """
        from django.db.models import Q
        return queryset.filter(
            Q(transaction_from__icontains=value) | Q(transaction_to__icontains=value)
        )
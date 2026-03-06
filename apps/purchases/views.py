from rest_framework import viewsets, status
from rest_framework.response import Response
from django.db.models import Prefetch
from django_filters import rest_framework as filters
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes
from .models import Purchases
from .serializers import PurchasesSerializer
from .filters import PurchasesFilter
from listings.filters import StandardPagination
from transactions.filters import StableOrderingFilter


class PurchasesViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Purchases model.
    Supports filtering by platform, order_status, approved_status, and other fields.
    """
    queryset = Purchases.objects.all().order_by('-updated_at', '-id')
    serializer_class = PurchasesSerializer
    filterset_class = PurchasesFilter
    filter_backends = [filters.DjangoFilterBackend, StableOrderingFilter]
    ordering_fields = [
        'id', 'platform', 'external_id', 'product_title', 'order_status',
        'approved_status', 'purchased_at', 'updated_at', 'approved_rejected_at', 'total_price', 'tracking_code',
        'seller_name', 'seller_name_sort'  # seller_name_sort is the annotated field for JSONField ordering
    ]
    ordering = ['-updated_at', '-id']
    pagination_class = StandardPagination
    
    def get_queryset(self):
        """
        Optimize queryset by prefetching listing relationship to prevent N+1 queries.
        Also annotate seller_name for ordering (from JSONField).
        """
        queryset = super().get_queryset()
        # Prefetch listing to avoid N+1 queries
        queryset = queryset.select_related('listing')
        
        # Annotate seller_name for ordering (from JSONField)
        # Use COALESCE to prefer seller_name, fallback to username
        from django.db.models import F, Value, CharField
        from django.db.models.functions import Coalesce
        
        queryset = queryset.annotate(
            seller_name_sort=Coalesce(
                F('seller_info__seller_name'),
                F('seller_info__username'),
                Value(''),
                output_field=CharField()
            )
        )
        
        return queryset
    
    def get_serializer_context(self):
        """
        Add prefetched vendors to serializer context to avoid N+1 queries.
        """
        context = super().get_serializer_context()
        
        # Prefetch all vendors that might be needed for the current queryset
        queryset = self.filter_queryset(self.get_queryset())
        platforms = queryset.values_list('platform', flat=True).distinct()
        
        if platforms:
            from transactions.models import Vendor
            from django.db.models import Q
            platform_filters = Q()
            for platform in platforms:
                platform_filters |= Q(vendor_name__iexact=platform)
            vendors = Vendor.objects.filter(platform_filters)
            # Store vendors in a dict keyed by uppercase platform name for quick lookup
            context['prefetched_vendors'] = {v.vendor_name.upper(): v for v in vendors}
        else:
            context['prefetched_vendors'] = {}
        
        return context
    
    @extend_schema(
        operation_id="purchases_list",
        description="List all purchases with filtering and pagination. "
                    "Supports filtering by platform, order_status, approved_status, product_title, tracking_code, seller_name, total_price range, and date ranges. "
                    "Universal search (query parameter) searches across tracking_code, product_title, seller_name, external_id, and platform.",
        tags=["Purchases"],
        parameters=[
            OpenApiParameter('id', OpenApiTypes.INT, description='Filter by ID (exact match)'),
            OpenApiParameter('platform', OpenApiTypes.STR, description='Filter by platform (vinted, amazon, kleinanzeigen, momox)'),
            OpenApiParameter('external_id', OpenApiTypes.STR, description='Search by external ID (partial match)'),
            OpenApiParameter('order_status', OpenApiTypes.STR, description='Filter by order status'),
            OpenApiParameter('approved_status', OpenApiTypes.STR, description='Filter by approved status (approved, rejected)'),
            OpenApiParameter('product_title', OpenApiTypes.STR, description='Search by product title (partial match)'),
            OpenApiParameter('tracking_code', OpenApiTypes.STR, description='Search by tracking code (partial match)'),
            OpenApiParameter('seller_name', OpenApiTypes.STR, description='Search by seller name (searches in seller_info JSONField)'),
            OpenApiParameter('min_total_price', OpenApiTypes.FLOAT, description='Minimum total price'),
            OpenApiParameter('max_total_price', OpenApiTypes.FLOAT, description='Maximum total price'),
            OpenApiParameter('query', OpenApiTypes.STR, description='Universal search across tracking_code, product_title, seller_name, external_id, and platform'),
            OpenApiParameter('start_date', OpenApiTypes.DATETIME, description='Filter purchases from this date (purchased_at >= start_date)'),
            OpenApiParameter('end_date', OpenApiTypes.DATETIME, description='Filter purchases until this date (purchased_at <= end_date)'),
            OpenApiParameter('updated_start_date', OpenApiTypes.DATETIME, description='Filter purchases updated from this date (updated_at >= updated_start_date)'),
            OpenApiParameter('updated_end_date', OpenApiTypes.DATETIME, description='Filter purchases updated until this date (updated_at <= updated_end_date)'),
            OpenApiParameter('page', OpenApiTypes.INT, description='Page number'),
            OpenApiParameter('page_size', OpenApiTypes.INT, description='Results per page (max 100)'),
            OpenApiParameter('ordering', OpenApiTypes.STR, description='Order results by field (e.g., -updated_at, approved_rejected_at, total_price, seller_name)'),
        ],
        responses=PurchasesSerializer(many=True),
    )
    def filter_queryset(self, queryset):
        """
        Override to map seller_name ordering to seller_name_sort (annotated field).
        """
        queryset = super().filter_queryset(queryset)
        
        # Check if ordering by seller_name and map to seller_name_sort
        ordering_param = self.request.query_params.get('ordering', '')
        if ordering_param and 'seller_name' in ordering_param:
            # Replace seller_name with seller_name_sort in the ordering
            ordering_list = ordering_param.split(',')
            new_ordering = []
            for field in ordering_list:
                field = field.strip()
                if field == 'seller_name':
                    new_ordering.append('seller_name_sort')
                elif field == '-seller_name':
                    new_ordering.append('-seller_name_sort')
                else:
                    new_ordering.append(field)
            
            # Apply the modified ordering
            queryset = queryset.order_by(*new_ordering)
        
        return queryset
    
    def list(self, request, *args, **kwargs):
        """List all purchases with filtering and pagination."""
        return super().list(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="purchases_retrieve",
        description="Get detailed information about a specific purchase.",
        tags=["Purchases"],
        responses=PurchasesSerializer,
    )
    def retrieve(self, request, *args, **kwargs):
        """Retrieve a single purchase by ID."""
        return super().retrieve(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="purchases_update",
        description="Update a purchase (full update).",
        tags=["Purchases"],
        request=PurchasesSerializer,
        responses=PurchasesSerializer,
    )
    def update(self, request, *args, **kwargs):
        """Update a purchase (full update)."""
        return super().update(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="purchases_partial_update",
        description="Partially update a purchase. Only provided fields will be updated.",
        tags=["Purchases"],
        request=PurchasesSerializer,
        responses=PurchasesSerializer,
    )
    def partial_update(self, request, *args, **kwargs):
        """Partially update a purchase."""
        return super().partial_update(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="purchases_delete",
        description="Delete a specific purchase by ID.",
        tags=["Purchases"],
        responses={204: None},
    )
    def destroy(self, request, *args, **kwargs):
        """Delete a purchase."""
        return super().destroy(request, *args, **kwargs)

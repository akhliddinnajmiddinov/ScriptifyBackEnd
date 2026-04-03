from rest_framework import viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db.models import Prefetch
from django_filters import rest_framework as filters
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes
from .models import Purchases
from .serializers import PurchasesSerializer
from .filters import PurchasesFilter
from listings.filters import StandardPagination
from transactions.filters import StableOrderingFilter
from transactions.models import Vendor


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
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        from apps.user.perm_utils import HasPerm
        if self.action in ('list', 'retrieve'):
            return [permissions.IsAuthenticated(), HasPerm('purchases.view_purchases')]
        if self.action == 'create':
            return [permissions.IsAuthenticated(), HasPerm('purchases.add_purchases')]
        if self.action in ('update', 'partial_update'):
            return [permissions.IsAuthenticated(), HasPerm('purchases.change_purchases')]
        if self.action == 'destroy':
            return [permissions.IsAuthenticated(), HasPerm('purchases.delete_purchases')]
        if self.action == 'bulk_upsert':
            return [permissions.IsAuthenticated(), HasPerm('purchases.can_import_purchases_from_file')]
        # preview: always allowed for authenticated users
        return [permissions.IsAuthenticated()]

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
        from django.db.models import Value, CharField
        from django.db.models.functions import Coalesce
        from django.db.models.fields.json import KeyTextTransform
        
        queryset = queryset.annotate(
            seller_name_sort=Coalesce(
                KeyTextTransform('seller_name', 'seller_info'),
                KeyTextTransform('username', 'seller_info'),
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
        if 'approved_status' in request.data:
            from apps.user.perm_utils import HasPerm
            perm = HasPerm('purchases.can_approve_purchase')
            if not perm.has_permission(request, self):
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied("You do not have permission to approve or reject purchases.")
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

    @action(
        detail=False,
        methods=['post'],
        permission_classes=[permissions.IsAuthenticated],
        url_path='preview',
        url_name='preview'
    )
    @extend_schema(
        operation_id="purchases_preview",
        description="Preview purchases for import without saving. Returns duplicate detection and vendor info.",
        tags=["Purchases"],
        request=PurchasesSerializer(many=True),
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'purchases': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'platform': {'type': 'string'},
                                'external_id': {'type': 'string'},
                                'data': {'type': 'object'},
                                'is_duplicate': {'type': 'boolean'},
                                'duplicate_id': {'type': ['integer', 'null']},
                                'vendor_image': {'type': ['string', 'null']},
                                'errors': {'type': 'array', 'items': {'type': 'string'}}
                            }
                        }
                    }
                }
            }
        }
    )
    def preview(self, request):
        """
        Preview purchases for import without saving.
        Checks for duplicates based on (platform, external_id) and retrieves vendor images.
        """
        data = request.data
        if not isinstance(data, list):
            return Response(
                {'error': 'Expected list of purchases'},
                status=status.HTTP_400_BAD_REQUEST
            )

        previews = []
        seen_pairs = {}  # (platform, external_id) -> 1-based row number

        for item in data:
            platform = item.get('platform')
            external_id = item.get('external_id')

            preview_item = {
                'platform': platform,
                'external_id': external_id,
                'data': item,
                'is_duplicate': False,
                'duplicate_id': None,
                'vendor_image': None,
                'errors': []
            }

            # Validate required fields
            if not platform:
                preview_item['errors'].append('platform is required')
            if not external_id:
                preview_item['errors'].append('external_id is required')

            if preview_item['errors']:
                previews.append(preview_item)
                continue

            # Check for intra-file duplicates
            pair_key = (platform, external_id)
            if pair_key in seen_pairs:
                preview_item['errors'].append(f'Duplicate in file — same as row {seen_pairs[pair_key]}')
                previews.append(preview_item)
                continue
            seen_pairs[pair_key] = len(previews) + 1  # 1-based row number

            # Check for duplicates in database
            existing = Purchases.objects.filter(
                platform=platform,
                external_id=external_id
            ).first()

            if existing:
                preview_item['is_duplicate'] = True
                preview_item['duplicate_id'] = existing.id

            # Get vendor image
            vendor = Vendor.objects.filter(
                vendor_name__iexact=platform
            ).first()

            if vendor and vendor.image:
                image_url = vendor.image.url if hasattr(vendor.image, 'url') else str(vendor.image)
                preview_item['vendor_image'] = request.build_absolute_uri(image_url)

            previews.append(preview_item)

        return Response(
            {'purchases': previews},
            status=status.HTTP_200_OK
        )

    @action(
        detail=False,
        methods=['post'],
        permission_classes=[permissions.IsAuthenticated],
        url_path='bulk_upsert',
        url_name='bulk_upsert'
    )
    @extend_schema(
        operation_id="purchases_bulk_upsert",
        description="Bulk create or update purchases. Uses (platform, external_id) as unique key. All-or-nothing operation.",
        tags=["Purchases"],
        request=PurchasesSerializer(many=True),
        responses={
            201: {
                'type': 'object',
                'properties': {
                    'created_count': {'type': 'integer'},
                    'updated_count': {'type': 'integer'},
                    'error_count': {'type': 'integer'},
                    'error': {'type': ['string', 'null']},
                    'errors': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'index': {'type': 'integer'},
                                'platform': {'type': 'string'},
                                'external_id': {'type': 'string'},
                                'errors': {'type': 'object'}
                            }
                        }
                    }
                }
            }
        }
    )
    def bulk_upsert(self, request):
        """
        Bulk create or update purchases using (platform, external_id) as unique key.
        All-or-nothing: if any row fails, nothing is committed.
        """
        from django.db import transaction

        data = request.data
        if not isinstance(data, list):
            return Response({'error': 'Expected list of purchases'}, status=status.HTTP_400_BAD_REQUEST)

        errors_list = []
        validated = []
        seen_pairs = {}  # (platform, external_id) -> first idx; detects intra-file duplicates

        # Build context once — get_serializer_context hits the DB for vendor prefetch
        # and calling it per-row would cause N redundant queries.
        serializer_context = self.get_serializer_context()

        for idx, item in enumerate(data):
            platform = item.get('platform')
            external_id = item.get('external_id')
            product_title = item.get('product_title')

            field_errors = {}
            if not platform:
                field_errors['platform'] = ['This field is required']
            if not external_id:
                field_errors['external_id'] = ['This field is required']
            if not product_title:
                field_errors['product_title'] = ['This field is required']

            if field_errors:
                errors_list.append({'index': idx, 'platform': platform, 'external_id': external_id, 'errors': field_errors})
                continue

            # Check for intra-file duplicates
            pair_key = (platform, external_id)
            if pair_key in seen_pairs:
                errors_list.append({
                    'index': idx,
                    'platform': platform,
                    'external_id': external_id,
                    'errors': {'external_id': [f'Duplicate in file — same as row {seen_pairs[pair_key] + 1}']}
                })
                continue
            seen_pairs[pair_key] = idx

            existing = Purchases.objects.filter(platform=platform, external_id=external_id).first()
            serializer = PurchasesSerializer(
                instance=existing,
                data=item,
                context=serializer_context,
            ) if existing else PurchasesSerializer(
                data=item,
                context=serializer_context,
            )
            if not serializer.is_valid():
                errors_list.append({'index': idx, 'platform': platform, 'external_id': external_id, 'errors': serializer.errors})
                continue

            # Store the serializer itself so save() (→ create/update) is called
            # in the atomic block, not a raw update_or_create that bypasses update().
            validated.append((idx, platform, external_id, existing, serializer))

        if errors_list:
            return Response(
                {'error': f'{len(errors_list)} row(s) failed validation', 'error_count': len(errors_list), 'created_count': 0, 'updated_count': 0, 'errors': errors_list},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            created_count = 0
            updated_count = 0
            with transaction.atomic():
                for idx, platform, external_id, existing, serializer in validated:
                    serializer.save()
                    if existing:
                        updated_count += 1
                    else:
                        created_count += 1

            return Response(
                {'created_count': created_count, 'updated_count': updated_count, 'error_count': 0, 'error': None, 'errors': []},
                status=status.HTTP_201_CREATED
            )
        except Exception as e:
            return Response(
                {'error': str(e), 'error_count': 1, 'created_count': 0, 'updated_count': 0, 'errors': []},
                status=status.HTTP_400_BAD_REQUEST
            )

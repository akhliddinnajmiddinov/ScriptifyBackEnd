# views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction as db_transaction
from django.db.models import Sum, Count, Avg, Q, Prefetch
from django_filters import rest_framework as filters
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes, OpenApiResponse
from drf_spectacular.types import OpenApiTypes
from .models import Listing, Shelf, InventoryVendor, Asin, ListingAsin, BuildComponent, BuildLog, BuildLogItem
from .serializers import (
    ListingSerializer, ShelfSerializer, InventoryVendorSerializer, 
    AsinSerializer, AsinPreviewItemSerializer, AsinBulkAddItemSerializer,
    BuildLogSerializer, BuildOrderDiscoverySerializer)
from .filters import StandardPagination, ListingFilter, ShelfFilter, InventoryVendorFilter, AsinFilter
from apps.transactions.filters import StableOrderingFilter
from apps.transactions.models import Transaction
from apps.transactions.serializers import TransactionSerializer


class ListingViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Listing CRUD and bulk operations.
    """
    queryset = Listing.objects.all().order_by('-timestamp')
    serializer_class = ListingSerializer
    filterset_class = ListingFilter
    filter_backends = [filters.DjangoFilterBackend, StableOrderingFilter]
    ordering_fields = ['id', 'listing_url', 'price', 'timestamp', 'tracking_number']
    ordering = ['-timestamp', '-id']
    pagination_class = StandardPagination
    
    def get_queryset(self):
        """
        Optimize queryset by prefetching listings_asins to prevent N+1 queries.
        """
        queryset = super().get_queryset()
        # Prefetch listings_asins to avoid N+1 queries when counting ASINs
        from .models import ListingAsin
        queryset = queryset.prefetch_related(
            Prefetch('listings_asins', queryset=ListingAsin.objects.select_related('asin'))
        )
        return queryset
    
    @extend_schema(
        operation_id="listings_list",
        description="List all listings with filtering and pagination. "
                    "Supports filtering by price range, date range, listing URL, and tracking number.",
        tags=["Listings"],
        parameters=[
            OpenApiParameter('min_price', OpenApiTypes.FLOAT, description='Minimum listing price'),
            OpenApiParameter('max_price', OpenApiTypes.FLOAT, description='Maximum listing price'),
            OpenApiParameter('start_date', OpenApiTypes.DATETIME, description='Filter listings from this date'),
            OpenApiParameter('end_date', OpenApiTypes.DATETIME, description='Filter listings until this date'),
            OpenApiParameter('listing_url', OpenApiTypes.STR, description='Search by listing URL (partial match)'),
            OpenApiParameter('tracking_number', OpenApiTypes.STR, description='Search by tracking number (partial match)'),
            OpenApiParameter('page', OpenApiTypes.INT, description='Page number'),
            OpenApiParameter('page_size', OpenApiTypes.INT, description='Results per page (max 100)'),
            OpenApiParameter('ordering', OpenApiTypes.STR, description='Order results by field (e.g., price, -timestamp)'),
        ],
        responses=ListingSerializer(many=True),
    )
    def list(self, request, *args, **kwargs):
        """List all listings with filtering and pagination."""
        return super().list(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="listings_retrieve",
        description="Get detailed information about a specific listing.",
        tags=["Listings"],
        responses=ListingSerializer,
    )
    def retrieve(self, request, *args, **kwargs):
        """Retrieve a single listing by ID."""
        return super().retrieve(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="listings_create",
        description="Create a new listing with listing URL, picture URLs, price, timestamp, and optional tracking number.",
        tags=["Listings"],
        request=ListingSerializer,
        responses=ListingSerializer,
    )
    def create(self, request, *args, **kwargs):
        """Create a single listing."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
            headers=headers
        )
    
    @extend_schema(
        operation_id="listings_update",
        description="Update a listing (full update).",
        tags=["Listings"],
        request=ListingSerializer,
        responses=ListingSerializer,
    )
    def update(self, request, *args, **kwargs):
        """Update a listing (full update)."""
        return super().update(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="listings_partial_update",
        description="Partially update a listing. Only provided fields will be updated.",
        tags=["Listings"],
        request=ListingSerializer,
        responses=ListingSerializer,
    )
    def partial_update(self, request, *args, **kwargs):
        """Partially update a listing."""
        return super().partial_update(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="listings_delete",
        description="Delete a specific listing by ID.",
        tags=["Listings"],
        responses={204: None},
    )
    def destroy(self, request, *args, **kwargs):
        """Delete a single listing."""
        return super().destroy(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="listings_bulk_add",
        description="Bulk add multiple listings in a single request. "
                    "All listings must be valid - if any listing is invalid, nothing is saved. "
                    "Returns all validation errors if any listing fails validation.",
        tags=["Listings"],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'listings': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'listing_url': {'type': 'string'},
                                'picture_urls': {
                                    'type': 'array',
                                    'items': {'type': 'string'},
                                    'description': 'JSON array of image URLs: ["url1", "url2", ...]'
                                },
                                'price': {'type': 'number'},
                                'timestamp': {'type': 'string', 'format': 'date-time'},
                                'tracking_number': {'type': 'string'},
                            },
                            'required': ['listing_url', 'price', 'timestamp']
                        }
                    }
                },
                'required': ['listings']
            }
        },
        responses={
            201: {
                'type': 'object',
                'properties': {
                    'created_count': {'type': 'integer'},
                    'created_listings': {'type': 'array'}
                }
            },
            400: {
                'type': 'object',
                'properties': {
                    'error': {'type': 'string'},
                    'error_count': {'type': 'integer'},
                    'errors': {'type': 'array'}
                }
            },
        },
    )
    @action(detail=False, methods=['post'])
    def bulk_add(self, request):
        """
        Bulk add multiple listings.
        All listings must be valid - if any listing is invalid, nothing is saved.
        """
        listings_data = request.data.get('listings', [])
        
        if not listings_data:
            return Response(
                {'error': 'No listings provided'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # First pass: Validate all listings without saving
        serializers = []
        errors = []
        
        for idx, listing_data in enumerate(listings_data):
            serializer = self.get_serializer(data=listing_data)
            if serializer.is_valid():
                serializers.append((idx, serializer))
            else:
                errors.append({
                    'index': idx,
                    'data': listing_data,
                    'errors': serializer.errors
                })
        
        # If any errors, return all errors without saving anything
        if errors:
            return Response(
                {
                    'error': 'Validation failed for one or more listings. No listings were saved.',
                    'error_count': len(errors),
                    'errors': errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # All valid - save all listings in a single database transaction
        created_listings = []
        with db_transaction.atomic():
            for idx, serializer in serializers:
                serializer.save()
                created_listings.append(serializer.data)
        
        return Response(
            {
                'created_count': len(created_listings),
                'created_listings': created_listings
            },
            status=status.HTTP_201_CREATED
        )
    
    @extend_schema(
        operation_id="listings_bulk_delete",
        description="Bulk delete multiple listings by their IDs in a single request.",
        tags=["Listings"],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'ids': {
                        'type': 'array',
                        'items': {'type': 'integer'},
                        'description': 'List of listing IDs to delete'
                    }
                },
                'required': ['ids']
            }
        },
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'deleted_count': {'type': 'integer'},
                    'message': {'type': 'string'}
                }
            },
        },
    )
    @action(detail=False, methods=['delete'])
    def bulk_delete(self, request):
        """
        Bulk delete listings by IDs.
        """
        ids = request.data.get('ids', [])
        
        if not ids:
            return Response(
                {'error': 'No listing IDs provided'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        deleted_count, _ = Listing.objects.filter(id__in=ids).delete()
        
        return Response({
            'deleted_count': deleted_count,
            'message': f'Successfully deleted {deleted_count} listing(s)'
        }, status=status.HTTP_200_OK)
    
    @extend_schema(
        operation_id="listings_statistics",
        description="Get aggregated statistics for listings. "
                    "Respects current filters - statistics will be calculated only for filtered listings. "
                    "Returns total count, average price, and min/max prices.",
        tags=["Listings"],
        parameters=[
            OpenApiParameter('min_price', OpenApiTypes.FLOAT, description='Include listings from this price'),
            OpenApiParameter('max_price', OpenApiTypes.FLOAT, description='Include listings up to this price'),
            OpenApiParameter('start_date', OpenApiTypes.DATETIME, description='Include listings from this date'),
            OpenApiParameter('end_date', OpenApiTypes.DATETIME, description='Include listings until this date'),
            OpenApiParameter('listing_url', OpenApiTypes.STR, description='Filter by listing URL'),
            OpenApiParameter('tracking_number', OpenApiTypes.STR, description='Filter by tracking number'),
        ],
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'total_listings': {'type': 'integer'},
                    'average_price': {'type': 'number'},
                    'min_price': {'type': 'number'},
                    'max_price': {'type': 'number'}
                }
            }
        },
    )
    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """
        Get listing statistics.
        Respects the current filters applied.
        Optimized to combine all aggregates into a single query.
        """
        from django.db.models import Min, Max
        
        # Get filtered queryset
        queryset = self.filter_queryset(self.get_queryset())
        
        # Combine all aggregates into a single query
        stats_data = queryset.aggregate(
            total_listings=Count('id'),
            average_price=Avg('price'),
            min_price=Min('price'),
            max_price=Max('price')
        )
        
        stats = {
            'total_listings': stats_data['total_listings'],
            'average_price': stats_data['average_price'],
            'min_price': stats_data['min_price'],
            'max_price': stats_data['max_price']
        }
        
        return Response(stats, status=status.HTTP_200_OK)
    
    @extend_schema(
        operation_id="listings_matched_transactions",
        description="Get all transactions that match this listing based on price and timestamp proximity.",
        tags=["Listings"],
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'listing': {'type': 'object'},
                    'matched_transactions': {'type': 'array'},
                    'match_count': {'type': 'integer'}
                }
            },
        },
    )
    @action(detail=True, methods=['get'])
    def matched_transactions(self, request, pk=None):
        """
        Get all transactions that could match this listing.
        """
        from datetime import timedelta
        import math
        
        listing = self.get_object()
        
        # Thresholds
        amount_threshold = 5
        time_threshold_seconds = 10
        
        # Find potential matching transactions
        time_range = timedelta(seconds=time_threshold_seconds)
        potential_transactions = Transaction.objects.filter(
            transaction_date__gte=listing.timestamp - time_range,
            transaction_date__lte=listing.timestamp + time_range,
            amount__gte=listing.price - amount_threshold,
            amount__lte=listing.price + amount_threshold
        )
        
        # Calculate distances and sort
        transaction_distances = []
        for transaction in potential_transactions:
            time_diff = abs((listing.timestamp - transaction.transaction_date).total_seconds())
            amount_diff = abs(listing.price - transaction.amount)
            
            time_weight = 0.1
            amount_weight = 1.0
            
            distance = math.sqrt(
                (time_weight * time_diff) ** 2 + 
                (amount_weight * amount_diff) ** 2
            )
            
            transaction_distances.append({
                'transaction': TransactionSerializer(transaction).data,
                'distance': distance
            })
        
        # Sort by distance
        transaction_distances.sort(key=lambda x: x['distance'])
        
        return Response({
            'listing': self.get_serializer(listing).data,
            'matched_transactions': [t['transaction'] for t in transaction_distances],
            'match_count': len(transaction_distances)
        }, status=status.HTTP_200_OK)


# ============== Inventory ViewSets ==============

class ShelfViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Shelf CRUD operations.
    """
    queryset = Shelf.objects.all()
    serializer_class = ShelfSerializer
    filterset_class = ShelfFilter
    filter_backends = [filters.DjangoFilterBackend, StableOrderingFilter]
    ordering_fields = ['id', 'name']
    ordering = ['id']
    pagination_class = StandardPagination
    
    @extend_schema(
        operation_id="shelves_list",
        description="List all shelves with filtering and pagination.",
        tags=["Inventory - Shelves"],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="shelves_retrieve",
        description="Get a shelf by ID.",
        tags=["Inventory - Shelves"],
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="shelves_create",
        description="Create a new shelf.",
        tags=["Inventory - Shelves"],
    )
    def create(self, request, *args, **kwargs):
        # Strip name whitespace
        if 'name' in request.data and isinstance(request.data['name'], str):
            request.data._mutable = True
            request.data['name'] = request.data['name'].strip()
            request.data._mutable = False
            
        return super().create(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="shelves_update",
        description="Update a shelf. If new name exists, merge items to existing shelf and delete this one.",
        tags=["Inventory - Shelves"],
    )
    def update(self, request, *args, **kwargs):
        return self._update_with_merge(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="shelves_partial_update",
        description="Partially update a shelf. If new name exists, merge items to existing shelf and delete this one.",
        tags=["Inventory - Shelves"],
    )
    def partial_update(self, request, *args, **kwargs):
        return self._update_with_merge(request, partial=True, *args, **kwargs)
    
    def _update_with_merge(self, request, partial=False, *args, **kwargs):
        """
        Handle update with merge logic.
        If new name already exists in another shelf, merge all connected items
        to that shelf and delete the current one.
        """
        instance = self.get_object()
        new_name = request.data.get('name', '').strip()
        
        # Check if name is being changed to an existing shelf
        if new_name and new_name.lower() != instance.name.lower():
            existing_shelf = Shelf.objects.filter(name__iexact=new_name).exclude(id=instance.id).first()
            
            if existing_shelf:
                # Merge: move all connected asins to existing shelf
                with db_transaction.atomic():
                    for asin in instance.asins.all():
                        # Add existing_shelf only if not already connected
                        if not asin.shelf.filter(id=existing_shelf.id).exists():
                            asin.shelf.add(existing_shelf)
                        # Remove old shelf
                        asin.shelf.remove(instance)
                    
                    # Delete the old shelf
                    instance.delete()
                
                # Return same format as native update
                return Response(ShelfSerializer(existing_shelf).data)
        
        # Normal update
        data = request.data.copy()
        if 'name' in request.data:
            data['name'] = new_name
            
        serializer = self.get_serializer(instance, data=data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    
    @extend_schema(
        operation_id="shelves_delete",
        description="Delete a shelf.",
        tags=["Inventory - Shelves"],
    )
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)


class InventoryVendorViewSet(viewsets.ModelViewSet):
    """
    ViewSet for InventoryVendor CRUD operations.
    """
    queryset = InventoryVendor.objects.all()
    serializer_class = InventoryVendorSerializer
    filterset_class = InventoryVendorFilter
    filter_backends = [filters.DjangoFilterBackend, StableOrderingFilter]
    ordering_fields = ['id', 'name']
    ordering = ['id']
    pagination_class = StandardPagination
    
    @extend_schema(
        operation_id="inventory_vendors_list",
        description="List all inventory vendors with filtering and pagination.",
        tags=["Inventory - Vendors"],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="inventory_vendors_retrieve",
        description="Get a vendor by ID.",
        tags=["Inventory - Vendors"],
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="inventory_vendors_create",
        description="Create a new vendor.",
        tags=["Inventory - Vendors"],
    )
    def create(self, request, *args, **kwargs):
        # Strip name whitespace
        if 'name' in request.data and isinstance(request.data['name'], str):
            request.data._mutable = True
            request.data['name'] = request.data['name'].strip()
            request.data._mutable = False
            
        return super().create(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="inventory_vendors_update",
        description="Update a vendor. If new name exists, merge items to existing vendor and delete this one.",
        tags=["Inventory - Vendors"],
    )
    def update(self, request, *args, **kwargs):
        return self._update_with_merge(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="inventory_vendors_partial_update",
        description="Partially update a vendor. If new name exists, merge items to existing vendor and delete this one.",
        tags=["Inventory - Vendors"],
    )
    def partial_update(self, request, *args, **kwargs):
        return self._update_with_merge(request, partial=True, *args, **kwargs)
    
    def _update_with_merge(self, request, partial=False, *args, **kwargs):
        """
        Handle update with merge logic.
        If new name already exists in another vendor, merge all connected items
        to that vendor and delete the current one.
        """
        instance = self.get_object()
        new_name = request.data.get('name', '').strip()
        
        # Check if name is being changed to an existing vendor
        if new_name and new_name.lower() != instance.name.lower():
            existing_vendor = InventoryVendor.objects.filter(name__iexact=new_name).exclude(id=instance.id).first()
            
            if existing_vendor:
                # Merge: move all connected asins to existing vendor
                with db_transaction.atomic():
                    Asin.objects.filter(vendor=instance).update(vendor=existing_vendor)
                    
                    # Delete the old vendor
                    instance.delete()
                
                # Return same format as native update
                return Response(InventoryVendorSerializer(existing_vendor).data)
        
        # Normal update
        data = request.data.copy()
        if 'name' in request.data:
            data['name'] = new_name
            
        serializer = self.get_serializer(instance, data=data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    
    @extend_schema(
        operation_id="inventory_vendors_delete",
        description="Delete a vendor.",
        tags=["Inventory - Vendors"],
    )
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)


class AsinViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Asin (inventory items) CRUD and bulk operations.
    """
    queryset = Asin.objects.all().order_by('-id')
    serializer_class = AsinSerializer
    filterset_class = AsinFilter
    filter_backends = [filters.DjangoFilterBackend, StableOrderingFilter]
    ordering_fields = ['id', 'value', 'name', 'ean', 'amount', 'vendor', 'shelf', 'contains']
    ordering = ['-id']
    pagination_class = StandardPagination
   
    def get_queryset(self):
        """
        Optimize queryset by prefetching asins_listings and components to prevent N+1 queries.
        """
        queryset = super().get_queryset()
        # Prefetch asins_listings to avoid N+1 queries when counting Listings
        # Prefetch component_set for BuildComponent M2M relationship
        queryset = queryset.prefetch_related(
            Prefetch('asins_listings', queryset=ListingAsin.objects.select_related('listing')),
            Prefetch('component_set', queryset=BuildComponent.objects.select_related('component'))
        )
        return queryset
    
    @extend_schema(
        operation_id="asins_list",
        description="List all inventory items with filtering and pagination. "
                    "Supports filtering by value, name, ean, vendor, shelf, contains, and amount range.",
        tags=["Inventory - Items"],
        parameters=[
            OpenApiParameter('value', OpenApiTypes.STR, description='Search by ASIN/SKU (partial match)'),
            OpenApiParameter('name', OpenApiTypes.STR, description='Search by item name (partial match)'),
            OpenApiParameter('ean', OpenApiTypes.STR, description='Search by EAN (partial match)'),
            OpenApiParameter('vendor', OpenApiTypes.STR, description='Search by vendor (partial match)'),
            OpenApiParameter('shelf', OpenApiTypes.STR, description='Search by shelf (partial match)'),
            OpenApiParameter('contains', OpenApiTypes.STR, description='Search by contains (partial match)'),
            OpenApiParameter('min_amount', OpenApiTypes.FLOAT, description='Minimum amount'),
            OpenApiParameter('max_amount', OpenApiTypes.FLOAT, description='Maximum amount'),
            OpenApiParameter('page', OpenApiTypes.INT, description='Page number'),
            OpenApiParameter('page_size', OpenApiTypes.INT, description='Results per page (max 100)'),
            OpenApiParameter('ordering', OpenApiTypes.STR, description='Order results by field (e.g., amount, -value)'),
        ],
        responses=AsinSerializer(many=True),
    )
    def list(self, request, *args, **kwargs):
        """List all inventory items with filtering and pagination."""
        return super().list(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="asins_retrieve",
        description="Get detailed information about a specific inventory item.",
        tags=["Inventory - Items"],
        responses=AsinSerializer,
    )
    def retrieve(self, request, *args, **kwargs):
        """Retrieve a single inventory item by ID."""
        return super().retrieve(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="asins_create",
        description="Create a new inventory item with value (ASIN/SKU), name, and optional fields.",
        tags=["Inventory - Items"],
        request=AsinSerializer,
        responses=AsinSerializer,
    )
    def create(self, request, *args, **kwargs):
        """Create a single inventory item."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
            headers=headers
        )
    
    @extend_schema(
        operation_id="asins_update",
        description="Update an inventory item (full update).",
        tags=["Inventory - Items"],
        request=AsinSerializer,
        responses=AsinSerializer,
    )
    def update(self, request, *args, **kwargs):
        """Update an inventory item (full update)."""
        return super().update(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="asins_partial_update",
        description="Partially update an inventory item. Only provided fields will be updated.",
        tags=["Inventory - Items"],
        request=AsinSerializer,
        responses=AsinSerializer,
    )
    def partial_update(self, request, *args, **kwargs):
        """Partially update an inventory item."""
        return super().partial_update(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="asins_delete",
        description="Delete a specific inventory item by ID.",
        tags=["Inventory - Items"],
        responses={204: None},
    )
    def destroy(self, request, *args, **kwargs):
        """Delete a single inventory item."""
        return super().destroy(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="asins_bulk_add",
        description="Bulk add multiple inventory items in a single request. "
                    "All items must be valid - if any item is invalid, nothing is saved. "
                    "Returns all validation errors if any item fails validation.",
        tags=["Inventory - Items"],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'items': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'value': {'type': 'string'},
                                'name': {'type': 'string'},
                                'ean': {'type': 'string'},
                                'vendor': {'type': 'string'},
                                'amount': {'type': 'number'},
                                'shelf': {'type': 'string'},
                                'contains': {'type': 'string'},
                            },
                            'required': ['value', 'name']
                        }
                    }
                },
                'required': ['items']
            }
        },
        responses={
            201: {
                'type': 'object',
                'properties': {
                    'created_count': {'type': 'integer'},
                    'created_items': {'type': 'array'}
                }
            },
            400: {
                'type': 'object',
                'properties': {
                    'error': {'type': 'string'},
                    'error_count': {'type': 'integer'},
                    'errors': {'type': 'array'}
                }
            },
        },
    )
    @action(detail=False, methods=['post'])
    def bulk_add(self, request):
        """
        Bulk add multiple inventory items.
        All items must be valid - if any item is invalid, nothing is saved.
        """
        items_data = request.data.get('items', [])
        
        if not items_data:
            return Response(
                {'error': 'No items provided'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # First pass: Validate all items without saving
        serializers = []
        errors = []
        
        for idx, item_data in enumerate(items_data):
            serializer = self.get_serializer(data=item_data)
            if serializer.is_valid():
                serializers.append((idx, serializer))
            else:
                errors.append({
                    'index': idx,
                    'data': item_data,
                    'errors': serializer.errors
                })
        
        # If any errors, return all errors without saving anything
        if errors:
            return Response(
                {
                    'error': 'Validation failed for one or more items. No items were saved.',
                    'error_count': len(errors),
                    'errors': errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # All valid - save all items in a single database transaction
        created_items = []
        with db_transaction.atomic():
            for idx, serializer in serializers:
                serializer.save()
                created_items.append(serializer.data)
        
        return Response(
            {
                'created_count': len(created_items),
                'created_items': created_items
            },
            status=status.HTTP_201_CREATED
        )

    @extend_schema(
        operation_id="asins_preview_listing_updates",
        description="Preview inventory updates from listings within a date range. "
                    "Excludes listings with URLs containing 'kleinanzeigen'. "
                    "Returns computed amount deltas and shelf changes.",
        tags=["Inventory - Items"],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'start': {'type': 'string', 'format': 'date-time', 'description': 'Start datetime (inclusive)'},
                    'end': {'type': 'string', 'format': 'date-time', 'description': 'End datetime (exclusive)'},
                },
                'required': ['start', 'end']
            }
        },
        responses={
            200: {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'asin_id': {'type': 'integer'},
                        'value': {'type': 'string'},
                        'name': {'type': 'string'},
                        'old_amount': {'type': 'integer'},
                        'delta_amount': {'type': 'integer'},
                        'new_amount': {'type': 'integer'},
                        'old_shelf': {'type': 'string', 'nullable': True},
                        'new_shelf': {'type': 'string', 'nullable': True},
                    }
                }
            },
            400: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
        },
    )
    @action(detail=False, methods=['post'])
    def preview_listing_updates(self, request):
        """
        Preview inventory updates from listings in a date range.
        Excludes listings with URLs containing 'kleinanzeigen'.
        """
        start_str = request.data.get('start')
        end_str = request.data.get('end')
        
        if not start_str or not end_str:
            return Response(
                {'error': 'Both start and end datetime are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            from django.utils.dateparse import parse_datetime
            from django.utils.timezone import is_aware, make_aware
            
            start = parse_datetime(start_str)
            end = parse_datetime(end_str)
            
            if not start:
                return Response({'error': f'Invalid start datetime format: {start_str}'}, status=status.HTTP_400_BAD_REQUEST)
            if not end:
                return Response({'error': f'Invalid end datetime format: {end_str}'}, status=status.HTTP_400_BAD_REQUEST)
                
            # Ensure they are aware if USE_TZ is True (Standard Django behavior with parse_datetime)
            if not is_aware(start):
                start = make_aware(start)
            if not is_aware(end):
                end = make_aware(end)
        except (ValueError, AttributeError) as e:
            return Response(
                {'error': f'Invalid datetime format: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if end <= start:
            return Response(
                {'error': 'End datetime must be after start datetime'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Query: aggregate amounts per ASIN from listings in range, excluding kleinanzeigen
        from django.db.models import Sum
        from django.db.models.functions import Coalesce
        
        # Get all ListingAsin entries where:
        # - listing.timestamp is in [start, end)
        # - listing.listing_url does NOT contain 'kleinanzeigen'
        listing_asins = ListingAsin.objects.filter(
            listing__timestamp__gte=start,
            listing__timestamp__lt=end,
        ).exclude(
            listing__listing_url__icontains='kleinanzeigen'
        ).values('asin_id').annotate(
            delta_amount=Sum('amount')
        )
        
        if not listing_asins:
            return Response([], status=status.HTTP_200_OK)
        
        # Get ASIN details for each aggregated result
        asin_ids = [item['asin_id'] for item in listing_asins]
        asins = {a.id: a for a in Asin.objects.filter(id__in=asin_ids)}
        
        # Build delta map
        delta_map = {item['asin_id']: item['delta_amount'] for item in listing_asins}
        
        def compute_shelf_update(old_shelf):
            """
            Shelf logic:
            - NULL/empty/whitespace => 'Box'
            - non-empty and does NOT contain 'Box' (case-insensitive) => append ', Box'
            - contains 'Box' => no change (return old_shelf)
            """
            if old_shelf is None:
                return 'Box'
            s = old_shelf.strip()
            if s == '':
                return 'Box'
            if 'box' in s.lower():
                return old_shelf  # Return the original shelf instead of None
            return f'{old_shelf}, Box'
        
        # Build preview results
        results = []
        for asin_id in asin_ids:
            asin = asins.get(asin_id)
            if not asin:
                continue
            
            delta = delta_map.get(asin_id, 0) or 0
            old_amount = asin.amount or 0
            new_amount = old_amount + delta
            
            old_shelf = asin.shelf
            new_shelf = compute_shelf_update(old_shelf)
            
            results.append({
                'asin_id': asin.id,
                'value': asin.value or '',
                'name': asin.name or '',
                'old_amount': old_amount,
                'delta_amount': delta,
                'new_amount': new_amount,
                'old_shelf': old_shelf,
                'new_shelf': new_shelf,
            })
        
        # Sort by asin_id for consistent ordering
        results.sort(key=lambda x: x['asin_id'])
        
        return Response(results, status=status.HTTP_200_OK)

    @extend_schema(
        operation_id="asins_apply_listing_updates",
        description="Apply inventory updates from the preview. "
                    "Updates amount and shelf for each ASIN in the list.",
        tags=["Inventory - Items"],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'updates': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'asin_id': {'type': 'integer'},
                                'new_amount': {'type': 'integer'},
                                'new_shelf': {'type': 'string', 'nullable': True},
                            },
                            'required': ['asin_id', 'new_amount']
                        }
                    }
                },
                'required': ['updates']
            }
        },
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'updated_count': {'type': 'integer'},
                }
            },
            400: {
                'type': 'object',
                'properties': {
                    'error': {'type': 'string'},
                    'error_count': {'type': 'integer'},
                    'errors': {'type': 'array'}
                }
            },
        },
    )
    @action(detail=False, methods=['post'])
    def apply_listing_updates(self, request):
        """
        Apply inventory updates from a preview.
        Updates amount and optionally shelf for each ASIN.
        All or nothing: if any update fails validation, no changes are committed.
        """
        updates = request.data.get('updates', [])
        
        if not updates:
            return Response(
                {'error': 'No updates provided'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        errors = []
        validated_updates = []
        
        # Phase 1: Validation
        # Check all updates before applying any changes to ensure atomicity.
        for idx, update in enumerate(updates):
            asin_id = update.get('asin_id')
            new_amount = update.get('new_amount')
            new_shelf = update.get('new_shelf')
            
            field_errors = {}
            if asin_id is None:
                field_errors['asin_id'] = ['This field is required.']
            if new_amount is None:
                field_errors['new_amount'] = ['This field is required.']
            
            if field_errors:
                errors.append({
                    'index': idx,
                    'asin_id': asin_id,
                    'errors': field_errors
                })
                continue
                
            try:
                asin = Asin.objects.get(id=asin_id)
                validated_updates.append((asin, new_amount, new_shelf))
            except Asin.DoesNotExist:
                errors.append({
                    'index': idx,
                    'asin_id': asin_id,
                    'errors': {'asin_id': [f'ASIN with id {asin_id} not found.']}
                })

        if errors:
            return Response(
                {
                    'error': 'Validation failed for one or more items. No updates were applied.',
                    'error_count': len(errors),
                    'errors': errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )
            
        # Phase 2: Application
        # Everything validated, now apply in a single transaction.
        updated_count = 0
        try:
            with db_transaction.atomic():
                for asin, new_amount, new_shelf in validated_updates:
                    # Update amount
                    asin.amount = new_amount
                    
                    # Update shelf only if new_shelf is provided (not None)
                    if new_shelf is not None:
                        asin.shelf = new_shelf
                    
                    asin.save()
                    updated_count += 1
        except Exception as e:
            return Response(
                {'error': f'Database error during apply: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        return Response(
            {'updated_count': updated_count},
            status=status.HTTP_200_OK
        )


class BuildLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for Build History (Read Only).
    Provides a revert action to break down a build.
    """
    queryset = BuildLog.objects.all().prefetch_related(
        Prefetch('items', queryset=BuildLogItem.objects.select_related('component'))
    ).select_related('parent_item')
    serializer_class = BuildLogSerializer
    pagination_class = StandardPagination
    filter_backends = [StableOrderingFilter]
    ordering = ['-timestamp']

    @extend_schema(
        operation_id="build_log_revert",
        description="Revert a build action (break down items). Increases component stock and marks log as reverted.",
        tags=["Inventory - Build Orders"],
        responses={200: BuildLogSerializer},
    )
    @action(detail=True, methods=['post'])
    def revert(self, request, pk=None):
        build_log = self.get_object()
        
        if build_log.is_reverted:
            return Response(
                {"error": "This build has already been reverted."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        with db_transaction.atomic():
            # Restore component quantities
            for log_item in build_log.items.all():
                component = log_item.component
                component.amount += log_item.quantity_consumed
                component.save()
            
            # Mark as reverted
            build_log.is_reverted = True
            build_log.save()
            
        return Response(BuildLogSerializer(build_log).data)


class BuildOrderViewSet(viewsets.ViewSet):
    """
    ViewSet for discovering buildable items and executing builds.
    """
    
    @extend_schema(
        operation_id="build_orders_status",
        description="List all items with components, grouped into ready and missing based on stock availability.",
        tags=["Inventory - Build Orders"],
        responses={
            200: OpenApiResponse(
                description="Lists of ready and missing build orders",
                response=OpenApiTypes.OBJECT,
            )
        },
    )
    @action(detail=False, methods=['get'])
    def status(self, request):
        # Find all Asins that have components
        items_with_components = Asin.objects.order_by('-id').annotate(
            comp_count=Count('component_set')
        ).filter(comp_count__gt=0).prefetch_related(
            Prefetch('component_set', queryset=BuildComponent.objects.select_related('component'))
        )
        
        ready = []
        missing = []
        
        for item in items_with_components:
            # Calculate max buildable quantity
            max_buildable = float('inf')
            has_missing = False
            
            components = item.component_set.all()
            for bc in components:
                if bc.quantity > 0:
                    possible = bc.component.amount // bc.quantity
                    if possible < max_buildable:
                        max_buildable = possible
                    if bc.component.amount < bc.quantity:
                        has_missing = True
                else:
                    # Quantity 0? Should not happen but handle it
                    pass
            
            if max_buildable == float('inf'):
                max_buildable = 0
            
            item.max_buildable = int(max_buildable)
            data = BuildOrderDiscoverySerializer(item).data
            
            if has_missing or max_buildable == 0:
                missing.append(data)
            else:
                ready.append(data)
                
        return Response({
            'ready': ready,
            'missing': missing
        })

    @extend_schema(
        operation_id="build_orders_execute",
        description="Execute a build action for a parent item.",
        tags=["Inventory - Build Orders"],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'parent_id': {'type': 'integer'},
                    'quantity': {'type': 'integer', 'minimum': 1},
                },
                'required': ['parent_id', 'quantity']
            }
        },
        responses={201: BuildLogSerializer},
    )
    @action(detail=False, methods=['post'])
    def build(self, request):
        parent_id = request.data.get('parent_id')
        quantity = int(request.data.get('quantity', 0))
        
        if not parent_id or quantity <= 0:
            return Response({"error": "parent_id and positive quantity are required"}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            parent_item = Asin.objects.prefetch_related('component_set__component').get(id=parent_id)
        except Asin.DoesNotExist:
            return Response({"error": "Parent item not found"}, status=status.HTTP_404_NOT_FOUND)
            
        components = parent_item.component_set.all()
        if not components:
            return Response({"error": "This item has no components defined"}, status=status.HTTP_400_BAD_REQUEST)
            
        # Validate stock
        for bc in components:
            required = bc.quantity * quantity
            if bc.component.amount < required:
                return Response({
                    "error": f"Insufficient stock for component {bc.component.value}. Needed: {required}, Available: {bc.component.amount}"
                }, status=status.HTTP_400_BAD_REQUEST)
        
        with db_transaction.atomic():
            # Create Log
            build_log = BuildLog.objects.create(
                parent_item=parent_item,
                quantity=quantity
            )
            
            # Consume stock and create log items
            for bc in components:
                required = bc.quantity * quantity
                component = bc.component
                component.amount -= required
                component.save()
                
                BuildLogItem.objects.create(
                    build_log=build_log,
                    component=component,
                    quantity_consumed=required
                )
                
        return Response(BuildLogSerializer(build_log).data, status=status.HTTP_201_CREATED)
    
    @extend_schema(
        operation_id="asins_bulk_delete",
        description="Bulk delete multiple inventory items by their IDs in a single request.",
        tags=["Inventory - Items"],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'ids': {
                        'type': 'array',
                        'items': {'type': 'integer'},
                        'description': 'List of item IDs to delete'
                    }
                },
                'required': ['ids']
            }
        },
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'deleted_count': {'type': 'integer'},
                    'message': {'type': 'string'}
                }
            },
        },
    )
    @action(detail=False, methods=['delete'])
    def bulk_delete(self, request):
        """
        Bulk delete inventory items by IDs.
        """
        ids = request.data.get('ids', [])
        
        if not ids:
            return Response(
                {'error': 'No item IDs provided'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        deleted_count, _ = Asin.objects.filter(id__in=ids).delete()
        
        return Response({
            'deleted_count': deleted_count,
            'message': f'Successfully deleted {deleted_count} item(s)'
        }, status=status.HTTP_200_OK)
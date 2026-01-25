# views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction as db_transaction
from django.db.models import Sum, Count, Avg, Q, Prefetch
from django_filters import rest_framework as filters
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes, OpenApiResponse
from drf_spectacular.types import OpenApiTypes
from .models import Listing, Shelf, InventoryVendor, Asin, ListingAsin
from .serializers import (
    ListingSerializer, ShelfSerializer, InventoryVendorSerializer, 
    AsinSerializer, AsinPreviewItemSerializer, AsinBulkAddItemSerializer
)
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
    ordering_fields = ['id', 'name', 'order']
    ordering = ['order', 'id']
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
    ordering_fields = ['id', 'name', 'order']
    ordering = ['order', 'id']
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
    ViewSet for Asin (inventory items) CRUD operations.
    Includes preview and bulk_add actions.
    """
    queryset = Asin.objects.all()
    serializer_class = AsinSerializer
    filterset_class = AsinFilter
    filter_backends = [filters.DjangoFilterBackend, StableOrderingFilter]
    ordering_fields = ['id', 'value', 'name', 'ean', 'amount', 'multiple']
    ordering = ['-id']
    pagination_class = StandardPagination
    
    def get_queryset(self):
        """Optimize queryset with select_related and prefetch_related."""
        queryset = super().get_queryset()
        queryset = queryset.select_related('vendor', 'parent').prefetch_related(
            'shelf',
            'children',
            Prefetch('asins_listings', queryset=ListingAsin.objects.select_related('listing'))
        )
        return queryset
    
    @extend_schema(
        operation_id="asins_list",
        description="List all inventory items with filtering and pagination. "
                    "Supports filtering by value, name, ean, vendor, amount range, multiple, parent, and shelf.",
        tags=["Inventory - Items"],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="asins_retrieve",
        description="Get an inventory item by ID. Includes connected listings.",
        tags=["Inventory - Items"],
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="asins_update",
        description="Update an inventory item.",
        tags=["Inventory - Items"],
    )
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="asins_partial_update",
        description="Partially update an inventory item.",
        tags=["Inventory - Items"],
    )
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="asins_delete",
        description="Delete an inventory item.",
        tags=["Inventory - Items"],
    )
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="asins_preview",
        description="Preview inventory items before bulk add. "
                    "Validates vendor, shelfs, and contains (parent ASIN) existence.",
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
                                'shelfs': {'type': 'array', 'items': {'type': 'object'}},
                                'multiple': {'type': 'string', 'enum': ['YES', 'NO']},
                                'contains': {'type': 'array', 'items': {'type': 'object'}}
                            }
                        }
                    }
                }
            }
        },
    )
    @action(detail=False, methods=['post'])
    def preview(self, request):
        """
        Preview inventory items with lookup results.
        Validates vendor, shelfs, and contains existence.
        """
        items_data = request.data.get('items', [])
        
        if not items_data:
            return Response(
                {'error': 'No items provided'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        preview_results = []
        for item_data in items_data:
            serializer = AsinPreviewItemSerializer(data=item_data)
            if serializer.is_valid():
                preview_results.append(serializer.data)
            else:
                preview_results.append({
                    'error': 'Validation failed',
                    'data': item_data,
                    'errors': serializer.errors
                })
        
        return Response({
            'preview': preview_results,
            'total_count': len(preview_results)
        }, status=status.HTTP_200_OK)
    
    @extend_schema(
        operation_id="asins_bulk_add",
        description="Bulk add inventory items. Validates vendor, shelfs, and contains existence. "
                    "If any validation fails, all items are rolled back.",
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
                                'shelfs': {'type': 'array'},
                                'multiple': {'type': 'string'},
                                'contains': {'type': 'array'}
                            }
                        }
                    }
                }
            }
        },
    )
    @action(detail=False, methods=['post'])
    def bulk_add(self, request):
        """
        Bulk add inventory items with atomic transaction.
        Validates all references (vendor, shelfs, contains) before creating.
        """
        items_data = request.data.get('items', [])
        
        if not items_data:
            return Response(
                {'error': 'No items provided'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        errors = []
        validated_items = []
        
        # First pass: Validate all items
        for idx, item_data in enumerate(items_data):
            serializer = AsinBulkAddItemSerializer(data=item_data)
            
            # 1. Standard Serializer Validation
            if not serializer.is_valid():
                errors.append({
                    'index': idx,
                    'data': item_data,
                    'errors': serializer.errors
                })
                continue
            
            data = serializer.validated_data
            custom_errors = {}
            
            # 2. Custom Validation (Vendor, Shelfs, Parent)
            
            # Validate vendor exists
            vendor = None
            vendor_name = data.get('vendor')
            if vendor_name:
                vendor = InventoryVendor.objects.filter(name__iexact=vendor_name).first()
                if not vendor:
                    custom_errors['vendor'] = [f"Vendor '{vendor_name}' not found"]
            
            # Validate shelfs exist
            shelfs = []
            if data.get('shelfs'):
                missing_shelfs = []
                for shelf_item in data.get('shelfs', []):
                    shelf_name = shelf_item.get('name', '')
                    shelf = Shelf.objects.filter(name__iexact=shelf_name).first()
                    if shelf:
                        shelfs.append(shelf)
                    else:
                        missing_shelfs.append(shelf_name)
                
                if missing_shelfs:
                    custom_errors['shelfs'] = [f"Shelves not found: {', '.join(missing_shelfs)}"]
            
            # Validate contains (child ASINs) exist
            children = []
            if data.get('contains'):
                missing_children = []
                for child_item in data.get('contains', []):
                    child_value = child_item.get('value', '')
                    child = Asin.objects.filter(value__iexact=child_value).first()
                    if child:
                        children.append(child)
                    else:
                        missing_children.append(child_value)
                
                if missing_children:
                    custom_errors['contains'] = [f"Child ASINs not found: {', '.join(missing_children)}"]
            
            # If custom validation failed, append error matching Transaction format
            if custom_errors:
                errors.append({
                    'index': idx,
                    'data': item_data,
                    'errors': custom_errors
                })
            else:
                validated_items.append({
                    'data': data,
                    'vendor': vendor,
                    'shelfs': shelfs,
                    'children': children
                })
        
        # If any errors, return all errors without saving anything
        if errors:
            return Response(
                {
                    'error': 'Validation failed for one or more items. No items were created.',
                    'error_count': len(errors),
                    'errors': errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # All valid - create items atomically
        created_items = []
        try:
            with db_transaction.atomic():
                for item in validated_items:
                    data = item['data']
                    asin = Asin.objects.create(
                        value=data['value'],
                        name=data['name'],
                        ean=data.get('ean') or '',
                        vendor=item['vendor'],
                        amount=data.get('amount', 0),
                        multiple=data.get('multiple', 'NO'),
                        parent=None  # Parent is set on children (they point to this item), not here
                    )
                    
                    # Set M2M shelfs
                    if item['shelfs']:
                        asin.shelf.set(item['shelfs'])
                    
                    # Set parent for children
                    if item['children']:
                        for child in item['children']:
                            child.parent = asin
                            child.save()
                    
                    created_items.append(AsinSerializer(asin).data)
        except Exception as e:
            return Response(
                {'error': f'Failed to create items: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        return Response(
            {
                'created_count': len(created_items),
                'created_items': created_items
            },
            status=status.HTTP_201_CREATED
        )
    
    @extend_schema(
        operation_id="asins_bulk_delete",
        description="Bulk delete inventory items by IDs.",
        tags=["Inventory - Items"],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'ids': {
                        'type': 'array',
                        'items': {'type': 'integer'}
                    }
                }
            }
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
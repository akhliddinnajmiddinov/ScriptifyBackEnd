# views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction as db_transaction
from django.db.models import Sum, Count, Avg, Q
from django_filters import rest_framework as filters
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes, OpenApiResponse
from drf_spectacular.types import OpenApiTypes
from .models import Listing
from .serializers import ListingSerializer
from .filters import StandardPagination, ListingFilter
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
        """
        from django.db.models import Min, Max
        
        # Get filtered queryset
        queryset = self.filter_queryset(self.get_queryset())
        
        stats = {
            'total_listings': queryset.count(),
            'average_price': queryset.aggregate(avg=Avg('price'))['avg'],
            'min_price': queryset.aggregate(min=Min('price'))['min'],
            'max_price': queryset.aggregate(max=Max('price'))['max']
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
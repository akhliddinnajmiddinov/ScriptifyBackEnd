# views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction as db_transaction
from django.db.models import Sum, Count, Avg, Q, Case, When, IntegerField, OuterRef, Exists
from django.db import models
from django_filters import rest_framework as filters
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes, OpenApiResponse
from drf_spectacular.types import OpenApiTypes
from .models import Transaction, Vendor
from apps.listings.models import Listing
from .serializers import TransactionSerializer, VendorSerializer
from .filters import StandardPagination, TransactionFilter, VendorFilter, StableOrderingFilter

class VendorViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Vendor CRUD operations with automatic cleanup.
    """
    queryset = Vendor.objects.all().order_by('vendor_name')
    serializer_class = VendorSerializer
    filterset_class = VendorFilter
    filter_backends = [filters.DjangoFilterBackend, StableOrderingFilter]
    ordering_fields = ['id', 'vendor_name', 'vendor_vat']
    ordering = ['vendor_name', '-id']
    pagination_class = StandardPagination
    
    @extend_schema(
        operation_id="vendors_list",
        description="List all vendors with filtering and pagination.",
        tags=["Vendors"],
        parameters=[
            OpenApiParameter('vendor_name', OpenApiTypes.STR, description='Filter by vendor name (partial match)'),
            OpenApiParameter('vendor_vat', OpenApiTypes.STR, description='Filter by vendor VAT (partial match)'),
            OpenApiParameter('has_image', OpenApiTypes.BOOL, description='Filter vendors with/without image'),
            OpenApiParameter('page', OpenApiTypes.INT, description='Page number'),
            OpenApiParameter('page_size', OpenApiTypes.INT, description='Results per page (max 100)'),
        ],
        responses=VendorSerializer(many=True),
    )
    def list(self, request, *args, **kwargs):
        """List all vendors with filtering and pagination."""
        return super().list(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="vendors_retrieve",
        description="Get detailed information about a specific vendor.",
        tags=["Vendors"],
        responses=VendorSerializer,
    )
    def retrieve(self, request, *args, **kwargs):
        """Retrieve a single vendor by ID."""
        return super().retrieve(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="vendors_create",
        description="Create a new vendor.",
        tags=["Vendors"],
        request=VendorSerializer,
        responses=VendorSerializer,
    )
    def create(self, request, *args, **kwargs):
        """Create a single vendor."""
        return super().create(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="vendors_update",
        description="Update a vendor. If vendor_name is changed, all transactions with "
                    "the old vendor name (in transaction_from or transaction_to) will be updated. "
                    "If the old vendor name has 0 matching transactions after update, it will be deleted.",
        tags=["Vendors"],
        request=VendorSerializer,
        responses=VendorSerializer,
    )
    def update(self, request, *args, **kwargs):
        """
        Update a vendor (full update).
        Updates all related transactions if vendor_name changes.
        If new vendor name already exists, merges into existing vendor and deletes old one.
        Deletes old vendor if it has no more transactions.
        """
        vendor = self.get_object()
        old_vendor_name = vendor.vendor_name
        
        # Check if vendor_name is being changed and if it already exists (BEFORE validation)
        new_vendor_name = request.data.get('vendor_name')
        
        if new_vendor_name and new_vendor_name != old_vendor_name:
            # Check if a vendor with the new name already exists (case-insensitive)
            existing_vendor = Vendor.objects.filter(
                vendor_name__iexact=new_vendor_name
            ).exclude(id=vendor.id).first()
            
            if existing_vendor:
                # Vendor with new name already exists - handle merge BEFORE validation
                # Validate serializer without vendor_name to avoid uniqueness error
                serializer_data = request.data.copy()
                serializer_data.pop('vendor_name', None)  # Remove vendor_name from validation
                
                serializer = self.get_serializer(vendor, data=serializer_data)
                serializer.is_valid(raise_exception=True)
                
                with db_transaction.atomic():
                    # Convert new vendor name to uppercase
                    new_vendor_name_upper = new_vendor_name.upper()
                    
                    # Update all transactions from old name to new name
                    Transaction.objects.filter(transaction_from__iexact=old_vendor_name).update(
                        transaction_from=new_vendor_name_upper
                    )
                    Transaction.objects.filter(transaction_to__iexact=old_vendor_name).update(
                        transaction_to=new_vendor_name_upper
                    )
                    
                    # Update existing vendor with new data if provided
                    for key, value in serializer.validated_data.items():
                        setattr(existing_vendor, key, value)
                    existing_vendor.save()
                    
                    # Delete the old vendor
                    vendor.delete()
                    
                    # Return the existing vendor
                    return Response(self.get_serializer(existing_vendor).data)
        
        # Normal update path - validate and update
        serializer = self.get_serializer(vendor, data=request.data)
        serializer.is_valid(raise_exception=True)
        
        new_vendor_name = serializer.validated_data.get('vendor_name')
        
        with db_transaction.atomic():
            # If vendor name is changing
            if new_vendor_name and new_vendor_name != old_vendor_name:
                # Convert new vendor name to uppercase
                new_vendor_name_upper = new_vendor_name.upper()
                
                # Update all transactions with old vendor name in both transaction_from and transaction_to (case-insensitive)
                Transaction.objects.filter(transaction_from__iexact=old_vendor_name).update(
                    transaction_from=new_vendor_name_upper
                )
                Transaction.objects.filter(transaction_to__iexact=old_vendor_name).update(
                    transaction_to=new_vendor_name_upper
                )
                
                # Check if old vendor name has any transactions left (in either transaction_from or transaction_to)
                old_vendor_transaction_count = Transaction.objects.filter(
                    Q(transaction_from__iexact=old_vendor_name) | Q(transaction_to__iexact=old_vendor_name)
                ).count()
                
                # Delete old vendor if no transactions reference it
                if old_vendor_transaction_count == 0:
                    Vendor.objects.filter(vendor_name__iexact=old_vendor_name).exclude(id=vendor.id).delete()
            
            # Save the updated vendor
            self.perform_update(serializer)
        
        return Response(serializer.data)
    
    @extend_schema(
        operation_id="vendors_partial_update",
        description="Partially update a vendor. If vendor_name is changed, all transactions with "
                    "the old vendor name will be updated. If the old vendor has 0 transactions after update, it will be deleted.",
        tags=["Vendors"],
        request=VendorSerializer,
        responses=VendorSerializer,
    )
    def partial_update(self, request, *args, **kwargs):
        """
        Partially update a vendor.
        Updates all related transactions if vendor_name changes.
        If new vendor name already exists, merges into existing vendor and deletes old one.
        Deletes old vendor if it has no more transactions.
        """
        vendor = self.get_object()
        old_vendor_name = vendor.vendor_name
        
        # Check if vendor_name is being changed and if it already exists (BEFORE validation)
        new_vendor_name = request.data.get('vendor_name')
        
        if new_vendor_name and new_vendor_name != old_vendor_name:
            # Check if a vendor with the new name already exists (case-insensitive)
            existing_vendor = Vendor.objects.filter(
                vendor_name__iexact=new_vendor_name
            ).exclude(id=vendor.id).first()
            
            if existing_vendor:
                # Vendor with new name already exists - handle merge BEFORE validation
                # Validate serializer without vendor_name to avoid uniqueness error
                serializer_data = request.data.copy()
                serializer_data.pop('vendor_name', None)  # Remove vendor_name from validation
                
                serializer = self.get_serializer(vendor, data=serializer_data, partial=True)
                serializer.is_valid(raise_exception=True)
                
                with db_transaction.atomic():
                    # Convert new vendor name to uppercase
                    new_vendor_name_upper = new_vendor_name.upper()
                    
                    # Update all transactions from old name to new name
                    Transaction.objects.filter(transaction_from__iexact=old_vendor_name).update(
                        transaction_from=new_vendor_name_upper
                    )
                    Transaction.objects.filter(transaction_to__iexact=old_vendor_name).update(
                        transaction_to=new_vendor_name_upper
                    )
                    
                    # Update existing vendor with new data if provided (only update fields that were provided)
                    for key, value in serializer.validated_data.items():
                        if value is not None:  # Only update if value is provided (partial update)
                            setattr(existing_vendor, key, value)
                    existing_vendor.save()
                    
                    # Delete the old vendor
                    vendor.delete()
                    
                    # Return the existing vendor
                    return Response(self.get_serializer(existing_vendor).data)
        
        # Normal update path - validate and update
        serializer = self.get_serializer(vendor, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        
        new_vendor_name = serializer.validated_data.get('vendor_name')
        
        with db_transaction.atomic():
            # If vendor name is changing
            if new_vendor_name and new_vendor_name != old_vendor_name:
                # Convert new vendor name to uppercase
                new_vendor_name_upper = new_vendor_name.upper()
                
                # Update all transactions with old vendor name in both transaction_from and transaction_to (case-insensitive)
                Transaction.objects.filter(transaction_from__iexact=old_vendor_name).update(
                    transaction_from=new_vendor_name_upper
                )
                Transaction.objects.filter(transaction_to__iexact=old_vendor_name).update(
                    transaction_to=new_vendor_name_upper
                )
                
                # Check if old vendor name has any transactions left (in either transaction_from or transaction_to)
                old_vendor_transaction_count = Transaction.objects.filter(
                    Q(transaction_from__iexact=old_vendor_name) | Q(transaction_to__iexact=old_vendor_name)
                ).count()
                
                # Delete old vendor if no transactions reference it
                if old_vendor_transaction_count == 0:
                    Vendor.objects.filter(vendor_name__iexact=old_vendor_name).exclude(id=vendor.id).delete()
            
            # Save the updated vendor
            self.perform_update(serializer)
        
        return Response(serializer.data)
    
    @extend_schema(
        operation_id="vendors_delete",
        description="Delete a vendor. Only vendors with 0 matching transactions can be deleted.",
        tags=["Vendors"],
        responses={204: None},
    )
    def destroy(self, request, *args, **kwargs):
        """
        Delete a vendor.
        Only allowed if vendor has no associated transactions.
        """
        vendor = self.get_object()
        
        # Check if vendor has any transactions (in either transaction_from or transaction_to)
        transaction_count = Transaction.objects.filter(
            Q(transaction_from__iexact=vendor.vendor_name) | Q(transaction_to__iexact=vendor.vendor_name)
        ).count()
        
        if transaction_count > 0:
            return Response(
                {
                    'error': f'Cannot delete vendor. {transaction_count} transaction(s) reference this vendor.',
                    'transaction_count': transaction_count
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        return super().destroy(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="vendors_cleanup",
        description="Delete all vendors that have 0 matching transactions. "
                    "Returns the count of deleted vendors.",
        tags=["Vendors"],
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'deleted_count': {'type': 'integer'},
                    'message': {'type': 'string'}
                }
            }
        },
    )
    @action(detail=False, methods=['post'])
    def cleanup(self, request):
        """
        Delete all vendors with 0 matching transactions.
        Optimized to use subquery instead of per-vendor queries.
        """
        from django.db.models import OuterRef, Exists
        
        # Use subquery to check if vendor has any transactions
        # Since vendors are connected by name (not FK), we use a subquery
        has_transactions = Transaction.objects.filter(
            Q(transaction_from__iexact=OuterRef('vendor_name')) |
            Q(transaction_to__iexact=OuterRef('vendor_name'))
        )
        
        # Get vendors with no transactions
        vendors_to_delete = Vendor.objects.annotate(
            has_transactions=Exists(has_transactions)
        ).filter(has_transactions=False)
        
        # Get IDs and delete
        vendor_ids = list(vendors_to_delete.values_list('id', flat=True))
        deleted_count = Vendor.objects.filter(id__in=vendor_ids).delete()[0]
        
        return Response({
            'deleted_count': deleted_count,
            'message': f'Successfully deleted {deleted_count} vendor(s) with no transactions'
        }, status=status.HTTP_200_OK)
    
    @extend_schema(
        operation_id="vendors_statistics",
        description="Get vendor statistics including total vendors, vendors with/without images, "
                    "and transaction counts per vendor.",
        tags=["Vendors"],
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'total_vendors': {'type': 'integer'},
                    'vendors_with_image': {'type': 'integer'},
                    'vendors_without_image': {'type': 'integer'},
                    'vendors_with_vat': {'type': 'integer'},
                    'vendors_without_transactions': {'type': 'integer'}
                }
            }
        },
    )
    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """
        Get vendor statistics.
        Optimized to use annotate instead of per-vendor queries.
        """
        queryset = self.filter_queryset(self.get_queryset())
        
        # Since vendors are connected by name (not FK), we use a subquery to count transactions
        from django.db.models import Subquery
        
        # Create a subquery that counts transactions for each vendor
        transaction_count_subquery = Transaction.objects.filter(
            Q(transaction_from__iexact=OuterRef('vendor_name')) |
            Q(transaction_to__iexact=OuterRef('vendor_name'))
        ).aggregate(count=Count('id'))['count']
        
        # Annotate queryset with transaction count using Subquery
        # Since we can't use aggregate in annotate directly, we'll use a different approach:
        # Count transactions that match the vendor name using a filtered Count
        # We need to use a raw SQL approach or iterate, but let's use a simpler method:
        # Get all vendor names and count their transactions in Python (but optimized)
        
        # Actually, let's use Exists to check if vendor has transactions, then count those without
        has_transactions = Transaction.objects.filter(
            Q(transaction_from__iexact=OuterRef('vendor_name')) |
            Q(transaction_to__iexact=OuterRef('vendor_name'))
        )
        
        annotated_queryset = queryset.annotate(
            has_transactions=Exists(has_transactions)
        )
        
        # Aggregate all counts in a single query
        stats_data = annotated_queryset.aggregate(
            total_vendors=Count('id'),
            vendors_with_image=Count(Case(When(~Q(image='') & ~Q(image__isnull=True), then=1), output_field=IntegerField())),
            vendors_without_image=Count(Case(When(Q(image='') | Q(image__isnull=True), then=1), output_field=IntegerField())),
            vendors_with_vat=Count(Case(When(~Q(vendor_vat='') & ~Q(vendor_vat__isnull=True), then=1), output_field=IntegerField())),
            vendors_without_transactions=Count(Case(When(has_transactions=False, then=1), output_field=IntegerField()))
        )
        
        stats = {
            'total_vendors': stats_data['total_vendors'],
            'vendors_with_image': stats_data['vendors_with_image'],
            'vendors_without_image': stats_data['vendors_without_image'],
            'vendors_with_vat': stats_data['vendors_with_vat'],
            'vendors_without_transactions': stats_data['vendors_without_transactions']
        }
        
        return Response(stats, status=status.HTTP_200_OK)
    
    @extend_schema(
        operation_id="vendors_transactions",
        description="Get all transactions associated with this vendor (either as sender or receiver).",
        tags=["Vendors"],
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'vendor': {'type': 'object'},
                    'transactions': {'type': 'array'},
                    'transaction_count': {'type': 'integer'}
                }
            }
        },
    )
    @action(detail=True, methods=['get'])
    def transactions(self, request, pk=None):
        """Get all transactions for a specific vendor."""
        vendor = self.get_object()
        
        transactions = Transaction.objects.filter(
            Q(transaction_from__iexact=vendor.vendor_name) | Q(transaction_to__iexact=vendor.vendor_name)
        ).order_by('-transaction_date')
        
        return Response({
            'vendor': self.get_serializer(vendor).data,
            'transactions': TransactionSerializer(transactions, many=True).data,
            'transaction_count': transactions.count()
        }, status=status.HTTP_200_OK)


class TransactionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Transaction CRUD and bulk operations.
    """
    queryset = Transaction.objects.all().order_by('-transaction_date')
    serializer_class = TransactionSerializer
    filterset_class = TransactionFilter
    filter_backends = [filters.DjangoFilterBackend, StableOrderingFilter]
    ordering_fields = ['id', 'transaction_id', 'status', 'transaction_date', 'amount', 'currency', 'type', 'transaction_from', 'transaction_to']
    ordering = ['-transaction_date', '-id']
    pagination_class = StandardPagination
    
    def get_queryset(self):
        """
        Optimize queryset by prefetching vendors to prevent N+1 queries.
        Note: Vendors are looked up by name (not FK), so we batch fetch all unique vendor names.
        """
        queryset = super().get_queryset()
        # For list/retrieve actions, we'll batch fetch vendors in the serializer
        # This method ensures we have a consistent queryset
        return queryset

    @extend_schema(
        operation_id="transactions_list",
        description="List all transactions with filtering and pagination. "
                    "Supports filtering by type, date range, vendor, currency, and amount range.",
        tags=["Transactions"],
        parameters=[
            OpenApiParameter('type', OpenApiTypes.STR, description='Filter by transaction type (RECEIVED or PAID)'),
            OpenApiParameter('start_date', OpenApiTypes.DATETIME, description='Filter transactions from this date'),
            OpenApiParameter('end_date', OpenApiTypes.DATETIME, description='Filter transactions until this date'),
            OpenApiParameter('transaction_from', OpenApiTypes.STR, description='Filter by transaction sender (partial match)'),
            OpenApiParameter('transaction_to', OpenApiTypes.STR, description='Filter by transaction receiver (partial match)'),
            OpenApiParameter('vendor', OpenApiTypes.STR, description='Filter by vendor name (searches in both transaction_from and transaction_to)'),
            OpenApiParameter('currency', OpenApiTypes.STR, description='Filter by currency code (e.g., USD, EUR)'),
            OpenApiParameter('min_amount', OpenApiTypes.FLOAT, description='Minimum transaction amount'),
            OpenApiParameter('max_amount', OpenApiTypes.FLOAT, description='Maximum transaction amount'),
            OpenApiParameter('transaction_id', OpenApiTypes.STR, description='Search by transaction ID (partial match)'),
            OpenApiParameter('ordering', OpenApiTypes.STR, description='Order results by field (e.g., transaction_id, -transaction_date)'),
        ],
        responses=TransactionSerializer(many=True),
    )
    def list(self, request, *args, **kwargs):
        """List all transactions with filtering."""
        return super().list(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="transactions_retrieve",
        description="Get detailed information about a specific transaction including matched listing data, "
                    "vendor information (image and VAT), and error status if listing not found.",
        tags=["Transactions"],
        responses=TransactionSerializer,
    )
    def retrieve(self, request, *args, **kwargs):
        """Retrieve a single transaction by ID."""
        return super().retrieve(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="transactions_create",
        description="Create a new transaction. Automatically creates vendor entries if transaction_from "
                    "or transaction_to vendors don't exist in the system.",
        tags=["Transactions"],
        request=TransactionSerializer,
        responses=TransactionSerializer,
    )
    def create(self, request, *args, **kwargs):
        """
        Create a single transaction.
        Automatically creates vendors if they don't exist.
        """
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
        operation_id="transactions_update",
        description="Update a transaction. Automatically creates vendor entries if new transaction_from "
                    "or transaction_to vendors don't exist in the system.",
        tags=["Transactions"],
        request=TransactionSerializer,
        responses=TransactionSerializer,
    )
    def update(self, request, *args, **kwargs):
        """Update a transaction (full update)."""
        return super().update(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="transactions_partial_update",
        description="Partially update a transaction. Only provided fields will be updated. "
                    "Automatically creates vendor entries if transaction_from or transaction_to vendors don't exist.",
        tags=["Transactions"],
        request=TransactionSerializer,
        responses=TransactionSerializer,
    )
    def partial_update(self, request, *args, **kwargs):
        """Partially update a transaction."""
        return super().partial_update(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="transactions_delete",
        description="Delete a specific transaction by ID.",
        tags=["Transactions"],
        responses={204: None},
    )
    def destroy(self, request, *args, **kwargs):
        """Delete a single transaction."""
        return super().destroy(request, *args, **kwargs)
    
    @extend_schema(
        operation_id="transactions_preview",
        description="Preview transactions before bulk upload. Does NOT save to database. "
                    "Returns transaction data with matched listing information, vendor details, "
                    "and error messages for transactions without matching listings.",
        tags=["Transactions"],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'transactions': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'transaction_id': {'type': 'string'},
                                'transaction_date': {'type': 'string', 'format': 'date-time'},
                                'amount': {'type': 'number'},
                                'currency': {'type': 'string'},
                                'type': {'type': 'string', 'enum': ['RECEIVED', 'PAID']},
                                'transaction_from': {'type': 'string'},
                                'transaction_to': {'type': 'string'},
                            },
                            'required': ['transaction_id', 'transaction_date', 'amount', 'currency', 'type', 'transaction_from', 'transaction_to']
                        }
                    }
                },
                'required': ['transactions']
            }
        },
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'preview': {'type': 'array'},
                    'total_count': {'type': 'integer'}
                }
            },
        },
    )
    @action(detail=False, methods=['post'])
    def preview(self, request):
        """
        Preview transactions before bulk upload.
        Does NOT save to database. Does NOT create vendors.
        """
        from django.utils.dateparse import parse_datetime
        
        transactions_data = request.data.get('transactions', [])
        
        if not transactions_data:
            return Response(
                {'error': 'No transactions provided'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        preview_data = []
        
        for trans_data in transactions_data:
            try:
                # Parse transaction_date if it's a string
                transaction_date = trans_data.get('transaction_date')
                if isinstance(transaction_date, str):
                    parsed_date = parse_datetime(transaction_date)
                    if parsed_date is None:
                        raise ValueError(f"Invalid datetime format: {transaction_date}")
                    transaction_date = parsed_date
                
                # Create temporary transaction instance (not saved, no pk)
                # This ensures serializer.to_representation() is used, not create()
                # Convert transaction_from and transaction_to to uppercase
                transaction_from = trans_data.get('transaction_from', '').upper() if trans_data.get('transaction_from') else ''
                transaction_to = trans_data.get('transaction_to', '').upper() if trans_data.get('transaction_to') else ''
                
                temp_transaction = Transaction(
                    transaction_id=trans_data.get('transaction_id', ''),
                    transaction_date=transaction_date,
                    amount=trans_data.get('amount', 0),
                    currency=trans_data.get('currency', ''),
                    type=trans_data.get('type', ''),
                    transaction_from=transaction_from,
                    transaction_to=transaction_to
                )
                # Ensure it's not saved (no primary key)
                # This prevents any save() logic from being triggered
                assert temp_transaction.pk is None, "Transaction should not be saved during preview"
                
                # Serialize to get preview with computed fields
                # Using to_representation ensures create() is never called
                serializer = self.get_serializer(temp_transaction)
                preview_data.append(serializer.data)
            except Exception as e:
                preview_data.append({
                    'error': str(e),
                    'data': trans_data
                })
        
        return Response({
            'preview': preview_data,
            'total_count': len(preview_data)
        }, status=status.HTTP_200_OK)
    
    @extend_schema(
        operation_id="transactions_bulk_add",
        description="Bulk add multiple transactions in a single request. "
                    "Automatically creates vendor entries for any vendors that don't exist. "
                    "All transactions must be valid - if any transaction is invalid, nothing is saved. "
                    "Returns all validation errors if any transaction fails validation.",
        tags=["Transactions"],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'transactions': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'transaction_id': {'type': 'string'},
                                'transaction_date': {'type': 'string', 'format': 'date-time'},
                                'amount': {'type': 'number'},
                                'currency': {'type': 'string'},
                                'type': {'type': 'string', 'enum': ['RECEIVED', 'PAID']},
                                'transaction_from': {'type': 'string'},
                                'transaction_to': {'type': 'string'},
                            },
                            'required': ['transaction_id', 'transaction_date', 'amount', 'currency', 'type', 'transaction_from', 'transaction_to']
                        }
                    }
                },
                'required': ['transactions']
            }
        },
        responses={
            201: {
                'type': 'object',
                'properties': {
                    'created_count': {'type': 'integer'},
                    'created_transactions': {'type': 'array'}
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
        Bulk add multiple transactions.
        Automatically creates vendors if they don't exist.
        All transactions must be valid - if any transaction is invalid, nothing is saved.
        """
        transactions_data = request.data.get('transactions', [])
        
        if not transactions_data:
            return Response(
                {'error': 'No transactions provided'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # First pass: Validate all transactions without saving
        serializers = []
        errors = []
        
        for idx, trans_data in enumerate(transactions_data):
            serializer = self.get_serializer(data=trans_data)
            if serializer.is_valid():
                serializers.append((idx, serializer))
            else:
                errors.append({
                    'index': idx,
                    'data': trans_data,
                    'errors': serializer.errors
                })
        
        # If any errors, return all errors without saving anything
        if errors:
            return Response(
                {
                    'error': 'Validation failed for one or more transactions. No transactions were saved.',
                    'error_count': len(errors),
                    'errors': errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # All valid - save all transactions in a single database transaction
        created_transactions = []
        with db_transaction.atomic():
            for idx, serializer in serializers:
                serializer.save()
                created_transactions.append(serializer.data)
        
        return Response(
            {
                'created_count': len(created_transactions),
                'created_transactions': created_transactions
            },
            status=status.HTTP_201_CREATED
        )
    
    @extend_schema(
        operation_id="transactions_bulk_delete",
        description="Bulk delete multiple transactions by their IDs in a single request.",
        tags=["Transactions"],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'ids': {
                        'type': 'array',
                        'items': {'type': 'integer'},
                        'description': 'List of transaction IDs to delete'
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
        Bulk delete transactions by IDs.
        """
        ids = request.data.get('ids', [])
        
        if not ids:
            return Response(
                {'error': 'No transaction IDs provided'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        deleted_count, _ = Transaction.objects.filter(id__in=ids).delete()
        
        return Response({
            'deleted_count': deleted_count,
            'message': f'Successfully deleted {deleted_count} transaction(s)'
        }, status=status.HTTP_200_OK)
    
    @extend_schema(
        operation_id="transactions_statistics",
        description="Get aggregated statistics for transactions. "
                    "Respects current filters - statistics will be calculated only for filtered transactions. "
                    "Returns total count, received/paid totals, average amount, and list of currencies.",
        tags=["Transactions"],
        parameters=[
            OpenApiParameter('type', OpenApiTypes.STR, description='Filter statistics by transaction type'),
            OpenApiParameter('start_date', OpenApiTypes.DATETIME, description='Include transactions from this date'),
            OpenApiParameter('end_date', OpenApiTypes.DATETIME, description='Include transactions until this date'),
            OpenApiParameter('transaction_from', OpenApiTypes.STR, description='Filter statistics by transaction sender'),
            OpenApiParameter('transaction_to', OpenApiTypes.STR, description='Filter statistics by transaction receiver'),
            OpenApiParameter('vendor', OpenApiTypes.STR, description='Filter statistics by vendor (searches both from and to)'),
            OpenApiParameter('currency', OpenApiTypes.STR, description='Filter statistics by currency'),
        ],
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'total_transactions': {'type': 'integer'},
                    'total_received': {
                        'type': 'object',
                        'properties': {
                            'total': {'type': 'number'},
                            'count': {'type': 'integer'}
                        }
                    },
                    'total_paid': {
                        'type': 'object',
                        'properties': {
                            'total': {'type': 'number'},
                            'count': {'type': 'integer'}
                        }
                    },
                    'average_amount': {'type': 'number'},
                    'currencies': {
                        'type': 'array',
                        'items': {'type': 'string'}
                    }
                }
            }
        },
    )
    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """
        Get transaction statistics.
        Respects the current filters applied.
        Optimized to use a single aggregate query instead of multiple queries.
        """
        # Get filtered queryset
        queryset = self.filter_queryset(self.get_queryset())
        
        # Single aggregate query with conditional aggregation
        stats_data = queryset.aggregate(
            total_transactions=Count('id'),
            total_received_amount=Sum(Case(When(type='RECEIVED', then='amount'), default=0, output_field=models.FloatField())),
            total_received_count=Count(Case(When(type='RECEIVED', then=1), output_field=IntegerField())),
            total_paid_amount=Sum(Case(When(type='PAID', then='amount'), default=0, output_field=models.FloatField())),
            total_paid_count=Count(Case(When(type='PAID', then=1), output_field=IntegerField())),
            average_amount=Avg('amount')
        )
        
        # Get currencies in a separate query (can't be aggregated with other stats)
        currencies = list(queryset.values_list('currency', flat=True).distinct())
        
        stats = {
            'total_transactions': stats_data['total_transactions'],
            'total_received': {
                'total': stats_data['total_received_amount'] or 0,
                'count': stats_data['total_received_count']
            },
            'total_paid': {
                'total': stats_data['total_paid_amount'] or 0,
                'count': stats_data['total_paid_count']
            },
            'average_amount': stats_data['average_amount'],
            'currencies': currencies
        }
        
        return Response(stats, status=status.HTTP_200_OK)
    
    @extend_schema(
        operation_id="transactions_match_listing",
        description="Manually trigger listing matching for a specific transaction. "
                    "Returns the transaction with its matched listing data and match status.",
        tags=["Transactions"],
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'transaction': {'type': 'object'},
                    'listing_matched': {'type': 'boolean'}
                }
            },
        },
    )
    @action(detail=True, methods=['post'])
    def match_listing(self, request, pk=None):
        """
        Manually trigger listing matching for a specific transaction.
        Returns the transaction with listing match status.
        """
        transaction_obj = self.get_object()
        serializer = self.get_serializer(transaction_obj)
        
        return Response({
            'transaction': serializer.data,
            'listing_matched': serializer.data['listing_data'] is not None
        }, status=status.HTTP_200_OK)
from rest_framework import serializers
from django.db.models import Q
from .models import Transaction, Vendor
from apps.listings.models import Listing
from apps.listings.serializers import ListingSerializer
from django.utils import timezone
from django.conf import settings
from datetime import datetime


class VendorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vendor
        fields = ['id', 'vendor_name', 'image', 'vendor_vat']

class TransactionSerializer(serializers.ModelSerializer):
    listing_data = serializers.SerializerMethodField()
    error_status_text = serializers.SerializerMethodField()
    vendor_img = serializers.SerializerMethodField()
    vendor_vat = serializers.SerializerMethodField()
    
    class Meta:
        model = Transaction
        fields = [
            'id', 'transaction_id', 'transaction_date', 'amount', 'currency',
            'type', 'transaction_from', 'transaction_to', 'status',
            'listing_data', 'error_status_text', 'vendor_img', 'vendor_vat'
        ]
        read_only_fields = ['listing_data', 'error_status_text', 'vendor_img', 'vendor_vat']
    
    def create(self, validated_data):
        """Create transaction and ensure vendors exist for both transaction_from and transaction_to."""
        # Convert to uppercase before creating
        if validated_data.get('transaction_from'):
            validated_data['transaction_from'] = validated_data['transaction_from'].upper()
            Vendor.objects.get_or_create(
                vendor_name__iexact=validated_data['transaction_from'],
                defaults={'vendor_name': validated_data['transaction_from']}
            )
        
        if validated_data.get('transaction_to'):
            validated_data['transaction_to'] = validated_data['transaction_to'].upper()
            Vendor.objects.get_or_create(
                vendor_name__iexact=validated_data['transaction_to'],
                defaults={'vendor_name': validated_data['transaction_to']}
            )
        
        return super().create(validated_data)
    
    def update(self, instance, validated_data):
        """
        Update transaction and ensure vendors exist for both transaction_from and transaction_to.
        Delete old vendors if they have no more transactions.
        """
        old_transaction_from = instance.transaction_from
        old_transaction_to = instance.transaction_to
        
        # Convert to uppercase before updating
        if 'transaction_from' in validated_data and validated_data.get('transaction_from'):
            validated_data['transaction_from'] = validated_data['transaction_from'].upper()
        if 'transaction_to' in validated_data and validated_data.get('transaction_to'):
            validated_data['transaction_to'] = validated_data['transaction_to'].upper()
        
        new_transaction_from = validated_data.get('transaction_from', instance.transaction_from)
        new_transaction_to = validated_data.get('transaction_to', instance.transaction_to)
        
        # Create new vendors if they don't exist
        if new_transaction_from:
            Vendor.objects.get_or_create(
                vendor_name__iexact=new_transaction_from,
                defaults={'vendor_name': new_transaction_from}
            )
        
        if new_transaction_to:
            Vendor.objects.get_or_create(
                vendor_name__iexact=new_transaction_to,
                defaults={'vendor_name': new_transaction_to}
            )
        
        # Update the transaction
        updated_instance = super().update(instance, validated_data)
        
        # Check and delete old vendors if they have no transactions
        vendors_to_check = set()
        
        if old_transaction_from != new_transaction_from:
            vendors_to_check.add(old_transaction_from)
        
        if old_transaction_to != new_transaction_to:
            vendors_to_check.add(old_transaction_to)
        
        for vendor_name in vendors_to_check:
            if vendor_name:
                # Count transactions with this vendor name in either transaction_from or transaction_to
                transaction_count = Transaction.objects.filter(
                    Q(transaction_from__iexact=vendor_name) | Q(transaction_to__iexact=vendor_name)
                ).count()
                
                # Delete vendor if no transactions reference it
                if transaction_count == 0:
                    Vendor.objects.filter(vendor_name__iexact=vendor_name).delete()
        
        return updated_instance

    def _get_closest_listing(self, obj):
        """
        Internal method to find and cache the closest matching listing.
        """
        # Use an object-specific cache key so that each transaction
        # gets its own cached listing even when serializing many objects
        cache_key = f"_cached_listing_{getattr(obj, 'id', None) or id(obj)}"

        # Check if we've already calculated this for this particular object
        if hasattr(self, cache_key):
            return getattr(self, cache_key)
        
        from datetime import timedelta
        import math
        
        # Thresholds
        amount_threshold = 10  # Price difference threshold
        time_threshold_seconds = 10  # Time difference threshold in seconds
        try:
            amount = float(obj.amount)
        except:
            setattr(self, cache_key, None)
            return None

        if not isinstance(obj.transaction_date, datetime):
            setattr(self, cache_key, None)
            return None
        transaction_date = obj.transaction_date
        if timezone.is_naive(transaction_date):
            transaction_date = timezone.make_aware(transaction_date)
            
        # Get all listings within reasonable range
        time_range = timedelta(seconds=time_threshold_seconds)
        potential_listings = Listing.objects.filter(
            timestamp__gte=transaction_date - time_range,
            timestamp__lte=transaction_date + time_range,
            price__gte=amount - amount_threshold,
            price__lte=amount + amount_threshold
        ).order_by('timestamp')
        if not potential_listings.exists():
            setattr(self, cache_key, None)
            return None
        
        # Find the closest listing using distance formula
        closest_listing = None
        min_distance = float('inf')
        
        for listing in potential_listings:
            # Calculate time difference in seconds
            time_diff = abs((listing.timestamp - transaction_date).total_seconds())
            
            # Calculate amount difference
            amount_diff = abs(listing.price - amount)
            
            # Calculate distance: sqrt((time_weight * time_diff)^2 + (amount_weight * amount_diff)^2)
            time_weight = 0.8  # Weight for time difference
            amount_weight = 1.0  # Weight for amount difference
            
            distance = math.sqrt(
                (time_weight * time_diff) ** 2 + 
                (amount_weight * amount_diff) ** 2
            )
            
            if distance < min_distance:
                min_distance = distance
                closest_listing = listing
        
        # Cache the result for this particular object
        setattr(self, cache_key, closest_listing)
        return closest_listing
    
    def _get_vendor(self, obj):
        """
        Internal method to find and cache the vendor (only from transaction_to for display purposes).
        Note: Vendors are connected to both transaction_from and transaction_to, but
        vendor_img and vendor_vat only use transaction_to.
        """
        # Use an object-specific cache key so that each transaction
        # gets its own cached vendor even when serializing many objects
        cache_key = f"_cached_vendor_{getattr(obj, 'id', None) or id(obj)}"

        # Check if we've already fetched this for this particular object
        if hasattr(self, cache_key):
            return getattr(self, cache_key)
        
        vendor = None
        if obj.transaction_to:
            vendor = Vendor.objects.filter(
                vendor_name__iexact=obj.transaction_to
            ).first()
        
        # Cache the result for this particular object
        setattr(self, cache_key, vendor)
        return vendor
    
    def get_listing_data(self, obj):
        """
        Get the closest matching listing data.
        """
        closest_listing = self._get_closest_listing(obj)
        
        if closest_listing:
            return ListingSerializer(closest_listing).data
        return None
    
    def get_error_status_text(self, obj):
        """
        Return error status text if listing is not found or if listing has no connected ASINs.
        """
        closest_listing = self._get_closest_listing(obj)
        
        if not closest_listing:
            return "No matching listing found for this transaction"
        
        # Check if the found listing has connected ASINs
        # Use prefetched data if available to avoid additional query
        if hasattr(closest_listing, 'listings_asins'):
            if hasattr(closest_listing, '_prefetched_objects_cache') and 'listings_asins' in closest_listing._prefetched_objects_cache:
                asin_count = len(closest_listing.listings_asins.all())
            else:
                asin_count = closest_listing.listings_asins.count()
            if asin_count == 0:
                return "Matching listing found but has no connected ASINs"
        
        return None
    
    def get_vendor_img(self, obj):
        """
        Get vendor image from cached vendor.
        """
        vendor = self._get_vendor(obj)
        
        if vendor and vendor.image:
            return vendor.image.url if hasattr(vendor.image, 'url') else str(vendor.image)
        
        return None
    
    def get_vendor_vat(self, obj):
        """
        Get vendor VAT from cached vendor.
        """
        vendor = self._get_vendor(obj)
        
        if vendor:
            return vendor.vendor_vat
        
        return None

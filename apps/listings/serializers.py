from rest_framework import serializers
from .models import Listing, Shelf, InventoryVendor, Asin, ListingAsin
import json


class ListingSerializer(serializers.ModelSerializer):
    error_status_text = serializers.SerializerMethodField()

    class Meta:
        model = Listing
        fields = ['id', 'listing_url', 'picture_urls', 'price', 'timestamp', 'tracking_number', 'error_status_text']
        read_only_fields = ['error_status_text']

    def validate_picture_urls(self, value):
        """
        Validate that picture_urls is a JSON array of strings.
        Accepts both JSON strings (e.g., '["url1", "url2"]') and already-parsed lists.
        """
        # Handle None case (if field is optional)
        if value is None or not value:
            raise serializers.ValidationError("This field may not be null.")
        
        # If value is a string, try to parse it as JSON
        if isinstance(value, str):
            # Handle empty string
            if not value.strip():
                return []
            try:
                value = json.loads(value)
            except json.JSONDecodeError as e:
                raise serializers.ValidationError(
                    f"picture_urls must be valid JSON array: [\"url1\", \"url2\", ...]. Error: {str(e)}"
                )
        
        # Validate that it's a list
        if not isinstance(value, list):
            raise serializers.ValidationError(
                f"picture_urls must be a JSON array, got {type(value).__name__}. "
                f"Expected format: [\"url1\", \"url2\", ...]"
            )
        
        # Validate that all items in the array are strings
        for idx, item in enumerate(value):
            if not isinstance(item, str):
                raise serializers.ValidationError(
                    f"All items in picture_urls must be strings (URLs). "
                    f"Item at index {idx} is {type(item).__name__}: {item}"
                )
        
        return value

    def to_representation(self, instance):
        """
        Convert picture_urls to JSON string before sending to frontend.
        """
        representation = super().to_representation(instance)
        
        # Convert picture_urls (which is a list from JSONField) to JSON string
        if 'picture_urls' in representation and representation['picture_urls'] is not None:
            if isinstance(representation['picture_urls'], list):
                representation['picture_urls'] = json.dumps(representation['picture_urls'])
            # If it's already a string, keep it as is
        
        return representation

    def get_error_status_text(self, obj):
        """
        Return error status text if listing does not have connected asins.
        Optimized: Uses prefetched listings_asins to avoid additional query.
        """
        # Check if listing has any connected ASINs through ListingAsin relationship
        # Use prefetched data if available, otherwise fall back to count()
        if hasattr(obj, 'listings_asins'):
            # If prefetched, use len() to avoid query; otherwise use count()
            if hasattr(obj, '_prefetched_objects_cache') and 'listings_asins' in obj._prefetched_objects_cache:
                asin_count = len(obj.listings_asins.all())
            else:
                asin_count = obj.listings_asins.count()
            if asin_count == 0:
                return "No connected ASINs found for this listing"
        
        return None


# ============== Inventory Serializers ==============

class ShelfSerializer(serializers.ModelSerializer):
    """Serializer for Shelf model"""
    
    class Meta:
        model = Shelf
        fields = ['id', 'name', 'order']


class InventoryVendorSerializer(serializers.ModelSerializer):
    """Serializer for InventoryVendor model"""
    
    class Meta:
        model = InventoryVendor
        fields = ['id', 'name', 'photo', 'order']


class ListingAsinSerializer(serializers.ModelSerializer):
    """Serializer for ListingAsin with nested listing data"""
    listing = ListingSerializer(read_only=True)
    
    class Meta:
        model = ListingAsin
        fields = ['id', 'listing', 'amount']


class AsinSerializer(serializers.ModelSerializer):
    """Serializer for Asin (inventory item) model"""
    error_status_text = serializers.SerializerMethodField()
    
    # Nested listing data
    listings = ListingAsinSerializer(source='asins_listings', many=True, read_only=True)
    
    class Meta:
        model = Asin
        fields = [
            'id', 'value', 'name', 'ean', 
            'vendor', 'amount', 'shelf', 'contains',
            'listings', 'error_status_text'
        ]
        read_only_fields = ['listings', 'error_status_text']
    
    def get_error_status_text(self, obj):
        """
        Return error status text if item does not have connected listings.
        Optimized: Uses prefetched asins_listings to avoid additional query.
        """
        # Check if item has any connected Listings through ListingAsin relationship
        # Use prefetched data if available, otherwise fall back to count()
        # if hasattr(obj, 'asins_listings'):
        #     # If prefetched, use len() to avoid query; otherwise use count()
        #     if hasattr(obj, '_prefetched_objects_cache') and 'asins_listings' in obj._prefetched_objects_cache:
        #         listing_count = len(obj.asins_listings.all())
        #     else:
        #         listing_count = obj.asins_listings.count()
        #     if listing_count == 0:
        #         return "No connected listings found for this item"
        
        return None




class AsinPreviewItemSerializer(serializers.Serializer):
    """Serializer for preview API - validates input data"""
    
    value = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    name = serializers.CharField(max_length=255)
    ean = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    vendor = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, default=0)
    shelf = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    contains = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')


class AsinBulkAddItemSerializer(serializers.Serializer):
    """Serializer for bulk add API"""
    
    value = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    name = serializers.CharField(max_length=255)
    ean = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    vendor = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, default=0)
    shelf = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    contains = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')
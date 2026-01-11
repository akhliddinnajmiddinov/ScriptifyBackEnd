from rest_framework import serializers
from .models import Listing
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
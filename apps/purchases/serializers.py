from rest_framework import serializers
from .models import Purchases
from apps.transactions.models import Vendor


class PurchasesSerializer(serializers.ModelSerializer):
    """
    Serializer for Purchases model.
    chat_link is built dynamically from external_id via model property.
    vendor_image is fetched from Vendor model based on platform name.
    """
    chat_link = serializers.ReadOnlyField()
    vendor_image = serializers.SerializerMethodField()
    
    class Meta:
        model = Purchases
        fields = '__all__'
        read_only_fields = ['created_at', 'modified_at', 'chat_link', 'vendor_image']
    
    def _get_vendor(self, obj):
        """
        Internal method to find and cache the vendor based on platform name.
        Uses case-insensitive matching since vendor_name is stored uppercase.
        Uses prefetched vendors from context to avoid N+1 queries.
        """
        if not obj.platform:
            return None
        
        # Use platform name as cache key so purchases with same platform share cached vendor
        cache_key = f"_cached_vendor_{obj.platform.upper()}"

        # Check if we've already fetched this vendor for this platform
        if hasattr(self, cache_key):
            return getattr(self, cache_key)
        
        vendor = Vendor.objects.filter(
            vendor_name__iexact=obj.platform
        ).first()
        
        # Cache the result for this platform
        setattr(self, cache_key, vendor)
        return vendor
    
    def get_vendor_image(self, obj):
        """
        Get vendor image URL from Vendor model based on platform name.
        """
        vendor = self._get_vendor(obj)
        
        if vendor and vendor.image:
            return vendor.image.url if hasattr(vendor.image, 'url') else str(vendor.image)
        
        return None

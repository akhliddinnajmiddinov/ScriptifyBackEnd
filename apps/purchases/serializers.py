from rest_framework import serializers
from django.utils import timezone
from .models import Purchases
from apps.transactions.models import Vendor
from apps.listings.models import Listing, ListingAsin, Asin


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

    def to_representation(self, instance):
        """
        Enrich items with matching listing data and connected ASINs.
        """
        ret = super().to_representation(instance)
        items = ret.get('items')

        if items and isinstance(items, list):
            # 1. Collect stored IDs for pre-fetching to avoid N+1
            list_ids = [item.get('listing_id') for item in items if item.get('listing_id')]
            urls = [item.get('url') for item in items if item.get('url')]
            
            # 2. Fetch all potential listings
            listings_by_id = {l.id: l for l in Listing.objects.filter(id__in=list_ids)} if list_ids else {}
            listings_by_url = {l.listing_url: l for l in Listing.objects.filter(listing_url__in=urls)} if urls else {}
            
            # 3. Fetch all ListingAsin for this purchase once
            all_connections = list(ListingAsin.objects.filter(purchase=instance).select_related('asin'))

            is_approved = instance.approved_status == 'approved'
            reconstructed_items = []
            
            for item in items:
                listing_id = item.get('listing_id')
                url = item.get('url')
                
                # Discover listing: Priority to stored ID, fall back to URL match
                listing = listings_by_id.get(listing_id) or listings_by_url.get(url)
                
                # Fetch essential connected ASINs for this listing
                asins = []
                if listing:
                    asins = [
                        {
                            'id': c.asin.id if c.asin else None,
                            'value': c.asin.value if c.asin else "",
                            'name': c.asin.name if c.asin else "",
                            'quantity': c.amount
                        }
                        for c in all_connections if c.listing_id == listing.id
                    ]

                if is_approved:
                    # Relational data is the source of truth for finalized purchases
                    if listing:
                        reconstructed_items.append({
                            'listing_id': listing.id,
                            'url': listing.listing_url,
                            'price': listing.price,
                            'image_urls': listing.picture_urls,
                            'title': item.get('title', ''), # Preserved in JSON during stripping
                            'connected_asins': asins
                        })
                    else:
                        # Fallback case (item was rejected/approved without a listing match)
                        item['listing_id'] = None
                        item['connected_asins'] = asins
                        reconstructed_items.append(item)
                else:
                    # JSON data is the source of truth for pending purchases
                    # We ONLY inject the relational matching info
                    lid = listing.id if listing else None
                    item['listing_id'] = lid
                    item['connected_asins'] = asins
                    reconstructed_items.append(item)
            
            ret['items'] = reconstructed_items

        return ret
    
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

    def update(self, instance, validated_data):
        """
        Auto-set approved_rejected_at when approved_status changes.
        """
        if 'approved_status' in validated_data:
            new_status = validated_data['approved_status']
            if instance.approved_status is not None:
                # If status is already set, it cannot be changed or cleared
                if new_status != instance.approved_status:
                    raise serializers.ValidationError({
                        "approved_status": f"Status has already been set to '{instance.approved_status}' and cannot be changed."
                    })
            else:
                # Status is being set for the first time
                if new_status and not instance.approved_rejected_at:
                    validated_data['approved_rejected_at'] = timezone.now()
                # If new_status is None and old status was None, do nothing

        # Handle ASIN synchronization ONLY if status is approved or rejected
        # If it's pending (None or 'pending'), we just save the raw JSON without syncing to Listings.
        items_data = validated_data.get('items')
        if items_data is not None and isinstance(items_data, list):
            target_status = validated_data.get('approved_status', instance.approved_status)
            
            if target_status == 'approved':
                # Find listings for these items
                list_ids = [it.get('listing_id') for it in items_data if it.get('listing_id')]
                urls = [it.get('url') for it in items_data if it.get('url')]
                
                listings_by_id = {l.id: l for l in Listing.objects.filter(id__in=list_ids)} if list_ids else {}
                listings_by_url = {l.listing_url: l for l in Listing.objects.filter(listing_url__in=urls)} if urls else {}

                for item_data in items_data:
                    listing_id = item_data.get('listing_id')
                    url = item_data.get('url')
                    connected_asins = item_data.get('connected_asins')
                    
                    # 1. Discover listing
                    listing = listings_by_id.get(listing_id) or listings_by_url.get(url)

                    # 2. Update or Create Listing (and prioritize existing listing data if payload is stripped)
                    if listing:
                        # Fallback to listing data if payload is missing info (already stripped)
                        url = url or listing.listing_url
                        price_val = item_data.get('price')
                        price = float(price_val) if price_val is not None else listing.price
                        image_urls = item_data.get('image_urls') or listing.picture_urls
                        
                        # Apply updates
                        listing.price = price
                        listing.listing_url = url
                        if image_urls:
                            listing.picture_urls = image_urls
                        if instance.tracking_code:
                            listing.tracking_number = instance.tracking_code
                        listing.timestamp = timezone.now()
                        listing.save()
                    elif url:
                        # Create new listing
                        price = float(item_data.get('price') or 0.0)
                        image_urls = item_data.get('image_urls', [])
                        listing = Listing.objects.create(
                            listing_url=url,
                            price=price,
                            timestamp=timezone.now(),
                            picture_urls=image_urls,
                            tracking_number=instance.tracking_code or None
                        )
                        listings_by_url[url] = listing

                    # 3. Handle ASIN synchronization (update amount or create)
                    if listing and connected_asins is not None:
                        # Extract ID to local variable to help with type inference/clarity
                        lid = listing.id
                        for conn in connected_asins:
                            asin_id = conn.get('id')
                            if asin_id:
                                # Ensure amount is at least 1 for new/updated connections
                                raw_amount = conn.get('quantity')
                                amount = int(raw_amount) if raw_amount not in [None, ""] else 1
                                if amount < 1: amount = 1
                                
                                listing_asin, created = ListingAsin.objects.get_or_create(
                                    purchase=instance,
                                    listing_id=lid,
                                    asin_id=asin_id,
                                    defaults={'amount': amount}
                                )
                                if not created and listing_asin.amount != amount:
                                    listing_asin.amount = amount
                                    listing_asin.save()
                        
                        # Handle potential removals
                        if len(connected_asins) > 0:
                            current_asin_ids = [c.get('id') for c in connected_asins if c.get('id')]
                            ListingAsin.objects.filter(
                                purchase=instance, 
                                listing_id=lid
                            ).exclude(asin_id__in=current_asin_ids).delete()
                        else:
                            ListingAsin.objects.filter(purchase=instance, listing_id=lid).delete()

                    # 4. Clear JSON data, keeping ONLY listing_id AND title
                    if listing:
                        stored_title = item_data.get('title', '')
                        item_data.clear()
                        item_data['listing_id'] = listing.id
                        item_data['title'] = stored_title
            else:
                # For pending purchases, just strip the temporary UI fields before saving raw JSON
                for item_data in items_data:
                    item_data.pop('connected_asins', None)
                    item_data.pop('matching_listing_id', None)

        return super().update(instance, validated_data)

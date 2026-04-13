from rest_framework import serializers
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from .models import Purchases
from transactions.models import Vendor
from listings.models import Listing, ListingAsin, Asin
from tasks.models import Task
from tasks.services import create_task_run, enqueue_task_run_safely


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
                            'description': item.get('description'),
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
        Uses prefetched vendors from context (populated by the viewset) to avoid
        N+1 queries. Falls back to a direct DB query when context is unavailable
        (e.g. when the serializer is used outside a viewset request).
        """
        if not obj.platform:
            return None

        platform_key = obj.platform.upper()

        # 1. Use prefetched vendors from viewset context (fast path, no extra query)
        prefetched = self.context.get('prefetched_vendors')
        if prefetched is not None:
            return prefetched.get(platform_key)

        # 2. Fallback: per-serializer instance cache to avoid repeated queries
        cache_key = f"_cached_vendor_{platform_key}"
        if hasattr(self, cache_key):
            return getattr(self, cache_key)

        vendor = Vendor.objects.filter(vendor_name__iexact=obj.platform).first()
        setattr(self, cache_key, vendor)
        return vendor
    
    def get_vendor_image(self, obj):
        """
        Get vendor image URL from Vendor model based on platform name.
        """
        vendor = self._get_vendor(obj)

        if vendor and vendor.image:
            image_url = vendor.image.url if hasattr(vendor.image, 'url') else str(vendor.image)
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(image_url)
            return image_url

        return None

    def update(self, instance, validated_data):
        """
        Auto-set approved_rejected_at when approved_status changes.
        """
        with transaction.atomic():
            should_start_vinted_completion = (
                instance.platform == 'vinted'
                and instance.approved_status is None
                and validated_data.get('approved_status') == 'approved'
            )

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

                        # 3. Handle ASIN synchronization: set applied=True and update inventory
                        if listing and connected_asins is not None:
                            lid = listing.id
                            for conn in connected_asins:
                                asin_id = conn.get('id')
                                if asin_id:
                                    raw_amount = conn.get('quantity')
                                    amount = int(raw_amount) if raw_amount not in [None, ""] else 1
                                    if amount < 1:
                                        amount = 1

                                    try:
                                        listing_asin = ListingAsin.objects.get(
                                            purchase=instance,
                                            listing_id=lid,
                                            asin_id=asin_id,
                                        )
                                        if listing_asin.amount != amount:
                                            listing_asin.amount = amount
                                            listing_asin.save()
                                    except ListingAsin.DoesNotExist:
                                        listing_asin = ListingAsin.objects.create(
                                            purchase=instance,
                                            listing_id=lid,
                                            asin_id=asin_id,
                                            amount=amount,
                                            applied=False,
                                            timestamp=timezone.now(),
                                        )

                                    Asin.objects.filter(id=asin_id).update(
                                        amount=F('amount') + listing_asin.amount
                                    )
                                    listing_asin.applied = True
                                    listing_asin.save()

                            if len(connected_asins) > 0:
                                current_asin_ids = [c.get('id') for c in connected_asins if c.get('id')]
                                # Only delete unapplied orphans — applied records must not be silently removed
                                ListingAsin.objects.filter(
                                    purchase=instance,
                                    listing_id=lid,
                                    applied=False,
                                ).exclude(asin_id__in=current_asin_ids).delete()
                            else:
                                ListingAsin.objects.filter(
                                    purchase=instance,
                                    listing_id=lid,
                                    applied=False,
                                ).delete()

                        # 4. Clear JSON data, keeping ONLY listing_id, title, and description
                        if listing:
                            stored_title = item_data.get('title', '')
                            stored_description = item_data.get('description')
                            item_data.clear()
                            item_data['listing_id'] = listing.id
                            item_data['title'] = stored_title
                            item_data['description'] = stored_description
                elif target_status == 'rejected':
                    # For rejected purchases: strip UI-only fields and delete all unapplied ListingAsin records.
                    ListingAsin.objects.filter(purchase=instance, applied=False).delete()
                    for item_data in items_data:
                        item_data.pop('connected_asins', None)
                        item_data.pop('matching_listing_id', None)
                else:
                    # For pending (None) purchases: sync ListingAsin(applied=False) so ASINs
                    # can be pre-assigned before the package arrives / before approval.
                    list_ids_p = [it.get('listing_id') for it in items_data if it.get('listing_id')]
                    urls_p = [it.get('url') for it in items_data if it.get('url')]
                    listings_by_id_p = {l.id: l for l in Listing.objects.filter(id__in=list_ids_p)} if list_ids_p else {}
                    listings_by_url_p = {l.listing_url: l for l in Listing.objects.filter(listing_url__in=urls_p)} if urls_p else {}

                    for item_data in items_data:
                        listing_id_p = item_data.get('listing_id')
                        url_p = item_data.get('url')
                        connected_asins_p = item_data.get('connected_asins')

                        # Discover listing by stored ID, fall back to URL match
                        listing_p = listings_by_id_p.get(listing_id_p) or listings_by_url_p.get(url_p)

                        # Create listing if URL is available but no listing exists yet
                        if not listing_p and url_p:
                            price_p = float(item_data.get('price') or 0.0)
                            image_urls_p = item_data.get('image_urls', [])
                            listing_p = Listing.objects.create(
                                listing_url=url_p,
                                price=price_p,
                                timestamp=timezone.now(),
                                picture_urls=image_urls_p,
                                tracking_number=None,
                            )
                            listings_by_url_p[url_p] = listing_p

                        # Sync ListingAsin records with applied=False
                        if listing_p and connected_asins_p is not None:
                            lid_p = listing_p.id
                            for conn in connected_asins_p:
                                asin_id_p = conn.get('id')
                                if asin_id_p:
                                    raw_amount_p = conn.get('quantity')
                                    amount_p = int(raw_amount_p) if raw_amount_p not in [None, ""] else 1
                                    if amount_p < 1:
                                        amount_p = 1
                                    la_p, created_p = ListingAsin.objects.get_or_create(
                                        purchase=instance,
                                        listing_id=lid_p,
                                        asin_id=asin_id_p,
                                        defaults={'amount': amount_p, 'applied': False, 'timestamp': timezone.now()},
                                    )
                                    if not created_p and la_p.amount != amount_p:
                                        la_p.amount = amount_p
                                        la_p.save()

                            if len(connected_asins_p) > 0:
                                current_ids_p = [c.get('id') for c in connected_asins_p if c.get('id')]
                                # Only delete unapplied orphans — never delete applied records
                                ListingAsin.objects.filter(
                                    purchase=instance,
                                    listing_id=lid_p,
                                    applied=False,
                                ).exclude(asin_id__in=current_ids_p).delete()
                            else:
                                ListingAsin.objects.filter(
                                    purchase=instance,
                                    listing_id=lid_p,
                                    applied=False,
                                ).delete()

                        # Strip UI-only fields before persisting JSON
                        item_data.pop('connected_asins', None)
                        item_data.pop('matching_listing_id', None)

            updated_instance = super().update(instance, validated_data)

            if should_start_vinted_completion:
                try:
                    task = Task.objects.get(slug='vinted-purchase-completion', is_active=True)
                except Task.DoesNotExist as exc:
                    raise serializers.ValidationError({
                        "approved_status": "Vinted purchase completion task is not configured."
                    }) from exc

                request = self.context.get('request')
                started_by = request.user if request and getattr(request.user, 'is_authenticated', False) else None
                platform_data = updated_instance.platform_data or {}
                task_run = create_task_run(
                    task=task,
                    started_by=started_by,
                    input_data={
                        'purchase_id': updated_instance.id,
                        'purchase_external_id': updated_instance.external_id,
                        'transaction_id': platform_data.get('transaction_id'),
                    },
                )
                transaction.on_commit(lambda: enqueue_task_run_safely(task_run.id))

            return updated_instance

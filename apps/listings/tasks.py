"""
Celery tasks for the listings app.

Uses two SP-API endpoints:
  1. CatalogItems.get_catalog_item — title, images (5 req/s)
  2. Products.get_item_offers_batch — pricing (0.1 req/s, 20 ASINs per batch)

Results are merged and saved to Asin.min_listing_data.
"""
import logging
import time
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def fetch_min_prices_task(self, task_id: int):
    """
    Iterate over all ASINs with a non-empty value,
    fetch listing data (title, images) + lowest pricing from Amazon,
    merge them, and save to asin.min_listing_data.

    The MinPriceTask instance (task_id) is updated in-place so the
    frontend can poll for progress.
    """

    try:
        from .models import Asin, MinPriceTask
        from .sp_api_utils import (
            fetch_single_asin_data,
            merge_listing_data,
        )

        task_obj = MinPriceTask.objects.get(id=task_id)
        task_obj.status = 'RUNNING'
        task_obj.started_at = timezone.now()
        task_obj.save()

        from sp_api.api import Products
        from sp_api.api import CatalogItems
        from sp_api.api.catalog_items.catalog_items import CatalogItemsVersion
        from sp_api.base import Marketplaces

        products_api = Products(marketplace=Marketplaces.DE)
        catalog_api = CatalogItems(
            marketplace=Marketplaces.DE,
            version=CatalogItemsVersion.LATEST,
        )

        # Get all ASINs that have a non-empty value
        asins = list(
            Asin.objects.exclude(value__isnull=True)
            .exclude(value='')
            .values_list('id', 'value', named=False)
        )

        task_obj.total_asins = len(asins)
        task_obj.processed_asins = 0
        task_obj.save()

        logger.info(
            f"MinPriceTask #{task_id}: Starting for {len(asins)} ASINs "
            f"(processing individually to avoid batch failures)"
        )
        
        for idx, (asin_id, asin_value) in enumerate(asins):
            # Check if task was cancelled
            task_obj.refresh_from_db()
            if task_obj.status == 'CANCELLED':
                logger.info(
                    f"MinPriceTask #{task_id}: Cancelled at "
                    f"{idx}/{len(asins)}"
                )
                task_obj.finished_at = timezone.now()
                task_obj.save()
                return

            logger.info(
                f"MinPriceTask #{task_id}: Processing ASIN {idx + 1}/{len(asins)}: {asin_value}"
            )

            # Fetch both catalog and pricing data for this ASIN
            # This processes them sequentially but ensures one failure doesn't affect others
            catalog, pricing = fetch_single_asin_data(catalog_api, products_api, asin_value)

            # Merge and save immediately
            merged = merge_listing_data(asin_value, catalog, pricing)
            merged['fetched_at'] = timezone.now().isoformat()

            logger.debug(f"  Saving merged data for ASIN {asin_value}: min_price={merged.get('min_price')}, has_title={bool(merged.get('title'))}, has_images={len(merged.get('images', []))}")
            Asin.objects.filter(id=asin_id).update(
                min_listing_data=merged
            )

            # Update progress after each ASIN
            task_obj.processed_asins = idx + 1
            task_obj.save()

        task_obj.status = 'SUCCESS'
        task_obj.finished_at = timezone.now()
        task_obj.save()
        logger.info(f"MinPriceTask #{task_id}: Completed successfully")

    except Exception as e:
        logger.error(f"MinPriceTask #{task_id}: Failed - {e}", exc_info=True)
        task_obj.refresh_from_db()
        if task_obj.status != 'CANCELLED':
            task_obj.status = 'FAILURE'
            task_obj.error_message = str(e)
            task_obj.finished_at = timezone.now()
            task_obj.save()

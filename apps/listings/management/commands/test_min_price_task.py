"""
Management command to test the fetch_min_prices_task directly.
This bypasses Celery and runs the task synchronously for debugging.
"""
from django.core.management.base import BaseCommand
from apps.listings.models import Asin, MinPriceTask
from apps.listings.tasks import fetch_min_prices_task
from django.utils import timezone


class Command(BaseCommand):
    help = 'Test the fetch_min_prices_task directly (bypasses Celery)'

    def handle(self, *args, **options):
        from apps.listings.models import Asin, MinPriceTask
        from django.utils import timezone
        
        self.stdout.write("=" * 80)
        self.stdout.write("Testing fetch_min_prices_task")
        self.stdout.write("=" * 80)
        
        # Get a few ASINs to test with
        test_asins = list(Asin.objects.exclude(value__isnull=True).exclude(value='')[:5])
        asin_count = len(test_asins)
        
        if asin_count == 0:
            self.stdout.write(self.style.ERROR("No ASINs found in database. Please add some ASINs first."))
            return
        
        self.stdout.write(f"\nFound {asin_count} ASINs to test:")
        for asin in test_asins:
            self.stdout.write(f"  - {asin.value} (ID: {asin.id})")
        
        # Create a test task
        task_obj = MinPriceTask.objects.create(
            status='PENDING',
            total_asins=asin_count,
            processed_asins=0,
        )
        
        self.stdout.write(f"\nCreated MinPriceTask #{task_obj.id}")
        self.stdout.write(f"Starting task execution...\n")
        
        try:
            # Create a mock Celery task object
            class MockTask:
                def __init__(self):
                    self.request = type('Request', (), {'id': f'test-{task_obj.id}'})()
            
            mock_task = MockTask()
            
            # Import and call the function code directly (extract the logic)
            from apps.listings.sp_api_utils import (
                fetch_min_prices_batch,
                fetch_catalog_data,
                merge_listing_data,
                BATCH_SIZE,
            )
            from sp_api.api import Products
            from sp_api.api import CatalogItems
            from sp_api.api.catalog_items.catalog_items import CatalogItemsVersion
            from sp_api.base import Marketplaces
            
            task_obj.status = 'RUNNING'
            task_obj.started_at = timezone.now()
            task_obj.save()
            
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
            
            total_batches = (len(asins) + BATCH_SIZE - 1) // BATCH_SIZE
            self.stdout.write(f"Processing {len(asins)} ASINs in {total_batches} batches (batch_size={BATCH_SIZE})")
            
            for batch_start in range(0, len(asins), BATCH_SIZE):
                # Check if task was cancelled
                task_obj.refresh_from_db()
                if task_obj.status == 'CANCELLED':
                    self.stdout.write(f"Cancelled at {batch_start}/{len(asins)}")
                    task_obj.finished_at = timezone.now()
                    task_obj.save()
                    return
                
                batch = asins[batch_start:batch_start + BATCH_SIZE]
                batch_asin_values = [asin_value for _, asin_value in batch]
                batch_id_map = {asin_value: asin_id for asin_id, asin_value in batch}
                
                batch_num = batch_start // BATCH_SIZE + 1
                self.stdout.write(f"Processing batch {batch_num}/{total_batches} ({len(batch)} ASINs)")
                
                # Step 1: Fetch catalog data
                self.stdout.write(f"  Fetching catalog data for {len(batch)} ASINs...")
                catalog_results = fetch_catalog_data(catalog_api, batch_asin_values)
                self.stdout.write(f"  Catalog results: {len([r for r in catalog_results.values() if r is not None])}/{len(batch_asin_values)} successful")
                
                # Step 2: Fetch pricing data
                self.stdout.write(f"  Fetching pricing data for {len(batch)} ASINs...")
                pricing_results = fetch_min_prices_batch(products_api, batch_asin_values)
                self.stdout.write(f"  Pricing results: {len([r for r in pricing_results.values() if r is not None])}/{len(batch_asin_values)} successful")
                
                # Step 3: Merge and save
                for asin_value in batch_asin_values:
                    asin_id = batch_id_map.get(asin_value)
                    if not asin_id:
                        continue
                    
                    catalog = catalog_results.get(asin_value)
                    pricing = pricing_results.get(asin_value)
                    
                    merged = merge_listing_data(asin_value, catalog, pricing)
                    merged['fetched_at'] = timezone.now().isoformat()
                    
                    Asin.objects.filter(id=asin_id).update(
                        min_listing_data=merged
                    )
                
                # Update progress
                task_obj.processed_asins = min(
                    batch_start + BATCH_SIZE, len(asins)
                )
                task_obj.save()
                
                # Rate limiting
                if batch_start + BATCH_SIZE < len(asins):
                    import time
                    time.sleep(10)
            
            task_obj.status = 'SUCCESS'
            task_obj.finished_at = timezone.now()
            task_obj.save()
            self.stdout.write("Task completed successfully!")
            
            # Refresh from DB
            task_obj.refresh_from_db()
            
            self.stdout.write("\n" + "=" * 80)
            self.stdout.write("Task completed!")
            self.stdout.write("=" * 80)
            self.stdout.write(f"Status: {task_obj.status}")
            self.stdout.write(f"Processed: {task_obj.processed_asins}/{task_obj.total_asins}")
            self.stdout.write(f"Percentage: {task_obj.percentage}%")
            if task_obj.error_message:
                self.stdout.write(self.style.ERROR(f"Error: {task_obj.error_message}"))
            
            # Check results
            self.stdout.write("\nChecking results...")
            for asin in test_asins:
                asin.refresh_from_db()
                if asin.min_listing_data:
                    min_price = asin.min_listing_data.get('min_price')
                    title = asin.min_listing_data.get('title')
                    self.stdout.write(f"  {asin.value}: min_price={min_price}, title={title[:50] if title else 'None'}...")
                else:
                    self.stdout.write(f"  {asin.value}: No min_listing_data")
        
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\nERROR: Task failed with exception: {e}"))
            import traceback
            self.stdout.write(traceback.format_exc())
            task_obj.refresh_from_db()
            if task_obj.status != 'CANCELLED':
                task_obj.status = 'FAILURE'
                task_obj.error_message = str(e)
                task_obj.finished_at = timezone.now()
                task_obj.save()

"""
Management command to migrate 'contains' text field to BuildComponent M2M relationship.

Usage:
    python manage.py migrate_contains_to_m2m

This command:
1. Finds all Asin records with non-empty 'contains' field
2. Parses the comma-separated ASIN values
3. Counts duplicates to determine quantity
4. Creates BuildComponent records
5. Rolls back everything if any referenced ASIN doesn't exist
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from collections import Counter
from apps.listings.models import Asin, BuildComponent


class Command(BaseCommand):
    help = 'Migrate contains text field to BuildComponent M2M relationship'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN - No changes will be made'))
        
        # Get all Asin records with non-empty contains field
        asins_with_contains = Asin.objects.exclude(contains='').exclude(contains__isnull=True)
        
        if not asins_with_contains.exists():
            self.stdout.write(self.style.SUCCESS('No Asin records with contains field found. Nothing to migrate.'))
            return
        
        self.stdout.write(f'Found {asins_with_contains.count()} Asin records with contains field')
        
        # Collect all data first to validate before making changes
        migration_data = []
        missing_asins = set()
        
        for asin in asins_with_contains:
            # Parse contains field (comma-separated, possibly with spaces)
            contains_raw = asin.contains.strip()
            if not contains_raw:
                continue
            
            # Split by comma and strip whitespace
            component_values = [v.strip() for v in contains_raw.split(',') if v.strip()]
            
            if not component_values:
                continue
            
            # Count occurrences of each ASIN value
            component_counts = Counter(component_values)
            
            self.stdout.write(f'\nProcessing: {asin.value} ({asin.name})')
            self.stdout.write(f'  Contains: {contains_raw}')
            
            for component_value, quantity in component_counts.items():
                # Look up the component Asin
                try:
                    component_asin = Asin.objects.get(value__iexact=component_value)
                    migration_data.append({
                        'parent': asin,
                        'component': component_asin,
                        'quantity': quantity,
                    })
                    self.stdout.write(f'  → {component_value} x{quantity} (Found: ID {component_asin.id})')
                except Asin.DoesNotExist:
                    missing_asins.add(component_value)
                    self.stdout.write(self.style.ERROR(f'  → {component_value} x{quantity} (NOT FOUND!)'))
        
        # Check for missing ASINs
        if missing_asins:
            self.stdout.write('')
            self.stdout.write(self.style.ERROR('=' * 60))
            self.stdout.write(self.style.ERROR('MIGRATION ABORTED: The following ASINs do not exist:'))
            for missing in sorted(missing_asins):
                self.stdout.write(self.style.ERROR(f'  - {missing}'))
            self.stdout.write(self.style.ERROR('=' * 60))
            self.stdout.write('')
            self.stdout.write('Please create these ASINs first, then run this command again.')
            raise CommandError('Migration aborted due to missing ASINs')
        
        if not migration_data:
            self.stdout.write(self.style.SUCCESS('No valid component relationships found. Nothing to migrate.'))
            return
        
        self.stdout.write('')
        self.stdout.write(f'Total BuildComponent records to create: {len(migration_data)}')
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN complete. No changes were made.'))
            return
        
        # Execute migration in atomic transaction
        try:
            with transaction.atomic():
                created_count = 0
                updated_count = 0
                
                for data in migration_data:
                    obj, created = BuildComponent.objects.update_or_create(
                        parent=data['parent'],
                        component=data['component'],
                        defaults={'quantity': data['quantity']}
                    )
                    if created:
                        created_count += 1
                    else:
                        updated_count += 1
                
                self.stdout.write('')
                self.stdout.write(self.style.SUCCESS('=' * 60))
                self.stdout.write(self.style.SUCCESS('MIGRATION COMPLETE'))
                self.stdout.write(self.style.SUCCESS(f'  Created: {created_count} BuildComponent records'))
                self.stdout.write(self.style.SUCCESS(f'  Updated: {updated_count} BuildComponent records'))
                self.stdout.write(self.style.SUCCESS('=' * 60))
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Migration failed: {e}'))
            raise CommandError(f'Migration failed: {e}')

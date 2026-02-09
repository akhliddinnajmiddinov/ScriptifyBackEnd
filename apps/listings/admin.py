from django.contrib import admin
from .models import Listing, Shelf, InventoryVendor, Asin, BuildComponent, InventoryColor


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ['id', 'listing_url', 'price', 'timestamp', 'tracking_number']
    list_filter = ['timestamp']
    search_fields = ['listing_url', 'tracking_number']


@admin.register(Shelf)
class ShelfAdmin(admin.ModelAdmin):
    list_display = ['id', 'name']
    ordering = ['id']
    search_fields = ['name']


@admin.register(InventoryVendor)
class InventoryVendorAdmin(admin.ModelAdmin):
    list_display = ['id', 'name']
    ordering = ['id']
    search_fields = ['name']


class BuildComponentInline(admin.TabularInline):
    """Inline admin for components of a build item."""
    model = BuildComponent
    fk_name = 'parent'
    extra = 1
    autocomplete_fields = ['component']
    verbose_name = 'Component'
    verbose_name_plural = 'Components'


@admin.register(Asin)
class AsinAdmin(admin.ModelAdmin):
    list_display = ['id', 'value', 'name', 'ean', 'vendor', 'amount', 'shelf', 'component_count']
    list_filter = ['vendor']
    search_fields = ['value', 'name', 'ean', 'vendor', 'shelf', 'contains']
    inlines = [BuildComponentInline]
    
    def component_count(self, obj):
        """Display number of components for this item."""
        return obj.component_set.count()
    component_count.short_description = 'Components'


@admin.register(BuildComponent)
class BuildComponentAdmin(admin.ModelAdmin):
    list_display = ['id', 'parent', 'component', 'quantity']
    list_filter = ['parent']
    search_fields = ['parent__value', 'parent__name', 'component__value', 'component__name']
    autocomplete_fields = ['parent', 'component']


@admin.register(InventoryColor)
class InventoryColorAdmin(admin.ModelAdmin):
    list_display = ['id', 'pattern', 'color', 'created_at', 'updated_at']
    list_filter = ['created_at', 'updated_at']
    search_fields = ['pattern']
    ordering = ['pattern']
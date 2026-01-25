from django.contrib import admin
from .models import Listing, Shelf, InventoryVendor, Asin


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ['id', 'listing_url', 'price', 'timestamp', 'tracking_number']
    list_filter = ['timestamp']
    search_fields = ['listing_url', 'tracking_number']


@admin.register(Shelf)
class ShelfAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'order']
    list_editable = ['order']
    ordering = ['order', 'id']
    search_fields = ['name']


@admin.register(InventoryVendor)
class InventoryVendorAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'order']
    list_editable = ['order']
    ordering = ['order', 'id']
    search_fields = ['name']


@admin.register(Asin)
class AsinAdmin(admin.ModelAdmin):
    list_display = ['id', 'value', 'name', 'ean', 'vendor', 'amount', 'multiple', 'parent']
    list_filter = ['multiple', 'vendor']
    search_fields = ['value', 'name', 'ean']
    filter_horizontal = ['shelf']
    raw_id_fields = ['vendor', 'parent']

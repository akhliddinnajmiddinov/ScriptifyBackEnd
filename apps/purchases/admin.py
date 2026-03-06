from django.contrib import admin
from .models import Purchases


@admin.register(Purchases)
class PurchasesAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'platform',
        'external_id',
        'product_title',
        'order_status',
        'approved_status',
        'purchased_at',
        'updated_at',
        'listing'
    ]
    list_filter = ['platform', 'order_status', 'approved_status', 'purchased_at', 'updated_at']
    search_fields = ['external_id', 'product_title', 'description']
    readonly_fields = ['created_at', 'modified_at']
    ordering = ['-updated_at', '-id']

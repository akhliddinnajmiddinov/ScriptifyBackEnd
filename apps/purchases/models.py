from django.db import models
from listings.models import Listing


PLATFORM_CHOICES = [
    ('vinted', 'Vinted'),
    ('amazon', 'Amazon'),
    ('kleinanzeigen', 'Kleinanzeigen'),
    ('momox', 'Momox'),
]

ORDER_STATUS_CHOICES = [
    ('new', 'New'),
    ('pending', 'Pending'),
    ('processing', 'Processing'),
    ('shipped', 'Shipped'),
    ('delivered', 'Delivered'),
    ('completed', 'Completed'),
    ('cancelled', 'Cancelled'),
    ('returned', 'Returned'),
    ('refunded', 'Refunded'),
    ('uncompleted', 'Uncompleted'),
    ('waiting', 'Waiting'),
]

APPROVED_STATUS_CHOICES = [
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
]


class Purchases(models.Model):
    """
    Generic purchase order model that works across multiple platforms.
    Stores purchase/order data from various marketplaces (Vinted, Amazon, Kleinanzeigen, Momox, etc.)
    """
    
    # Platform identification
    platform = models.CharField(
        max_length=50,
        choices=PLATFORM_CHOICES,
        db_index=True,
        help_text="Platform source: vinted, amazon, kleinanzeigen, momox, etc."
    )
    
    # Core identifiers (platform-agnostic)
    external_id = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Platform-specific order/conversation ID"
    )
    
    # Seller/Vendor information (generic)
    seller_info = models.JSONField(
        null=True,
        blank=True,
        help_text="Platform-specific seller information (id, name, username, etc.)"
    )
    
    # Order status (normalized across platforms)
    order_status = models.CharField(
        max_length=50,
        choices=ORDER_STATUS_CHOICES,
        null=True,
        blank=True,
        db_index=True
    )
    
    # Product information
    product_title = models.CharField(max_length=500)
    description = models.TextField(null=True, blank=True)
    primary_listing_url = models.URLField(
        null=True,
        blank=True,
        help_text="Primary listing URL (first item's URL for bundles)"
    )
    
    # Dates
    purchased_at = models.DateTimeField(null=True, blank=True, db_index=True)
    updated_at = models.DateTimeField(null=True, blank=True, db_index=True)
    
    # Pricing (generic structure)
    item_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    item_price_currency = models.CharField(max_length=10, null=True, blank=True)
    
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    purchase_price_currency = models.CharField(max_length=10, null=True, blank=True)
    
    service_fee = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    service_fee_currency = models.CharField(max_length=10, null=True, blank=True)
    
    shipment_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    shipment_price_currency = models.CharField(max_length=10, null=True, blank=True)
    
    total_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    total_price_currency = models.CharField(max_length=10, null=True, blank=True)
    
    refunded_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    refunded_amount_currency = models.CharField(max_length=10, null=True, blank=True)
    
    # Shipment/Tracking (generic)
    shipment_id = models.CharField(max_length=255, null=True, blank=True)
    tracking_code = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
        help_text="Tracking number for matching with Listing.tracking_number"
    )
    tracking_url = models.URLField(null=True, blank=True)
    
    # Items (JSON array - platform-agnostic structure)
    items = models.JSONField(
        null=True,
        blank=True,
        help_text="Array of items: [{'title': '...', 'url': '...', 'price': '...', 'currency': '...', 'image_urls': [...]}]"
    )
    
    # Listing relationship (generic)
    listing = models.ForeignKey(
        Listing,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='purchases',
        db_index=True
    )
    
    # Approval workflow (generic)
    approved_status = models.CharField(
        max_length=20,
        choices=APPROVED_STATUS_CHOICES,
        null=True,
        blank=True,
        db_index=True
    )
    approved_rejected_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True
    )
    decision_note = models.TextField(
        null=True,
        blank=True,
        help_text="Optional note written by the reviewer when approving or rejecting"
    )
    
    # Platform-specific data (flexible JSON storage)
    platform_data = models.JSONField(
        null=True,
        blank=True,
        help_text="Platform-specific fields that don't fit in generic structure"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    
    # Platform-specific properties (computed)
    @property
    def chat_link(self):
        """Build platform-specific chat/conversation link"""
        from .adapters import get_adapter
        try:
            adapter = get_adapter(self.platform)
            return adapter.get_chat_link(self.external_id)
        except (ValueError, AttributeError):
            return None
    
    def __str__(self):
        return f"{self.platform.upper()} Purchase {self.external_id} - {self.product_title}"
    
    class Meta:
        db_table = 'purchases'
        ordering = ['-updated_at', '-id']
        unique_together = [['platform', 'external_id']]
        permissions = [
            ("can_approve_purchase",           "Approve / reject purchase"),
            ("can_import_purchases_from_file", "Import purchases from file"),
        ]
        indexes = [
            models.Index(fields=['platform', 'external_id'], name='purchases_platform_id_idx'),
            models.Index(fields=['platform'], name='purchases_platform_idx'),
            models.Index(fields=['order_status'], name='purchases_order_status_idx'),
            models.Index(fields=['approved_status'], name='purchases_approved_status_idx'),
            models.Index(fields=['purchased_at'], name='purchases_purchased_at_idx'),
            models.Index(fields=['updated_at'], name='purchases_updated_at_idx'),
            models.Index(fields=['tracking_code'], name='purchases_tracking_code_idx'),
            models.Index(fields=['listing'], name='purchases_listing_idx'),
        ]

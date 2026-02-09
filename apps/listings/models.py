from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
import os
import json
from datetime import datetime

User = get_user_model()


class Listing(models.Model):
    """
    Listings data
    """
    listing_url = models.CharField(max_length=1000)
    picture_urls = models.JSONField(help_text="JSON array of image URLs: [\"url1\", \"url2\", ...]")
    price = models.FloatField()
    timestamp = models.DateTimeField()
    tracking_number = models.CharField(max_length=255, null=True, blank=True)
    
    def __str__(self):
        return f"{self.listing_url} - {self.price}"

    class Meta:
        ordering = ['-timestamp', '-id']
        managed = False
        db_table = 'listing'
        indexes = [
            models.Index(fields=['listing_url'], name='listing_url_idx'),
            models.Index(fields=['timestamp'], name='listing_timestamp_idx'),
            models.Index(fields=['price'], name='listing_price_idx'),
            models.Index(fields=['tracking_number'], name='listing_tracking_number_idx'),
            models.Index(fields=['timestamp', 'price'], name='listing_timestamp_price_idx'),
        ]


class Shelf(models.Model):
    """
    Shelf for inventory storage locations
    """
    name = models.CharField(max_length=255, unique=True)
    
    def __str__(self):
        return self.name
    
    class Meta:
        ordering = ['id']
        managed = False
        db_table = 'shelf'
        indexes = [
            models.Index(fields=['name'], name='shelf_name_idx'),
        ]


class InventoryVendor(models.Model):
    """
    Vendor for inventory items
    """
    name = models.CharField(max_length=255, unique=True)
    photo = models.ImageField(upload_to='inventory_vendors/', null=True, blank=True)
    
    def __str__(self):
        return self.name
    
    class Meta:
        ordering = ['id']
        managed = False
        db_table = 'inventory_vendor'
        indexes = [
            models.Index(fields=['name'], name='inventory_vendor_name_idx'),
        ]


class Asin(models.Model):
    """
    Asin model - serves as inventory item
    """
    value = models.CharField(max_length=255, null=True, blank=True, unique=True)
    name = models.CharField(max_length=255)
    
    # Inventory fields
    ean = models.CharField(max_length=255, null=True, blank=True, unique=True)
    vendor = models.CharField(max_length=255, blank=True, default='')
    amount = models.IntegerField(default=0)
    shelf = models.CharField(max_length=255, blank=True, default='')
    contains = models.CharField(max_length=500, blank=True, default='', help_text="Comma-separated ASIN values for child items")

    def __str__(self):
        return f"{self.value} - {self.name}"
    
    class Meta:
        ordering = ['-id']
        managed = False
        db_table = 'asin'
        indexes = [
            models.Index(fields=['value'], name='asin_value_idx'),
            models.Index(fields=['name'], name='asin_name_idx'),
            models.Index(fields=['ean'], name='asin_ean_idx'),
            models.Index(fields=['vendor'], name='asin_vendor_idx'),
            models.Index(fields=['amount'], name='asin_amount_idx'),
            models.Index(fields=['shelf'], name='asin_shelf_idx'),
            # Composite indexes for common query patterns
            models.Index(fields=['vendor', 'amount'], name='asin_vendor_amount_idx'),
            models.Index(fields=['shelf', 'amount'], name='asin_shelf_amount_idx'),
        ]


    def save(self, *args, **kwargs):
        if self.value == '':
            self.value = None
        if self.ean == '':
            self.ean = None
        super().save(*args, **kwargs)

class BuildComponent(models.Model):
    """
    Through table for self-referential M2M on Asin.
    Defines which components (and how many) are needed to build a parent item.
    """
    parent = models.ForeignKey(
        Asin,
        on_delete=models.CASCADE,
        related_name='component_set'
    )
    component = models.ForeignKey(
        Asin,
        on_delete=models.CASCADE,
        related_name='parent_set'
    )
    quantity = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.parent.value} contains {self.quantity}x {self.component.value}"

    class Meta:
        db_table = 'build_component'
        unique_together = ['parent', 'component']
        ordering = ['parent', 'component']
        indexes = [
            models.Index(fields=['parent'], name='build_comp_parent_idx'),
            models.Index(fields=['component'], name='build_comp_comp_idx'),
        ]


class ListingAsin(models.Model):
    """
    ListingAsin model
    """
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name='listings_asins', null=True, blank=True)
    asin = models.ForeignKey(Asin, on_delete=models.CASCADE, related_name='asins_listings', null=True, blank=True)
    amount = models.IntegerField()
    
    def __str__(self):
        return f"{self.listing.id} - {self.asin.value} - {self.amount}"
    
    class Meta:
        ordering = ['-id']
        managed = False
        db_table = 'listing_asin'
        indexes = [
            models.Index(fields=['listing', 'asin'], name='listing_asin_composite_idx'),
            models.Index(fields=['listing'], name='listing_asin_listing_idx'),
            models.Index(fields=['asin'], name='listing_asin_asin_idx'),
        ]


class BuildLog(models.Model):
    """
    Records a build action where components were consumed.
    """
    parent_item = models.ForeignKey(Asin, on_delete=models.CASCADE, related_name='build_logs')
    quantity = models.PositiveIntegerField()
    timestamp = models.DateTimeField(auto_now_add=True)
    is_reverted = models.BooleanField(default=False)

    def __str__(self):
        return f"Build {self.quantity}x {self.parent_item.value} at {self.timestamp}"

    class Meta:
        db_table = 'build_log'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['parent_item'], name='build_log_parent_idx'),
            models.Index(fields=['timestamp'], name='build_log_timestamp_idx'),
            models.Index(fields=['is_reverted'], name='build_log_reverted_idx'),
        ]


class BuildLogItem(models.Model):
    """
    Snapshot of components consumed for a specific build.
    """
    build_log = models.ForeignKey(BuildLog, on_delete=models.CASCADE, related_name='items')
    component = models.ForeignKey(Asin, on_delete=models.CASCADE)
    quantity_consumed = models.PositiveIntegerField()

    def __str__(self):
        return f"{self.quantity_consumed}x {self.component.value} for log {self.build_log.id}"

    class Meta:
        db_table = 'build_log_item'
        indexes = [
            models.Index(fields=['build_log'], name='build_log_item_log_idx'),
            models.Index(fields=['component'], name='build_log_item_comp_idx'),
        ]


class InventoryColor(models.Model):
    """
    Color patterns for inventory items.
    Maps color patterns (e.g., "magenta", "red") to hex color codes.
    """
    pattern = models.CharField(max_length=255, unique=True, help_text="Color pattern name (e.g., 'magenta', 'red', 'cyan')")
    color = models.CharField(max_length=7, help_text="Hex color code (e.g., '#FF00FF')")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.pattern} ({self.color})"
    
    class Meta:
        db_table = 'inventory_color'
        ordering = ['pattern']
        indexes = [
            models.Index(fields=['pattern'], name='inventory_color_pattern_idx'),
        ]
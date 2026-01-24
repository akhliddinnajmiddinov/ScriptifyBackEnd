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


class Asin(models.Model):
    """
    Asin model
    """
    value = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    

    def __str__(self):
        return f"{self.value} - {self.name}"
    
    class Meta:
        ordering = ['-id']
        managed = False
        db_table = 'asin'
        indexes = [
            models.Index(fields=['value'], name='asin_value_idx'),
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
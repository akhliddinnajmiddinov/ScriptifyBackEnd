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
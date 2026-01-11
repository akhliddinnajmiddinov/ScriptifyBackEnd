from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
import os
import json
from datetime import datetime

User = get_user_model()


class Vendor(models.Model):
    """
    Vendor model
    """
    vendor_name = models.CharField(max_length=255, unique=True)
    image = models.ImageField(upload_to='vendor_images/', null=True, blank=True)
    vendor_vat = models.CharField(max_length=255, null=True, blank=True)
    
    def save(self, *args, **kwargs):
        """Override save to ensure vendor_name is always uppercase."""
        if self.vendor_name:
            self.vendor_name = self.vendor_name.upper()
        super().save(*args, **kwargs)
    
    def __str__(self):
        return self.vendor_name
    
    class Meta:
        ordering = ['vendor_name', '-id']

class Transaction(models.Model):
    """
    Transactions model
    """
    transaction_id = models.CharField(max_length=255)
    transaction_date = models.DateTimeField()
    amount = models.FloatField()
    currency = models.CharField(max_length=255)
    
    types = [
        ('RECEIVED', 'Received'),
        ('PAID', 'Paid')
    ]

    type = models.CharField(max_length=20, choices=types)

    STATUS_CHOICES = [
        ("COMPLETED", "Completed"),
        ("REFUNDED", "Refunded"),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, null=True, blank=True)

    transaction_from = models.CharField(max_length=255)
    transaction_to = models.CharField(max_length=255)
    
    def save(self, *args, **kwargs):
        """Override save to ensure transaction_from and transaction_to are always uppercase."""
        if self.transaction_from:
            self.transaction_from = self.transaction_from.upper()
        if self.transaction_to:
            self.transaction_to = self.transaction_to.upper()
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['-transaction_date', '-id']
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
import os
import json
from datetime import datetime

User = get_user_model()

CELERY_STATUS_CHOICES = [
    ('PENDING', 'Pending'),
    ('RECEIVED', 'Received'),
    ('STARTED', 'Started'),
    ('SUCCESS', 'Success'),
    ('FAILURE', 'Failure'),
    ('RETRY', 'Retry'),
    ('REVOKED', 'Revoked'),
]


class Script(models.Model):
    """
    Represents a reusable script/task that can be run multiple times.
    Stores metadata about the script including its input/output schemas and celery task name.
    """
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True, null=True)
    pic = models.ImageField(blank=True, null=True)
    # Celery task name - e.g., 'scripts.tasks.scrape_brand'
    celery_task = models.CharField(max_length=255)
    
    # JSON Schema for input form generation
    input_schema = models.JSONField(help_text="JSON Schema for generating frontend form")
    
    # JSON Schema for output display
    output_schema = models.JSONField(help_text="JSON Schema for displaying results")
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name


class Run(models.Model):
    """
    Represents a single execution of a script.
    Tracks input data, output results, logs, and execution status.
    """
    id = models.AutoField(primary_key=True)
    script = models.ForeignKey(Script, on_delete=models.CASCADE, related_name='runs')
    
    # Execution metadata
    started_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    
    status = models.CharField(max_length=20, choices=CELERY_STATUS_CHOICES, default='PENDING')
    celery_task_id = models.CharField(max_length=255, blank=True, null=True, unique=True)
    
    # Input data (captured from script input_schema)
    input_data = models.JSONField()
    input_file_path = models.TextField(blank=True, null=True)
    
    # Output results (captured from script output_schema)
    result_data = models.JSONField(null=True, blank=True)
    
    # File paths for logs and results
    logs_file_path = models.CharField(max_length=500, blank=True)
    result_file_path = models.CharField(max_length=500, blank=True)
    
    # Error information
    error_message = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-started_at']
    
    def __str__(self):
        return f"{self.script.name} - {self.id} ({self.status})"
    
    def get_duration(self):
        """Calculate run duration in seconds"""
        if self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None
    
    def is_running(self):
        return self.status in ['PENDING', 'RECEIVED', 'STARTED', 'RETRY']
    
    def is_finished(self):
        return self.status in ['SUCCESS', 'FAILURE', 'REVOKED']

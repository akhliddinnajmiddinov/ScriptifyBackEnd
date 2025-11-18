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
    pic = models.ImageField(upload_to="script_pics", blank=True, null=True)
    # Celery task name - e.g., 'scripts.tasks.scrape_brand'
    celery_task = models.CharField(max_length=255)
    
    # JSON Schema for input form generation
    input_schema = models.JSONField(help_text="JSON Schema for generating frontend form")
    
    # JSON Schema for output display
    output_schema = models.JSONField(help_text="JSON Schema for displaying results")
    
    cookies_file = models.FileField(upload_to="cookies/", null=True, blank=True)

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
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    
    status = models.CharField(max_length=20, choices=CELERY_STATUS_CHOICES, default='PENDING')
    celery_task_id = models.CharField(max_length=255, blank=True, null=True, unique=True)
    
    # Input data (captured from script input_schema)
    input_data = models.JSONField()
    input_file_paths = models.JSONField(blank=True, null=True)
    
    input_schema_snapshot  = models.JSONField(null=True, blank=True, help_text="input_schema at the time of run creation")
    output_schema_snapshot = models.JSONField(null=True, blank=True, help_text="output_schema at the time of run creation")

    # File paths for logs and results
    logs_file = models.FileField(upload_to="runs/logs/", blank=True, null=True)
    result_file = models.FileField(upload_to="runs/results/", blank=True, null=True)
    
    # Error information
    error_message = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-id']
    
    def __str__(self):
        return f"{self.script.name} - {self.id} ({self.status})"
    
    def get_duration(self):
        """Calculate run duration in seconds"""
        if self.finished_at and self.started_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None
    
    def is_running(self):
        return self.status in ['PENDING', 'RECEIVED', 'STARTED', 'RETRY']
    
    def is_finished(self):
        return self.status in ['SUCCESS', 'FAILURE', 'REVOKED']

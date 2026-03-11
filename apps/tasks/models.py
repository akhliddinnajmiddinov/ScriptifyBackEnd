from django.db import models
from django.contrib.auth import get_user_model
from django.utils.text import slugify

User = get_user_model()

TASK_STATUS_CHOICES = [
    ('PENDING', 'Pending'),
    ('RUNNING', 'Running'),
    ('SUCCESS', 'Success'),
    ('FAILURE', 'Failure'),
    ('CANCELLED', 'Cancelled'),
]


class Task(models.Model):
    """
    Represents a reusable task that can be run multiple times.
    Similar to Script but simpler - just name, celery task, and cookies file.
    """
    name = models.CharField(
        max_length=255,
        unique=True,
        help_text="e.g., 'Min Price Fetching', 'Vinted Conversation Scraping'"
    )
    slug = models.SlugField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="URL-friendly identifier (e.g., 'min-price-fetching', 'vinted-conversation-scraping')"
    )
    description = models.TextField(blank=True, null=True)
    
    # Celery task name - e.g., 'tasks.tasks.fetch_min_prices_task'
    celery_task = models.CharField(max_length=255)
    
    # Cookies file for tasks that need it (like vinted scraping)
    cookies_file = models.FileField(upload_to="task_cookies/", null=True, blank=True)

    # Concurrency control
    allow_concurrent_runs = models.BooleanField(
        default=False,
        help_text="Allow multiple runs of this task to execute at the same time."
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_active'], name='task_is_active_idx'),
            models.Index(fields=['name'], name='task_name_idx'),
            models.Index(fields=['slug'], name='task_slug_idx'),
        ]
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        # Auto-generate slug from name if not provided
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class TaskRun(models.Model):
    """
    Represents a single execution of a task.
    Tracks execution status, input data, and progress (flexible JSON structure).
    """
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='runs')
    
    # Execution metadata
    started_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    title = models.CharField(max_length=255, null=True, blank=True) # Added title field
    
    status = models.CharField(
        max_length=20,
        choices=TASK_STATUS_CHOICES,
        default='PENDING',
        db_index=True
    )
    celery_task_id = models.CharField(max_length=255, blank=True, null=True)
    
    # Input data (task-specific configuration)
    # Examples:
    # Vinted scraping: {"days_to_fetch": 7}
    # Min price: {} (no input needed)
    input_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Task-specific input parameters"
    )
    
    # Progress tracking (flexible JSON - different structure per task type)
    # Examples:
    # Min price: {"total_asins": 100, "processed_asins": 50}
    # Vinted: {"days_fetched": 7, "conversations_processed": 25, "total_conversations": 50}
    progress = models.JSONField(
        null=True,
        blank=True,
        default=dict,
        help_text="Task-specific progress data"
    )
    
    # Generic run detail text for any status
    detail = models.TextField(blank=True, default='')
    
    # Log file for this run
    logs_file = models.FileField(upload_to="taskruns/logs/", blank=True, null=True)
    
    class Meta:
        ordering = ['-id']
        indexes = [
            models.Index(fields=['status'], name='taskrun_status_idx'),
            models.Index(fields=['task', 'status'], name='taskrun_task_status_idx'),
            models.Index(fields=['started_at'], name='taskrun_started_at_idx'),
        ]
    
    def __str__(self):
        return f"{self.task.name} - Run #{self.id} ({self.status})"
    
    def is_running(self):
        return self.status in ['PENDING', 'RUNNING']

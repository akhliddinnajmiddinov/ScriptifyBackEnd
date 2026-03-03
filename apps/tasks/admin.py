from django.contrib import admin
from .models import Task, TaskRun


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'slug', 'celery_task', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'slug', 'description')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'slug', 'description', 'is_active')
        }),
        ('Task Configuration', {
            'fields': ('celery_task', 'cookies_file')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(TaskRun)
class TaskRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'task', 'status', 'started_by', 'started_at', 'finished_at')
    list_filter = ('status', 'started_at', 'task')
    search_fields = ('task__name', 'task__slug', 'started_by__email', 'celery_task_id')
    readonly_fields = ('started_at', 'finished_at', 'celery_task_id')
    
    fieldsets = (
        ('Execution Info', {
            'fields': ('task', 'started_by', 'status', 'celery_task_id')
        }),
        ('Input Data', {
            'fields': ('input_data',)
        }),
        ('Progress', {
            'fields': ('progress',)
        }),
        ('Timing', {
            'fields': ('started_at', 'finished_at')
        }),
        ('Error Information', {
            'fields': ('error_message',),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        return False  # TaskRuns are created via API only

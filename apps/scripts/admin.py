from django.contrib import admin
from .models import Script, Run


@admin.register(Script)
class ScriptAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'celery_task', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'description')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'pic', 'is_active')
        }),
        ('Task Configuration', {
            'fields': ('celery_task', 'input_schema', 'output_schema', 'cookies_file')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Run)
class RunAdmin(admin.ModelAdmin):
    list_display = ('id', 'script', 'status', 'started_by', 'started_at', 'finished_at')
    list_filter = ('status', 'started_at', 'script')
    search_fields = ('script__name', 'started_by__email', 'celery_task_id')
    readonly_fields = ('started_at', 'finished_at', 'celery_task_id', 'get_duration')
    
    fieldsets = (
        ('Execution Info', {
            'fields': ('script', 'started_by', 'status', 'celery_task_id')
        }),
        ('Timing', {
            'fields': ('started_at', 'finished_at', 'get_duration')
        }),
        ('Input/Output', {
            'fields': ('input_data', 'result_data'),
            'classes': ('collapse',)
        }),
        ('File Paths', {
            'fields': ('logs_file_path', 'result_file_path'),
            'classes': ('collapse',)
        }),
        ('Error Information', {
            'fields': ('error_message',),
            'classes': ('collapse',)
        }),
    )
    
    def get_duration(self, obj):
        duration = obj.get_duration()
        return f"{duration} seconds" if duration else "N/A"
    get_duration.short_description = "Duration"
    
    def has_add_permission(self, request):
        return False  # Runs are created via API only

from rest_framework import serializers
from .models import Task, TaskRun


class TaskSerializer(serializers.ModelSerializer):
    """Serializer for Task model"""
    
    class Meta:
        model = Task
        fields = [
            'id',
            'name',
            'slug',
            'description',
            'celery_task',
            'cookies_file',
            'allow_concurrent_runs',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']


class TaskRunSerializer(serializers.ModelSerializer):
    """Serializer for TaskRun model"""
    task = TaskSerializer(read_only=True)
    started_by_email = serializers.ReadOnlyField(source='started_by.email')
    
    class Meta:
        model = TaskRun
        fields = [
            'id',
            'task',
            'started_by',
            'started_by_email',
            'started_at',
            'finished_at',
            'status',
            'celery_task_id',
            'input_data',
            'progress',
            'detail',
            'logs_file',
            'title',
        ]
        read_only_fields = ['started_at', 'finished_at', 'celery_task_id', 'logs_file']


class TaskStartInputSerializer(serializers.Serializer):
    """
    Validates input_data for task start requests.
    Task-specific validation based on task slug.
    """
    input_data = serializers.DictField(required=False, allow_empty=True, default=dict)
    
    def validate(self, attrs):
        """
        Validate input_data based on the task slug.
        This is called with context containing the task.
        """
        task = self.context.get('task')
        input_data = attrs.get('input_data', {})
        
        if not task:
            return attrs
        
        # Task-specific validation
        if task.slug == 'vinted-conversation-scraping':
            # Validate days_to_fetch if provided
            if 'days_to_fetch' in input_data:
                days_to_fetch = input_data['days_to_fetch']
                if days_to_fetch is not None:
                    # Handle string numbers that might come from JSON (e.g., "7")
                    # But reject non-numeric strings
                    if isinstance(days_to_fetch, str):
                        try:
                            days_to_fetch = int(days_to_fetch)
                        except (ValueError, TypeError):
                            raise serializers.ValidationError({
                                'input_data': {
                                    'days_to_fetch': 'Must be a positive integer or null'
                                }
                            })
                    
                    # Must be a positive integer (reject floats, etc.)
                    if not isinstance(days_to_fetch, int):
                        raise serializers.ValidationError({
                            'input_data': {
                                'days_to_fetch': 'Must be a positive integer or null'
                            }
                        })
                    
                    if days_to_fetch <= 0:
                        raise serializers.ValidationError({
                            'input_data': {
                                'days_to_fetch': 'Must be a positive integer'
                            }
                        })
                    
                    # Update with validated integer
                    input_data['days_to_fetch'] = days_to_fetch
        elif task.slug == 'vinted-purchase-completion':
            if 'purchase_id' in input_data and input_data['purchase_id'] not in [None, ""]:
                try:
                    input_data['purchase_id'] = int(input_data['purchase_id'])
                except (TypeError, ValueError):
                    raise serializers.ValidationError({
                        'input_data': {
                            'purchase_id': 'Must be an integer'
                        }
                    })

        attrs['input_data'] = input_data
        return attrs

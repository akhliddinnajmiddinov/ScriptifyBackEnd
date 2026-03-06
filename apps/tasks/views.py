from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from .models import Task, TaskRun
from .serializers import TaskSerializer, TaskRunSerializer, TaskStartInputSerializer


class TaskViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for managing tasks.
    Provides read-only access to tasks and actions to start/status/cancel task runs.
    """
    queryset = Task.objects.filter(is_active=True)
    serializer_class = TaskSerializer
    lookup_field = 'slug'
    lookup_url_kwarg = 'slug'

    @action(detail=True, methods=['post'])
    def start(self, request, slug=None):
        """Start a new run of this task"""
        task = self.get_object()
        
        # Check if task already running
        running = TaskRun.objects.filter(
            task=task,
            status__in=['PENDING', 'RUNNING']
        ).first()
        
        if running:
            return Response(
                {
                    'error': f'A {task.name} task is already running.',
                    'run': TaskRunSerializer(running).data
                },
                status=status.HTTP_409_CONFLICT
            )
        
        # Validate input data
        input_serializer = TaskStartInputSerializer(
            data={'input_data': request.data.get('input_data', {})},
            context={'task': task}
        )
        input_serializer.is_valid(raise_exception=True)
        validated_input_data = input_serializer.validated_data['input_data']
        
        # Create new run with validated input data
        task_run = TaskRun.objects.create(
            task=task,
            started_by=request.user if request.user.is_authenticated else None,
            status='PENDING',
            input_data=validated_input_data
        )
        
        # Set descriptive title with ID
        task_run.title = f"{task.name} task #{task_run.id}"
        task_run.save(update_fields=['title'])
        
        # Dispatch Celery task
        try:
            # Dynamically import and call celery task function
            from importlib import import_module
            
            # Handle both full path (apps.tasks.tasks.fetch_vinted_conversations_task) and function name only (fetch_vinted_conversations_task)
            celery_task_path = task.celery_task
            if '.' not in celery_task_path:
                # If no dot, assume it's just the function name and construct the full path
                # Default module path for tasks in this app
                celery_task_path = f'tasks.tasks.{celery_task_path}'
            
            split_result = celery_task_path.rsplit('.', 1)
            
            if len(split_result) != 2:
                raise ValueError(f"Invalid celery_task format: '{task.celery_task}'. Expected format: 'module.path.function_name' or 'function_name'")
            
            module_path, func_name = split_result
            module = import_module(module_path)
            celery_func = getattr(module, func_name)
            
            celery_result = celery_func.delay(task_run_id=task_run.id)
            task_run.celery_task_id = celery_result.id
            task_run.save()
        except Exception as e:
            task_run.status = 'FAILURE'
            task_run.error_message = f'Failed to start: {str(e)}'
            task_run.finished_at = timezone.now()
            task_run.save()
            return Response(
                {'error': f'Failed to start task: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        return Response(TaskRunSerializer(task_run).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'])
    def status(self, request, slug=None):
        """Get status of the most recent run"""
        task = self.get_object()
        task_run = TaskRun.objects.filter(task=task).order_by('-id').first()
        
        if not task_run:
            return Response(
                {'error': f'No {task.name} task run found.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        return Response(TaskRunSerializer(task_run).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, slug=None):
        """Cancel running task"""
        task = self.get_object()
        task_run = TaskRun.objects.filter(
            task=task,
            status__in=['PENDING', 'RUNNING']
        ).first()
        
        if not task_run:
            return Response(
                {'error': f'No running {task.name} task found.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        task_run.status = 'CANCELLED'
        task_run.finished_at = timezone.now()
        task_run.save()
        
        # Revoke Celery task
        if task_run.celery_task_id:
            try:
                from scriptify_backend.celery import app as celery_app
                celery_app.control.revoke(task_run.celery_task_id, terminate=True)
            except Exception:
                pass  # Best effort
        
        return Response(TaskRunSerializer(task_run).data)

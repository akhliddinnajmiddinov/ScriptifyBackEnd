from django.db.models import Count, F, Q
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Task, TaskRun
from .serializers import TaskSerializer, TaskRunSerializer, TaskStartInputSerializer
from .services import create_task_run, delete_task_run, enqueue_task_run, reuse_task_run, task_has_running_run
from listings.filters import StandardPagination


class TaskViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for managing tasks.
    Provides read-only access to tasks and actions to start/status/cancel task runs.
    """
    queryset = Task.objects.filter(is_active=True)
    serializer_class = TaskSerializer
    lookup_field = 'slug'
    lookup_url_kwarg = 'slug'
    permission_classes = [permissions.IsAuthenticated]
    task_run_pagination_class = StandardPagination
    task_run_ordering_fields = {
        'id': 'id',
        'status': 'status',
        'started_at': 'started_at',
        'finished_at': 'finished_at',
        'title': 'title',
        'task_name': 'task__name',
    }

    def _validate_concurrency(self, task: Task):
        if not task.allow_concurrent_runs and task_has_running_run(task):
            running = TaskRun.objects.filter(
                task=task,
                status__in=['PENDING', 'RUNNING']
            ).order_by('-id').first()
            return Response(
                {
                    'error': f'A {task.name} task is already running.',
                    'run': TaskRunSerializer(running).data
                },
                status=status.HTTP_409_CONFLICT
            )
        return None

    def _validate_rerun_target(self, task_run: TaskRun):
        if task_run.status in ['PENDING', 'RUNNING']:
            return Response(
                {
                    'error': 'This task run is already queued or running.',
                    'run': TaskRunSerializer(task_run).data,
                },
                status=status.HTTP_409_CONFLICT,
            )
        return None

    def _validate_delete_target(self, task_run: TaskRun):
        if task_run.status in ['PENDING', 'RUNNING']:
            return Response(
                {
                    'error': 'Queued or running task runs cannot be deleted.',
                    'run': TaskRunSerializer(task_run).data,
                },
                status=status.HTTP_409_CONFLICT,
            )
        return None

    def _validate_cancel_target(self, task_run: TaskRun):
        if task_run.status not in ['PENDING', 'RUNNING']:
            return Response(
                {
                    'error': 'Only queued or running task runs can be cancelled.',
                    'run': TaskRunSerializer(task_run).data,
                },
                status=status.HTTP_409_CONFLICT,
            )
        return None

    def _cancel_task_run(self, task_run: TaskRun):
        task_run.status = 'CANCELLED'
        task_run.finished_at = timezone.now()
        task_run.detail = 'Task cancelled by user.'
        task_run.save(update_fields=['status', 'finished_at', 'detail'])

        if task_run.celery_task_id:
            try:
                from scriptify_backend.celery import app as celery_app
                celery_app.control.revoke(task_run.celery_task_id, terminate=True)
            except Exception:
                pass

        return task_run

    def _get_task_run_ordering(self):
        ordering = self.request.query_params.get('ordering', '-started_at,-id') or '-started_at,-id'
        ordering_fields = []
        for field in ordering.split(','):
            field = field.strip()
            raw_field = field[1:] if field.startswith('-') else field
            orm_field = self.task_run_ordering_fields.get(raw_field)
            if orm_field:
                if raw_field in ['started_at', 'finished_at']:
                    if field.startswith('-'):
                        ordering_fields.append(F(orm_field).desc(nulls_last=True))
                    else:
                        ordering_fields.append(F(orm_field).asc(nulls_last=True))
                else:
                    ordering_fields.append(f"-{orm_field}" if field.startswith('-') else orm_field)
        if not ordering_fields:
            ordering_fields = [F('started_at').desc(nulls_last=True), '-id']
        return ordering_fields

    def _parse_datetime_filter_value(self, value: str | None):
        if not value:
            return None

        parsed = parse_datetime(value)
        if not parsed:
            return None

        if timezone.is_aware(parsed):
            parsed = timezone.make_naive(parsed)

        return parsed

    def _apply_task_run_filters(self, queryset):
        params = self.request.query_params

        run_id = params.get('id')
        if run_id not in [None, '']:
            try:
                queryset = queryset.filter(id=int(run_id))
            except (TypeError, ValueError):
                return queryset.none()

        status_value = params.get('status')
        if status_value:
            queryset = queryset.filter(status=status_value)

        title = params.get('title')
        if title:
            queryset = queryset.filter(title__icontains=title)

        task_name = params.get('task_name')
        if task_name:
            queryset = queryset.filter(
                Q(task__name__icontains=task_name) |
                Q(task__slug__icontains=task_name)
            )

        started_by_email = params.get('started_by_email')
        if started_by_email:
            queryset = queryset.filter(started_by__email__icontains=started_by_email)

        detail = params.get('detail')
        if detail:
            queryset = queryset.filter(detail__icontains=detail)

        purchase_reference = params.get('purchase_reference')
        if purchase_reference:
            purchase_query = Q(input_data__purchase_external_id__icontains=purchase_reference)
            if str(purchase_reference).isdigit():
                purchase_query |= Q(input_data__purchase_id=int(purchase_reference))
            queryset = queryset.filter(purchase_query)

        started_at_start = self._parse_datetime_filter_value(params.get('started_at_start'))
        if started_at_start:
            queryset = queryset.filter(started_at__gte=started_at_start)

        started_at_end = self._parse_datetime_filter_value(params.get('started_at_end'))
        if started_at_end:
            queryset = queryset.filter(started_at__lte=started_at_end)

        finished_at_start = self._parse_datetime_filter_value(params.get('finished_at_start'))
        if finished_at_start:
            queryset = queryset.filter(finished_at__gte=finished_at_start)

        finished_at_end = self._parse_datetime_filter_value(params.get('finished_at_end'))
        if finished_at_end:
            queryset = queryset.filter(finished_at__lte=finished_at_end)

        return queryset

    def _get_task_run_queryset(self, task: Task):
        queryset = TaskRun.objects.filter(task=task).select_related('task', 'started_by')
        queryset = self._apply_task_run_filters(queryset)
        return queryset.order_by(*self._get_task_run_ordering())

    def _get_global_task_run_queryset(self):
        queryset = TaskRun.objects.select_related('task', 'started_by')
        task_slug = self.request.query_params.get('task_slug')
        if task_slug:
            queryset = queryset.filter(task__slug=task_slug)
        queryset = self._apply_task_run_filters(queryset)
        return queryset.order_by(*self._get_task_run_ordering())

    @action(detail=True, methods=['post'])
    def start(self, request, slug=None):
        """Start a new run of this task"""
        task = self.get_object()

        concurrency_error = self._validate_concurrency(task)
        if concurrency_error is not None:
            return concurrency_error
        
        # Validate input data
        input_serializer = TaskStartInputSerializer(
            data={'input_data': request.data.get('input_data', {})},
            context={'task': task}
        )
        input_serializer.is_valid(raise_exception=True)
        validated_input_data = input_serializer.validated_data['input_data']

        try:
            task_run = create_task_run(
                task=task,
                started_by=request.user if request.user.is_authenticated else None,
                input_data=validated_input_data,
            )
            enqueue_task_run(task_run)
        except Exception as e:
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

    @action(detail=True, methods=['get'])
    def summary(self, request, slug=None):
        """Get aggregate status counts for this task."""
        task = self.get_object()
        counts = TaskRun.objects.filter(task=task).aggregate(
            success_count=Count('id', filter=Q(status='SUCCESS')),
            failure_count=Count('id', filter=Q(status='FAILURE')),
            in_progress_count=Count('id', filter=Q(status__in=['PENDING', 'RUNNING'])),
        )
        return Response(counts)

    @action(detail=False, methods=['get'], url_path='summary')
    def global_summary(self, request):
        """Get aggregate status counts across all task runs."""
        counts = TaskRun.objects.aggregate(
            success_count=Count('id', filter=Q(status='SUCCESS')),
            failure_count=Count('id', filter=Q(status='FAILURE')),
            in_progress_count=Count('id', filter=Q(status__in=['PENDING', 'RUNNING'])),
        )
        return Response(counts)

    @action(detail=True, methods=['get'])
    def runs(self, request, slug=None):
        """List historical runs for this task."""
        task = self.get_object()
        queryset = self._get_task_run_queryset(task)
        paginator = self.task_run_pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        serializer = TaskRunSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @action(detail=False, methods=['get'], url_path='runs')
    def global_runs(self, request):
        """List historical runs across all tasks."""
        queryset = self._get_global_task_run_queryset()
        paginator = self.task_run_pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        serializer = TaskRunSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @action(detail=True, methods=['post'], url_path=r'runs/(?P<run_id>[^/.]+)/rerun')
    def rerun(self, request, slug=None, run_id=None):
        """Reuse an existing run row and enqueue it again."""
        task = self.get_object()
        concurrency_error = self._validate_concurrency(task)
        if concurrency_error is not None:
            return concurrency_error

        try:
            source_run = TaskRun.objects.get(task=task, id=run_id)
        except TaskRun.DoesNotExist:
            return Response(
                {'error': 'Task run not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        rerun_target_error = self._validate_rerun_target(source_run)
        if rerun_target_error is not None:
            return rerun_target_error

        try:
            task_run = reuse_task_run(
                task_run=source_run,
                started_by=request.user if request.user.is_authenticated else None,
            )
            enqueue_task_run(task_run)
        except Exception as exc:
            return Response(
                {'error': f'Failed to run task again: {exc}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(TaskRunSerializer(task_run).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path=r'runs/(?P<run_id>[^/.]+)/rerun')
    def global_rerun(self, request, run_id=None):
        """Reuse any existing task run row and enqueue it again."""
        try:
            source_run = TaskRun.objects.select_related('task').get(id=run_id)
        except TaskRun.DoesNotExist:
            return Response(
                {'error': 'Task run not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        rerun_target_error = self._validate_rerun_target(source_run)
        if rerun_target_error is not None:
            return rerun_target_error

        concurrency_error = self._validate_concurrency(source_run.task)
        if concurrency_error is not None:
            return concurrency_error

        try:
            task_run = reuse_task_run(
                task_run=source_run,
                started_by=request.user if request.user.is_authenticated else None,
            )
            enqueue_task_run(task_run)
        except Exception as exc:
            return Response(
                {'error': f'Failed to run task again: {exc}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(TaskRunSerializer(task_run).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['delete'], url_path=r'runs/(?P<run_id>[^/.]+)')
    def delete_run(self, request, slug=None, run_id=None):
        task = self.get_object()
        try:
            task_run = TaskRun.objects.get(task=task, id=run_id)
        except TaskRun.DoesNotExist:
            return Response(
                {'error': 'Task run not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        delete_target_error = self._validate_delete_target(task_run)
        if delete_target_error is not None:
            return delete_target_error

        delete_task_run(task_run)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path=r'runs/(?P<run_id>[^/.]+)/cancel')
    def cancel_run(self, request, slug=None, run_id=None):
        task = self.get_object()
        try:
            task_run = TaskRun.objects.get(task=task, id=run_id)
        except TaskRun.DoesNotExist:
            return Response(
                {'error': 'Task run not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        cancel_target_error = self._validate_cancel_target(task_run)
        if cancel_target_error is not None:
            return cancel_target_error

        return Response(TaskRunSerializer(self._cancel_task_run(task_run)).data)

    @action(detail=False, methods=['delete'], url_path=r'runs/(?P<run_id>[^/.]+)')
    def global_delete_run(self, request, run_id=None):
        try:
            task_run = TaskRun.objects.get(id=run_id)
        except TaskRun.DoesNotExist:
            return Response(
                {'error': 'Task run not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        delete_target_error = self._validate_delete_target(task_run)
        if delete_target_error is not None:
            return delete_target_error

        delete_task_run(task_run)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['post'], url_path=r'runs/(?P<run_id>[^/.]+)/cancel')
    def global_cancel_run(self, request, run_id=None):
        try:
            task_run = TaskRun.objects.get(id=run_id)
        except TaskRun.DoesNotExist:
            return Response(
                {'error': 'Task run not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        cancel_target_error = self._validate_cancel_target(task_run)
        if cancel_target_error is not None:
            return cancel_target_error

        return Response(TaskRunSerializer(self._cancel_task_run(task_run)).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, slug=None):
        """Cancel running task"""
        task = self.get_object()
        task_run = TaskRun.objects.filter(
            task=task,
            status__in=['PENDING', 'RUNNING']
        ).order_by('-id').first()
        
        if not task_run:
            return Response(
                {'error': f'No running {task.name} task found.'},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response(TaskRunSerializer(self._cancel_task_run(task_run)).data)

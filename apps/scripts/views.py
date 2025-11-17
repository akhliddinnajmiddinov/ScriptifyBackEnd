from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.renderers import JSONRenderer
from django.shortcuts import get_object_or_404
from django.utils import timezone
from .renderers import EventStreamRenderer
from django.http import StreamingHttpResponse
from django.core.files.base import ContentFile
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes, OpenApiResponse
from rest_framework.pagination import PageNumberPagination
from drf_spectacular.types import OpenApiTypes
from .models import Script, Run
from .serializers import ScriptSerializer, RunSerializer, RunCreateSerializer, ScriptStatsSerializer
from .tasks import execute_script_task, stream_logs
from django_eventstream import send_event
from .filters import RunFilter
from django.core.files.storage import default_storage
from django.http import HttpResponse, FileResponse
import os
import json
import time


class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

class ScriptViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Script.objects.filter(is_active=True)
    serializer_class = ScriptSerializer
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="scripts_list",
        description="List all active scripts with their configurations",
        tags=["Scripts"],
        responses=ScriptSerializer(many=True),  # Class, not instance
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        operation_id="scripts_retrieve",
        description="Get detailed information about a specific script including input/output schemas",
        tags=["Scripts"],
        responses=ScriptSerializer,  # Class, not instance
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        operation_id="scripts_stats_list",
        description="Get aggregated statistics for all scripts (total runs, success rate, average execution time)",
        tags=["Scripts"],
        responses=ScriptStatsSerializer(many=True),
    )
    @action(detail=False, methods=['get'], url_path='stats')
    def stats_list(self, request):
        scripts = self.get_queryset()
        serializer = ScriptStatsSerializer(scripts, many=True)
        return Response(serializer.data)

    @extend_schema(
        operation_id="scripts_stats_retrieve",
        description="Get statistics for a specific script (total runs, success rate, average execution time)",
        tags=["Scripts"],
        responses=ScriptStatsSerializer,
    )
    @action(detail=True, methods=['get'], url_path='stats')
    def stats_detail(self, request, pk=None):
        script = self.get_object()
        serializer = ScriptStatsSerializer(script)
        return Response(serializer.data)


class RunViewSet(viewsets.ModelViewSet):
    queryset = Run.objects.all()
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = RunFilter


    def get_serializer_class(self):
        if self.action == 'create':
            return RunCreateSerializer
        return RunSerializer

    def get_queryset(self):
        # Remove manual script_id filtering - now handled by django-filter
        return Run.objects.all().order_by('-started_at')
    
    @extend_schema(
        operation_id="runs_list",
        description="List all runs with filtering and pagination",
        tags=["Runs"],
        parameters=[
            OpenApiParameter('script_id', OpenApiTypes.INT, description='Filter by script ID'),
            OpenApiParameter('status', OpenApiTypes.STR, description='Filter by status'),
            OpenApiParameter('started_by', OpenApiTypes.INT, description='Filter by user ID'),
            OpenApiParameter('started_after', OpenApiTypes.DATETIME, description='Filter runs started after date'),
            OpenApiParameter('started_before', OpenApiTypes.DATETIME, description='Filter runs started before date'),
            OpenApiParameter('page', OpenApiTypes.INT, description='Page number'),
            OpenApiParameter('page_size', OpenApiTypes.INT, description='Results per page'),
        ],
        responses=RunSerializer(many=True),
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
        

    @extend_schema(
        operation_id="runs_retrieve",
        description="Get detailed information about a specific run including input data, status, and file paths",
        tags=["Runs"],
        responses=RunSerializer,
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        operation_id="runs_create",
        description="Create and immediately queue a new run for a script. Input data is validated against the script's input_schema.",
        tags=["Runs"],
        request=RunCreateSerializer,
        responses={
            201: RunSerializer,
            400: OpenApiResponse(description='Invalid input data'),
            500: OpenApiResponse(description='Task failed to start'),
        },
    )
    def create(self, request, *args, **kwargs):
        print(request.data)
        # Combine JSON + FILES into one dict for serializer
        mutable_data = request.data.copy()
        mutable_data.update(request.FILES)  # Crucial: include uploaded files

        serializer = self.get_serializer(data=mutable_data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        script = serializer.validated_data['script']
        input_data = serializer.validated_data['input_data']
        input_file_paths = serializer.validated_data.get('input_file_paths', {})

        # Create run
        run = Run.objects.create(
            script=script,
            started_by=request.user,
            input_data=input_data,
            input_file_paths=input_file_paths,  # Store file paths
            input_schema_snapshot=script.input_schema,
            output_schema_snapshot=script.output_schema,
            status='PENDING'
        )

        log_filename = f"run_{run.id}.log"
        result_filename = f"run_{run.id}.json"

        # Create empty files so Celery can append
        run.logs_file.save(log_filename, ContentFile(""))
        run.result_file.save(result_filename, ContentFile("{}"))

        run.save()

        try:
            task = execute_script_task.delay(
                script_id=script.id,
                run_id=run.id,
                input_data=input_data,
                input_file_paths=input_file_paths  # Pass file paths to Celery
            )
            channel = f"run-{run.id}"
            stream_logs.delay(run_id=run.id, log_path=run.logs_file.path, channel=channel)

            run.celery_task_id = task.id
            run.save()

            return Response(RunSerializer(run).data, status=status.HTTP_201_CREATED)

        except Exception as e:
            run.status = 'FAILURE'
            run.error_message = f"Task failed to start: {str(e)}"
            run.finished_at = timezone.now()
            run.save()
            return Response(
                {'error': f'Failed to start task: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
    @extend_schema(
        operation_id="runs_by_script",
        description="Get all runs for a specific script, ordered by start time (newest first)",
        tags=["Runs"],
        parameters=[
            OpenApiParameter(
                name='script_id',
                description='Script ID to filter runs',
                required=True,
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY
            ),
        ],
        responses=RunSerializer(many=True),
    )
    @action(detail=False, methods=['get'])
    def by_script(self, request):
        script_id = request.query_params.get('script_id')
        if not script_id:
            return Response(
                {'error': 'script_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        script = get_object_or_404(Script, id=script_id)
        runs = Run.objects.filter(script=script).order_by('-started_at')
        
        # Apply pagination
        page = self.paginate_queryset(runs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(runs, many=True)
        return Response(serializer.data)
        
    @extend_schema(
        operation_id="runs_abort",
        description="Abort a running celery task and mark the run as REVOKED.",
        tags=["Runs"],
        responses={
            200: RunSerializer,
            400: OpenApiResponse(description='Cannot abort finished run'),
        },
    )
    @action(detail=True, methods=['post'])
    def abort(self, request, pk=None):
        run = self.get_object()
        if run.is_finished():
            return Response(
                {'error': f'Cannot abort a {run.status} run'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if run.celery_task_id:
            from celery.result import AsyncResult
            AsyncResult(run.celery_task_id).revoke(terminate=True)

        run.status = 'REVOKED'
        run.finished_at = timezone.now()
        run.save()
        return Response(self.get_serializer(run).data)

    @extend_schema(
        operation_id="runs_get_logs",
        description="Get the complete log content for a specific run. Returns logs as plain text.",
        tags=["Runs"],
        responses=OpenApiTypes.STR,
    )
    @action(detail=True, methods=['get'], url_path='logs')
    def logs(self, request, pk=None):
        run = self.get_object()
        try:
            if os.path.exists(run.logs_file.path):
                with open(run.logs_file.path, 'r') as f:
                    logs = f.read()
                return Response({'logs': logs})
            return Response({'logs': ''})
        except Exception as e:
            return Response(
                {'error': f'Failed to read logs: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @extend_schema(
        operation_id="runs_stream_logs",
        description="Stream logs in real-time (SSE). "
                    "On connect: sends all existing logs. "
                    "While run is in progress: streams new lines. "
                    "On finish: sends final chunk + 'finished' signal.",
        tags=["Runs"],
    )
    @action(detail=True, methods=['get'], url_path='logs-stream')
    def logs_stream(self, request, pk=None):
        run = self.get_object()
        if not run.logs_file:
            return Response({'logs': ""}, status=404)
        log_path = run.logs_file.path
        channel = f"run-{run.id}"

        # === 1. Read existing logs ===
        existing_logs = ""
        if os.path.exists(log_path):
            try:
                with open(log_path, 'r', encoding='utf-8') as f:
                    existing_logs = f.read()
            except Exception as e:
                return Response({'error': str(e)}, status=500)

        run.refresh_from_db()
        finished = run.is_finished()

        # === 2. Return SSE URL + existing logs ===
        sse_url = f"events/?channel={channel}"

        return Response({
            'sse_url': sse_url,
            'channel': channel,
            'logs': existing_logs,  # ← HERE!
            'finished': finished
        })

    @extend_schema(
        operation_id="runs_get_results",
        description="Get the results for a specific run. Returns structured JSON data.",
        tags=["Runs"],
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=['get'], url_path='results')
    def results(self, request, pk=None):
        run = self.get_object()
        try:
            if os.path.exists(run.result_file.path):
                with open(run.result_file.path, 'r') as f:
                    results = json.load(f)
                    print("results")
                    print(str(results)[:100])
                return Response({"results": results, "status": run.status})
            return Response([])
        except Exception as e:
            return Response(
                {'error': f'Failed to read results: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['get'], url_path='download/(?P<field_name>[^/.]+)')
    def download_file(self, request, pk=None, field_name=None):
        run = self.get_object()
        file_paths = run.input_file_paths or '{}'
        file_path = file_paths.get(field_name)

        if not file_path or not default_storage.exists(file_path):
            return Response({'error': 'File not found'}, status=404)

        # Use FileResponse to efficiently stream large files
        file = default_storage.open(file_path, 'rb')
        response = FileResponse(file, content_type='application/octet-stream')
        response['Content-Disposition'] = f'attachment; filename="{os.path.basename(file_path)}"'
        return response
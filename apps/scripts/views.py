from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import JSONParser
from rest_framework.renderers import JSONRenderer
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.http import StreamingHttpResponse
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes, OpenApiResponse
from drf_spectacular.types import OpenApiTypes
from .models import Script, Run
from .serializers import ScriptSerializer, RunSerializer, RunCreateSerializer, ScriptStatsSerializer
from .tasks import execute_script_task
from django.contrib.auth.decorators import login_required
import os
import json
import time


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

    def get_serializer_class(self):
        if self.action == 'create':
            return RunCreateSerializer
        return RunSerializer

    def get_queryset(self):
        queryset = Run.objects.all()
        script_id = self.request.query_params.get('script_id')
        if script_id:
            queryset = queryset.filter(script_id=script_id)
        return queryset.order_by('-started_at')

    @extend_schema(
        operation_id="runs_list",
        description="List all runs ordered by start time (newest first). Filter by script_id using query parameter.",
        tags=["Runs"],
        parameters=[
            OpenApiParameter(
                name='script_id',
                description='Filter runs by script ID',
                required=False,
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY
            ),
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
        script_id = request.data.get('script_id')  # Better: from request.data
        print("SALAOMLAAR")
        if not script_id:
            return Response({'error': 'script_id is required'}, status=400)

        script = get_object_or_404(Script, id=script_id)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        input_data = serializer.validated_data['input_data']

        run = Run.objects.create(
            script=script,
            started_by=request.user,
            input_data=input_data,
            status='PENDING'
        )

        logs_dir = os.path.join('scripts_logs', str(script.id))
        result_dir = os.path.join('scripts_results', str(script.id))
        os.makedirs(logs_dir, exist_ok=True)
        os.makedirs(result_dir, exist_ok=True)

        run.logs_file_path = os.path.join(logs_dir, f'run_{run.id}.log')
        run.result_file_path = os.path.join(result_dir, f'run_{run.id}.json')
        run.save()

        try:
            task = execute_script_task.delay(
                script_id=script.id,
                run_id=run.id,
                input_data=input_data
            )
            run.celery_task_id = task.id
            run.save()
        except Exception as e:
            run.status = 'FAILURE'
            run.error_message = str(e)
            print(str(e))
            run.finished_at = timezone.now()
            run.save()
            return Response(
                {'error': f'Failed to start task: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(RunSerializer(run).data, status=status.HTTP_201_CREATED)

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
            if os.path.exists(run.logs_file_path):
                with open(run.logs_file_path, 'r') as f:
                    logs = f.read()
                return Response({'logs': logs})
            return Response({'logs': ''})
        except Exception as e:
            return Response(
                {'error': f'Failed to read logs: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )



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
            if os.path.exists(run.result_file_path):
                with open(run.result_file_path, 'r') as f:
                    results = json.load(f)
                return Response(results)
            return Response({'data': None})
        except Exception as e:
            return Response(
                {'error': f'Failed to read results: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

def log_generator():
    # Step 1: If run already finished → send full logs once
    run.refresh_from_db()
    if run.is_finished():
        if os.path.exists(log_path):
            try:
                with open(log_path, 'r', encoding='utf-8') as f:
                    full_logs = f.read()
                yield f"data: {json.dumps({'logs': full_logs, 'finished': True})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': f'Failed to read logs: {str(e)}'})})\n\n"
        else:
            yield f"data: {json.dumps({'logs': 'Log file not found', 'finished': True})}\n\n"
        return

    # Step 2: Run is in progress → send existing logs first
    existing_logs = ""
    if os.path.exists(log_path):
        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                existing_logs = f.read()
        except Exception as e:
            yield f"data: {json.dumps({'error': f'Initial read failed: {str(e)}'})})\n\n"
            return

    if existing_logs:
        yield f"data: {json.dumps({'logs': existing_logs})}\n\n"

    # Step 3: Start tailing from end of current file
    position = 0
    if os.path.exists(log_path):
        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                f.seek(0, os.SEEK_END)
                position = f.tell()
        except:
            position = 0

    # Step 4: Stream new lines until finish
    while True:
        run.refresh_from_db()
        if run.is_finished():
            # Send any final new lines
            try:
                with open(log_path, 'r', encoding='utf-8') as f:
                    f.seek(position)
                    final_chunk = f.read()
                    if final_chunk:
                        yield f"data: {json.dumps({'logs': final_chunk})}\n\n"
                    yield f"data: {json.dumps({'finished': True})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': f'Final chunk error: {str(e)}'})})\n\n"
            break

        try:
            if os.path.exists(log_path):
                with open(log_path, 'r', encoding='utf-8') as f:
                    f.seek(position)
                    new_data = f.read()
                    if new_data:
                        position = f.tell()
                        yield f"data: {json.dumps({'logs': new_data})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': f'Stream error: {str(e)}'})})\n\n"
            break

        time.sleep(1)


@extend_schema(
    operation_id="runs_stream_logs",
    description="Stream logs in real-time (SSE). "
                "On connect: sends all existing logs. "
                "While run is in progress: streams new lines. "
                "On finish: sends final chunk + 'finished' signal.",
    tags=["Runs"],
)

@login_required
def run_logs_stream(request, run_id):
    # same generator logic
    return StreamingHttpResponse(
        log_generator(),
        content_type="text/event-stream",
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        },
    )
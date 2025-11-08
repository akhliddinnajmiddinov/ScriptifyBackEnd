from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.openapi import OpenApiTypes
from .models import Script, Run
from django.contrib.auth import get_user_model

User = get_user_model()


class ScriptSerializer(serializers.ModelSerializer):
    class Meta:
        model = Script
        fields = ['id', 'name', 'description', 'celery_task', 'input_schema', 'output_schema', 'created_at', 'updated_at', 'is_active']
        read_only_fields = ['created_at', 'updated_at']


class RunSerializer(serializers.ModelSerializer):
    script_name = serializers.CharField(source='script.name', read_only=True)
    started_by_email = serializers.CharField(source='started_by.email', read_only=True)
    duration = serializers.SerializerMethodField()
    
    class Meta:
        model = Run
        fields = [
            'id', 'script', 'script_name', 'started_by', 'started_by_email',
            'started_at', 'finished_at', 'status', 'celery_task_id',
            'input_data', 'result_data', 'logs_file_path', 'result_file_path',
            'error_message', 'duration'
        ]
        read_only_fields = ['started_at', 'finished_at', 'celery_task_id', 'result_data', 'logs_file_path', 'result_file_path', 'error_message', 'duration']
    
    @extend_schema_field(OpenApiTypes.FLOAT)
    def get_duration(self, obj):
        return obj.get_duration()


class RunCreateSerializer(serializers.Serializer):
    """Serializer for creating new runs"""
    input_data = serializers.JSONField()
    
    def validate_input_data(self, value):
        """Validate input_data against script's input_schema if needed"""
        return value


class ScriptStatsSerializer(serializers.ModelSerializer):
    total_runs = serializers.SerializerMethodField()
    success_count = serializers.SerializerMethodField()
    failed_count = serializers.SerializerMethodField()
    success_rate = serializers.SerializerMethodField()
    average_time = serializers.SerializerMethodField()
    
    class Meta:
        model = Script
        fields = ['id', 'name', 'description', 'total_runs', 'success_count', 'failed_count', 'success_rate', 'average_time']
    
    @extend_schema_field(OpenApiTypes.INT)
    def get_total_runs(self, obj):
        return obj.runs.count()
    
    @extend_schema_field(OpenApiTypes.INT)
    def get_success_count(self, obj):
        return obj.runs.filter(status='SUCCESS').count()
    
    @extend_schema_field(OpenApiTypes.INT)
    def get_failed_count(self, obj):
        return obj.runs.filter(status='FAILURE').count()
    
    @extend_schema_field(OpenApiTypes.FLOAT)
    def get_success_rate(self, obj):
        total = obj.runs.count()
        if total == 0:
            return 0
        success = obj.runs.filter(status='SUCCESS').count()
        return round((success / total) * 100, 2)
    
    @extend_schema_field(OpenApiTypes.FLOAT)
    def get_average_time(self, obj):
        from django.db.models import Avg, F, ExpressionWrapper, DurationField
        
        completed_runs = obj.runs.filter(status__in=['SUCCESS', 'FAILURE'], finished_at__isnull=False)
        if not completed_runs.exists():
            return None
        
        avg_duration = completed_runs.aggregate(
            avg_duration=Avg(ExpressionWrapper(F('finished_at') - F('started_at'), output_field=DurationField()))
        )['avg_duration']
        
        if avg_duration:
            return round(avg_duration.total_seconds(), 2)
        return None

from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.files.storage import default_storage
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.openapi import OpenApiTypes
from django.utils.text import get_valid_filename
from django.core.files.base import ContentFile
from django.contrib.auth import get_user_model
from rest_framework import serializers
from .models import Script, Run
from django.conf import settings
import uuid
import json
import os

User = get_user_model()


class ScriptSerializer(serializers.ModelSerializer):
    class Meta:
        model = Script
        fields = ['id', 'name', 'description', 'pic', 'celery_task', 'input_schema', 'output_schema', 'created_at', 'updated_at', 'is_active']
        read_only_fields = ['created_at', 'updated_at']


class RunSerializer(serializers.ModelSerializer):
    script_name = serializers.CharField(source='script.name', read_only=True)
    started_by_email = serializers.CharField(source='started_by.email', read_only=True)
    duration = serializers.SerializerMethodField()
    input_file_paths = serializers.SerializerMethodField()

    class Meta:
        model = Run
        fields = [
            'id', 'script', 'script_name', 'started_by', 'started_by_email',
            'started_at', 'finished_at', 'status', 'celery_task_id',
            'input_data', 'result_data', 'logs_file_path', 'result_file_path',
            'error_message', 'duration', 'input_file_paths'
        ]
        read_only_fields = ['started_at', 'finished_at', 'celery_task_id', 'result_data', 'logs_file_path', 'result_file_path', 'error_message', 'duration']
    
    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_input_file_paths(self, obj):
        if obj.input_file_paths:
            return obj.input_file_paths
        return {}

    @extend_schema_field(OpenApiTypes.FLOAT)
    def get_duration(self, obj):
        return obj.get_duration()


class RunCreateSerializer(serializers.Serializer):
    script_id = serializers.IntegerField(required=True)

    def _validate_file_field(self, field_def, file_obj, field_name):
        """Validate uploaded file against schema constraints"""
        if file_obj is None:
            if field_def.get('required', False):
                raise serializers.ValidationError(f"File field '{field_name}' is required")
            return None  # Not required and not provided

        # Validate file size (maxFileSize in MB)
        max_size_mb = field_def.get('maxFileSize')
        if max_size_mb:
            max_size_bytes = max_size_mb * 1024 * 1024
            if file_obj.size > max_size_bytes:
                raise serializers.ValidationError(
                    f"File '{field_name}' exceeds maximum size of {max_size_mb} MB"
                )

        # Validate file extension
        allowed_exts = field_def.get('allowedExtensions', [])
        if allowed_exts:
            file_ext = os.path.splitext(file_obj.name)[1].lower().lstrip('.')
            if file_ext not in [ext.lower() for ext in allowed_exts]:
                raise serializers.ValidationError(
                    f"File '{field_name}' must be one of: {', '.join(allowed_exts)}"
                )

        return file_obj

    def _save_uploaded_file(self, file_obj, field_name):
        """Save file and return relative path"""
        clean_name = get_valid_filename(file_obj.name)  # removes bad chars
        filename = f"runs/input/{clean_name}"
        file_obj.seek(0)
        path = default_storage.save(filename, ContentFile(file_obj.read()))
        return path

    def _validate_field_value(self, field_def, value, field_name, files_dict=None):
        field_type = field_def.get('type')

        if field_type == 'file':
            file_obj = files_dict.get(field_name) if files_dict else None
            return self._validate_file_field(field_def, file_obj, field_name)

        # Existing validations (text, slider, etc.)
        if field_def.get('required') and (value is None or value == ''):
            raise serializers.ValidationError(f"Field '{field_name}' is required")
        if value is None or value == '':
            return

        if field_type == 'text':
            if not isinstance(value, str):
                raise serializers.ValidationError(f"Field '{field_name}' must be a string")

        elif field_type == 'slider':
            try:
                value = float(value)
                if value == int(value):
                    value = int(value)
            except:
                raise serializers.ValidationError(f"Field '{field_name}' must be a number")
            min_val = field_def.get('min')
            max_val = field_def.get('max')
            if min_val is not None and value < min_val:
                raise serializers.ValidationError(f"Field '{field_name}' must be >= {min_val}")
            if max_val is not None and value > max_val:
                raise serializers.ValidationError(f"Field '{field_name}' must be <= {max_val}")

        elif field_type == 'multiselect':
            if not isinstance(value, list):
                raise serializers.ValidationError(
                    f"Field '{field_name}' must be an array"
                )
            allowed = {opt['value'] for opt in field_def.get('options', [])}
            for idx, v in enumerate(value):
                if v not in allowed:
                    raise serializers.ValidationError(
                        f"Invalid option '{v}' in field '{field_name}'"
                    )

        elif field_type == 'dynamicArray':
            if not isinstance(value, list):
                raise serializers.ValidationError(f"Field '{field_name}' must be an array")
            for idx, item in enumerate(value):
                if not isinstance(item, dict):
                    raise serializers.ValidationError(f"Field '{field_name}[{idx}] must be an object")
                for nested_field in field_def.get('fields', []):
                    nested_name = nested_field.get('name')
                    nested_value = item.get(nested_name)
                    self._validate_field_value(nested_field, nested_value, f"{field_name}[{idx}].{nested_name}")

    def validate(self, data):
        print(data)
        script_id = data.get('script_id')
        try:
            script = Script.objects.get(id=script_id)
        except Script.DoesNotExist:
            raise serializers.ValidationError(f"Script with id {script_id} does not exist")

        input_schema = script.input_schema
        if not input_schema:
            raise serializers.ValidationError("Script does not have an input schema defined")

        dynamic_data = {k: v for k, v in self.initial_data.items() if k != 'script_id'}
        data.update(dynamic_data)

        json_data = {k: v for k, v in self.initial_data.items() if k != 'script_id' and not isinstance(v, InMemoryUploadedFile)}
        files_dict = {k: v for k, v in self.initial_data.items() if isinstance(v, InMemoryUploadedFile)}
        print(json_data)
        print(files_dict)
        all_fields = []
        for step in input_schema.get('steps', []):
            all_fields.extend(step.get('fields', []))

        validated_input = {}
        file_paths = {}

        # Validate each field
        for field_def in all_fields:
            field_name = field_def['name']
            field_type = field_def['type']

            if field_type == 'file':
                file_obj = files_dict.get(field_name)
                validated_file = self._validate_field_value(field_def, None, field_name, files_dict)
                if validated_file:
                    file_path = self._save_uploaded_file(validated_file, field_name)
                    file_paths[field_name] = file_path
            else:
                value = json_data.get(field_name)
                self._validate_field_value(field_def, value, field_name)
                if value not in (None, ''):
                    validated_input[field_name] = value

            # Check required fields
            if field_def.get('required'):
                if field_type == 'file':
                    if field_name not in files_dict:
                        raise serializers.ValidationError(f"Required file '{field_name}' is missing")
                elif field_name not in json_data:
                    raise serializers.ValidationError(f"Required field '{field_name}' is missing")

        # Store in data
        data['input_data'] = validated_input
        data['input_file_paths'] = file_paths  # e.g., {"products": "runs/input/abc123.csv"}
        data['script'] = script

        return data

    def create(self, validated_data):
        run = Run.objects.create(
            script=validated_data['script'],
            started_by=self.context['request'].user,
            input_data=validated_data['input_data'],
            input_file_paths=validated_data['input_file_paths']  # Store as JSON
        )
        return run


class ScriptStatsSerializer(serializers.ModelSerializer):
    total_runs = serializers.SerializerMethodField()
    success_count = serializers.SerializerMethodField()
    failed_count = serializers.SerializerMethodField()
    aborted_count = serializers.SerializerMethodField()
    running_count = serializers.SerializerMethodField()
    pending_count = serializers.SerializerMethodField()
    success_rate = serializers.SerializerMethodField()
    average_time = serializers.SerializerMethodField()
    
    class Meta:
        model = Script
        fields = ['id', 'name', 'description', 'total_runs', 'success_count', 'failed_count', 'aborted_count', 'running_count', 'pending_count', 'success_rate', 'average_time']
    
    @extend_schema_field(OpenApiTypes.INT)
    def get_total_runs(self, obj):
        return obj.runs.count()
    
    @extend_schema_field(OpenApiTypes.INT)
    def get_success_count(self, obj):
        return obj.runs.filter(status='SUCCESS').count()
    
    @extend_schema_field(OpenApiTypes.INT)
    def get_failed_count(self, obj):
        return obj.runs.filter(status='FAILURE').count()
    
    @extend_schema_field(OpenApiTypes.INT)
    def get_aborted_count(self, obj):
        return obj.runs.filter(status='REVOKED').count()
    
    @extend_schema_field(OpenApiTypes.INT)
    def get_running_count(self, obj):
        return obj.runs.filter(status='STARTED').count()
    
    @extend_schema_field(OpenApiTypes.INT)
    def get_pending_count(self, obj):
        return obj.runs.filter(status='PENDING').count()

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

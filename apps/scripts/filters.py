import django_filters
from .models import Run, CELERY_STATUS_CHOICES


class RunFilter(django_filters.FilterSet):
    script_id = django_filters.NumberFilter(field_name='script__id')
    status = django_filters.ChoiceFilter(choices=CELERY_STATUS_CHOICES)
    started_by = django_filters.NumberFilter(field_name='started_by__id')
    started_after = django_filters.DateTimeFilter(field_name='started_at', lookup_expr='gte')
    started_before = django_filters.DateTimeFilter(field_name='started_at', lookup_expr='lte')
    
    class Meta:
        model = Run
        fields = ['script_id', 'status', 'started_by', 'started_after', 'started_before']
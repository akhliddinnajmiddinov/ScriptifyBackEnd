from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ScriptViewSet, RunViewSet, run_logs_stream

router = DefaultRouter()
router.register(r'scripts', ScriptViewSet, basename='script')
router.register(r'runs', RunViewSet, basename='run')

urlpatterns = [
    path('', include(router.urls)),
    path("runs/<int:run_id>/logs-stream/", run_logs_stream),
]

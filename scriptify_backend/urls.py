from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework.permissions import AllowAny
from django.http import HttpResponse
from django.conf import settings
from django.conf.urls.static import static
from apps.user.views import TokenObtainAPIView, RevokeTokenAPIView

def health_check(request):
    return HttpResponse("OK", status=200)

urlpatterns = [
    # API Documentation
    path('api/docs/schema/', SpectacularAPIView.as_view(permission_classes=[AllowAny]), name='schema'),
    path('api/docs/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema', permission_classes=[AllowAny]), name='swagger-ui'),
    path('api/docs/redoc/', SpectacularRedocView.as_view(url_name='schema', permission_classes=[AllowAny]), name='redoc'),
    
    # OAuth2 endpoints
    path('oauth/token/', TokenObtainAPIView.as_view(), name="token_obtain"),
    path('oauth/token/revoke/', RevokeTokenAPIView.as_view(), name="token_revoke"),
    path('oauth/', include('oauth2_provider.urls', namespace='oauth2_provider')),
    
    # Other endpoints
    path("accounts/", include("django.contrib.auth.urls")),
    path('admin/', admin.site.urls),
    path('api/', include('api.urls')),
    path('health/', health_check, name='health'),
    path('events/', include('django_eventstream.urls')),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
"""
URL configuration for book_arena project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework.permissions import AllowAny, IsAuthenticated
import api.urls
from django.http import HttpResponse
from django.conf import settings
from django.conf.urls.static import static
from apps.user.views import TokenObtainAPIView, RevokeTokenAPIView

def health_check(request):
    return HttpResponse("OK", status=200)

urlpatterns = [
    path('api/docs/', SpectacularAPIView.as_view(permission_classes=[AllowAny]), name='schema'),
    path('api/docs/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema', permission_classes=[AllowAny]), name='swagger-ui'),
    path('api/docs/redoc/', SpectacularRedocView.as_view(url_name='schema', permission_classes=[AllowAny]), name='redoc'),
    
    path("accounts/", include("django.contrib.auth.urls")),
    
    path('admin/', admin.site.urls),
    path('oauth/token/', TokenObtainAPIView.as_view(), name="token_obtain"),
    path('oauth/token/refresh/', RevokeTokenAPIView.as_view(), name="token_revoke"),
    path('oauth/', include('oauth2_provider.urls', namespace='oauth2_provider')),
    
    path('api/', include('api.urls')),
    path('health/', health_check, name='health'),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
from django.urls import path, include

urlpatterns = [
    path('user/', include('apps.user.urls'), name="user"),
    path('', include('apps.scripts.urls')),  # Add scripts API
]
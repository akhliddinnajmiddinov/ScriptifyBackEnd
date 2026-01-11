from django.urls import path, include

urlpatterns = [
    path('user/', include('apps.user.urls'), name="user"),
    path('', include('apps.scripts.urls')),  # Add scripts API
    path('', include('apps.transactions.urls')),  # Add transactions API
    path('', include('apps.listings.urls')),  # Add listings API
]
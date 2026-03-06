from django.urls import path, include

urlpatterns = [
    path('user/', include('user.urls'), name="user"),
    path('', include('scripts.urls')),  # Add scripts API
    path('', include('transactions.urls')),  # Add transactions API
    path('', include('listings.urls')),  # Add listings API
    path('', include('tasks.urls')),  # Add tasks API
    path('', include('purchases.urls')),  # Add purchases API
]
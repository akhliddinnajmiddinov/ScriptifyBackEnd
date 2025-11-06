from django.urls import path, include

urlpatterns = [
    path('book/', include('apps.book.urls'), name="api"),
    path('user/', include('apps.user.urls'), name="user"),
]
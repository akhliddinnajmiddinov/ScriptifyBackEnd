from django.urls import path
from .views import (
    TokenObtainAPIView, RevokeTokenAPIView, UserRegisterView, UserProfileAPIView, ChangePasswordAPIView
)

urlpatterns = [
    path('register/', UserRegisterView.as_view(), name='register'),
    path('profile/', UserProfileAPIView.as_view(), name='user_profile'),
    path("change-password/", ChangePasswordAPIView.as_view(), name="change_password"),
]

from django.urls import path
from .views import (
    TokenObtainAPIView, RevokeTokenAPIView, SendCodeView, 
    VerifyCodeView, UserRegisterView, UserProfileAPIView
)

urlpatterns = [
    path('send-code/', SendCodeView.as_view(), name='send_code'),
    path('verify-code/', VerifyCodeView.as_view(), name='verify_code'),
    path('register/', UserRegisterView.as_view(), name='register'),
    path('profile/', UserProfileAPIView.as_view(), name='user_profile'),
]

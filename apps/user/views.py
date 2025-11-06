from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from oauth2_provider.settings import oauth2_settings
from braces.views import CsrfExemptMixin
from oauth2_provider.views.mixins import OAuthLibMixin
from drf_spectacular.utils import extend_schema
from django.http import HttpRequest, QueryDict

import json
from .serializers import RegisterUserSerializer, UserSerializer

from django.utils.decorators import method_decorator
from django.http import HttpResponse
from django.views.generic import View
from django.views.decorators.debug import sensitive_post_parameters
from django.utils.translation import gettext_lazy as _
from django.db import transaction
from rest_framework import serializers
from drf_spectacular.utils import extend_schema, inline_serializer
from oauth2_provider.views import TokenView, RevokeTokenView
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import extend_schema, inline_serializer, OpenApiExample
from django.utils import timezone

from django.contrib.auth import authenticate, login
import random
from .models import MyUser
from .serializers import RegisterUserSerializer, ChangePasswordSerializer

class TokenObtainAPIView(TokenView, APIView):
    @method_decorator(csrf_exempt)
    @extend_schema(
        request=inline_serializer(
            name="InlineTokenSerializer",
            fields={
                "username": serializers.CharField(),
                "password": serializers.CharField(),
                "grant_type": serializers.CharField(),
                "client_id": serializers.CharField(),
                "client_secret": serializers.CharField(),
            },
        ),
        tags=["Authentication"],
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class RevokeTokenAPIView(RevokeTokenView, APIView):
    @extend_schema(
        request=inline_serializer(
            name="RefreshTokenSerializer",
            fields={
                "refresh_token": serializers.CharField(),
                "grant_type": serializers.CharField(default="refresh_token"),
                "client_id": serializers.CharField(),
                "client_secret": serializers.CharField(),
            },
        ),
        responses={
            200: inline_serializer(
                name="RefreshTokenResponse",
                fields={
                    "access_token": serializers.CharField(),
                    "refresh_token": serializers.CharField(),
                    "token_type": serializers.CharField(),
                    "expires_in": serializers.IntegerField(),
                },
            ),
            400: inline_serializer(
                name="ErrorResponse",
                fields={"error": serializers.CharField()},
            ),
        },
        tags=["Authentication"],
    )
    def post(self, request, *args, **kwargs):
        """Handles OAuth2 token refresh"""
        return super().post(request, *args, **kwargs)


class UserRegisterView(CsrfExemptMixin, OAuthLibMixin, APIView):
    permission_classes = (permissions.AllowAny,)

    server_class = oauth2_settings.OAUTH2_SERVER_CLASS
    validator_class = oauth2_settings.OAUTH2_VALIDATOR_CLASS
    oauthlib_backend_class = oauth2_settings.OAUTH2_BACKEND_CLASS

    @extend_schema(
        summary="Register a new user",
        description="Registers a new user and returns an OAuth2 token.",
        request=RegisterUserSerializer,
        responses={
            201: {
                "message": "User registered successfully",
                "data": {
                    "access_token": "B6YSNgMmjlRVh2DVe1wzwD8X8Id4oO",
                    "expires_in": 86400,
                    "token_type": "Bearer",
                    "scope": "read write",
                    "refresh_token": "j41z6KcxMaPGXGbSQy6Obp2HsN0RrL"
                }
            },
            400: {"error": "string"},
            403: {"detail": "string"}
        },
        tags=["Authentication"],
    )
    def post(self, request):
        if request.auth is None:
            serializer = RegisterUserSerializer(data=request.data)
            if serializer.is_valid():
                try:
                    with transaction.atomic():
                        user = serializer.save()
                        
                        token_request_data = {
                            "grant_type": "password",
                            "username": serializer.validated_data["email"],
                            "password": serializer.validated_data["password"],
                            "client_id": request.data["client_id"],
                            "client_secret": request.data["client_secret"]
                        }

                        # Create a new request object for token generation
                        token_request = HttpRequest()
                        token_request.method = "POST"
                        token_request.POST = QueryDict('', mutable=True)
                        token_request.POST.update(token_request_data)
                        token_request.META = request.META.copy()

                        # Generate token
                        url, headers, body, token_status = self.create_token_response(token_request)
                        print(json.loads(body))
                        if token_status != 200:
                            error_msg = json.loads(body).get("error", "Token generation failed")
                            raise Exception(error_msg)

                        return Response({"message": "User registered successfully", "data": json.loads(body)}, status=token_status)
                except Exception as e:
                    return Response({"message": str(e)}, status=status.HTTP_400_BAD_REQUEST)
            return Response({"message": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"message": "User is authenticated"}, status=status.HTTP_403_FORBIDDEN)


class UserProfileAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        summary="Get user profile",
        description="Retrieves the authenticated user's profile information",
        responses={
            200: {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "data": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "email": {"type": "string"},
                            "first_name": {"type": "string"},
                            "last_name": {"type": "string"},
                            "photo": {"type": "string"},
                            "date_joined": {"type": "string"}
                        }
                    }
                }
            }
        },
        tags=["User Profile"]
    )
    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response({
            "success": True,
            "data": serializer.data
        }, status=status.HTTP_200_OK)
    
    @extend_schema(
        summary="Update user profile",
        description="Updates the authenticated user's profile information",
        request=UserSerializer,
        responses={
            200: {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "message": {"type": "string"},
                    "data": {"type": "object"}
                }
            }
        },
        tags=["User Profile"]
    )
    def put(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({
                "success": True,
                "message": "Profile updated successfully",
                "data": serializer.data
            }, status=status.HTTP_200_OK)
        return Response({
            "success": False,
            "error": "Validation failed",
            "message": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


# apps/user/views.py

class ChangePasswordAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Change user password",
        request=ChangePasswordSerializer,
        responses={
            200: inline_serializer(
                name="ChangePasswordSuccess",
                fields={"success": serializers.BooleanField(), "message": serializers.CharField()},
            ),
            400: inline_serializer(
                name="ChangePasswordError",
                fields={"error": serializers.CharField()},
            ),
        },
        tags=["User Profile"],
    )
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        if not serializer.is_valid():
            return Response(
                {"success": False, "error": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.save()

        return Response(
            {
                "success": True,
                "message": "Password changed successfully. Please log in again to get new tokens.",
            },
            status=status.HTTP_200_OK,
        )
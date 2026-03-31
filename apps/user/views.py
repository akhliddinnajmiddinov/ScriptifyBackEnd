from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from rest_framework.pagination import PageNumberPagination
from oauth2_provider.settings import oauth2_settings
from braces.views import CsrfExemptMixin
from oauth2_provider.views.mixins import OAuthLibMixin
from django.http import HttpRequest, QueryDict
from django.contrib.auth.models import Group

import json
from .serializers import (
    RegisterUserSerializer, UserSerializer, ChangePasswordSerializer,
    StaffUserSerializer, RoleSerializer, RoleWriteSerializer,
)

from django.utils.decorators import method_decorator
from django.http import HttpResponse
from django.views.generic import View
from django.views.decorators.debug import sensitive_post_parameters
from django.utils.translation import gettext_lazy as _
from django.db import transaction
from rest_framework import serializers
from oauth2_provider.views import TokenView, RevokeTokenView
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import extend_schema, inline_serializer, OpenApiExample
from django.utils import timezone

from django.contrib.auth import authenticate, login
import random
from .models import MyUser
from .permission_tree import PERMISSION_TREE

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


class StaffPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class StaffListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        qs = MyUser.objects.all().prefetch_related('groups').order_by('-date_joined')
        search = request.query_params.get('search')
        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(email__icontains=search) |
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search)
            )
        is_active = request.query_params.get('is_active')
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() == 'true')
        role = request.query_params.get('role')
        if role:
            qs = qs.filter(groups__name=role)

        paginator = StaffPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = StaffUserSerializer(page, many=True, context={'request': request})
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        serializer = StaffUserSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            user = serializer.save()
            return Response(StaffUserSerializer(user, context={'request': request}).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class StaffDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _get_user(self, pk):
        try:
            return MyUser.objects.prefetch_related('groups').get(pk=pk)
        except MyUser.DoesNotExist:
            return None

    def get(self, request, pk):
        user = self._get_user(pk)
        if not user:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(StaffUserSerializer(user, context={'request': request}).data)

    def put(self, request, pk):
        user = self._get_user(pk)
        if not user:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = StaffUserSerializer(user, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        user = self._get_user(pk)
        if not user:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class StaffAssignRoleView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            user = MyUser.objects.get(pk=pk)
        except MyUser.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        role_ids = request.data.get('role_ids', [])
        if not isinstance(role_ids, list):
            return Response({'detail': 'role_ids must be a list.'}, status=status.HTTP_400_BAD_REQUEST)

        groups = Group.objects.filter(id__in=role_ids)
        user.groups.set(groups)
        return Response(StaffUserSerializer(user, context={'request': request}).data)


class RoleListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        groups = Group.objects.prefetch_related('permissions').all().order_by('name')
        return Response(RoleSerializer(groups, many=True).data)

    def post(self, request):
        serializer = RoleWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        group = Group.objects.create(name=serializer.validated_data['name'])
        group.permissions.set(serializer.validated_data['permissions'])
        return Response(RoleSerializer(group).data, status=status.HTTP_201_CREATED)


class RoleDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _get_group(self, pk):
        try:
            return Group.objects.prefetch_related('permissions').get(pk=pk)
        except Group.DoesNotExist:
            return None

    def get(self, request, pk):
        group = self._get_group(pk)
        if not group:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(RoleSerializer(group).data)

    def put(self, request, pk):
        group = self._get_group(pk)
        if not group:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = RoleWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        group.name = serializer.validated_data['name']
        group.save()
        group.permissions.set(serializer.validated_data['permissions'])
        return Response(RoleSerializer(group).data)

    def delete(self, request, pk):
        group = self._get_group(pk)
        if not group:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        group.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PermissionTreeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(PERMISSION_TREE)
from django.urls import path
from .views import (
    TokenObtainAPIView, RevokeTokenAPIView, UserRegisterView, UserProfileAPIView, ChangePasswordAPIView,
    StaffListCreateView, StaffDetailView, StaffAssignRoleView,
    RoleListCreateView, RoleDetailView,
    PermissionTreeView,
)

urlpatterns = [
    path('register/', UserRegisterView.as_view(), name='register'),
    path('profile/', UserProfileAPIView.as_view(), name='user_profile'),
    path('change-password/', ChangePasswordAPIView.as_view(), name='change_password'),
    path('staff/', StaffListCreateView.as_view(), name='staff_list_create'),
    path('staff/<int:pk>/', StaffDetailView.as_view(), name='staff_detail'),
    path('staff/<int:pk>/assign-role/', StaffAssignRoleView.as_view(), name='staff_assign_role'),
    path('roles/', RoleListCreateView.as_view(), name='role_list_create'),
    path('roles/<int:pk>/', RoleDetailView.as_view(), name='role_detail'),
    path('permissions/tree/', PermissionTreeView.as_view(), name='permission_tree'),
]

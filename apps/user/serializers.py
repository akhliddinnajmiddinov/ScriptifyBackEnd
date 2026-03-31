from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema_field
from .models import MyUser

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField()
    permissions = serializers.SerializerMethodField()
    roles = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'last_name', 'full_name',
            'photo', 'date_joined', 'is_superuser', 'permissions', 'roles',
        ]
        read_only_fields = ['id', 'date_joined', 'is_superuser', 'permissions', 'roles']

    @extend_schema_field(serializers.CharField())
    def full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}"

    def get_permissions(self, obj):
        if obj.is_superuser:
            return ['*']
        perms = obj.user_permissions.values_list('content_type__app_label', 'codename')
        group_perms = Permission.objects.filter(group__user=obj).values_list('content_type__app_label', 'codename')
        all_perms = set(f"{app}.{code}" for app, code in perms) | set(f"{app}.{code}" for app, code in group_perms)
        return sorted(all_perms)

    def get_roles(self, obj):
        return list(obj.groups.values_list('name', flat=True))


class RegisterUserSerializer(serializers.ModelSerializer):
    confirm_password = serializers.CharField(write_only=True, required=True)
    client_id = serializers.CharField(write_only=True, required=True)
    client_secret = serializers.CharField(write_only=True, required=True)

    def validate(self, data):
        if User.objects.filter(email=data.get('email')).exists():
            raise serializers.ValidationError(_("User with this phone number already exists"))

        if not data.get('password') or not data.get('confirm_password'):
            raise serializers.ValidationError(_("Passwords should not be empty"))

        if data.get('password') != data.get('confirm_password'):
            raise serializers.ValidationError(_("Passwords mismatch"))
        
        return data

    def create(self, validated_data):
        validated_data.pop('client_id')
        validated_data.pop('client_secret')
        validated_data.pop("confirm_password")
        return User.objects.create_user(**validated_data)

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name", "password", "confirm_password", 'client_id', 'client_secret')
        extra_kwargs = {
            "password": {"write_only": True}, 
            "confirm_password": {"write_only": True}
        }


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)
    client_id = serializers.CharField(write_only=True, required=True)
    client_secret = serializers.CharField(write_only=True, required=True)

    def validate(self, data):
        if data["new_password"] != data["confirm_password"]:
            raise serializers.ValidationError("New passwords do not match.")
        return data

    def validate_current_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value


class StaffUserSerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField()
    roles = serializers.SerializerMethodField()
    password = serializers.CharField(write_only=True, required=False, min_length=8)

    class Meta:
        model = MyUser
        fields = ['id', 'email', 'first_name', 'last_name', 'full_name', 'photo', 'is_active', 'is_superuser', 'date_joined', 'roles', 'password']
        read_only_fields = ['id', 'date_joined']

    def get_roles(self, obj):
        return list(obj.groups.values_list('name', flat=True))

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = MyUser(**validated_data)
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class RoleSerializer(serializers.ModelSerializer):
    permissions = serializers.SerializerMethodField()
    user_count = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = ['id', 'name', 'permissions', 'user_count']

    def get_permissions(self, obj):
        return list(
            obj.permissions.values_list('content_type__app_label', 'codename')
        )

    def get_user_count(self, obj):
        return obj.user_set.count()

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Return permissions as "app_label.codename" strings
        data['permissions'] = [f"{app}.{code}" for app, code in data['permissions']]
        return data


class RoleWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    permissions = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
    )

    def validate_permissions(self, codenames):
        resolved = []
        errors = []
        for codename in codenames:
            parts = codename.split('.')
            if len(parts) != 2:
                errors.append(f"Invalid format: '{codename}'. Expected 'app_label.codename'.")
                continue
            app_label, code = parts
            try:
                perm = Permission.objects.get(content_type__app_label=app_label, codename=code)
                resolved.append(perm)
            except Permission.DoesNotExist:
                errors.append(f"Permission not found: '{codename}'.")
        if errors:
            raise serializers.ValidationError(errors)
        return resolved
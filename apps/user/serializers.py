from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from .models import MyUser

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField()
    
    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'last_name', 'full_name', 
            'photo', 'date_joined'
        ]
        read_only_fields = ['id', 'date_joined']

    @extend_schema_field(serializers.CharField())
    def full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}"


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
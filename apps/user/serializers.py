from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from .models import MyUser, PhoneVerificationCode

User = get_user_model()

class SendCodeSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=15)


class VerifyCodeSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=15)
    code = serializers.CharField(max_length=5)


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField()
    current_reading_streak = serializers.ReadOnlyField()
    
    class Meta:
        model = User
        fields = [
            'id', 'phone_number', 'first_name', 'last_name', 'full_name', 
            'email', 'age', 'bio', 'photo', 'reading_goal', 'favorite_genres',
            'current_reading_streak', 'date_joined'
        ]
        read_only_fields = ['id', 'phone_number', 'date_joined']


class RegisterUserSerializer(serializers.ModelSerializer):
    confirm_password = serializers.CharField(write_only=True, required=True)
    client_id = serializers.CharField(write_only=True, required=True)
    client_secret = serializers.CharField(write_only=True, required=True)

    def validate(self, data):
        if User.objects.filter(phone_number=data.get('phone_number')).exists():
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
        fields = ("phone_number", "first_name", "last_name", "password", "confirm_password", 'client_id', 'client_secret')
        extra_kwargs = {
            "password": {"write_only": True}, 
            "confirm_password": {"write_only": True}
        }

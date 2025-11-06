import uuid
from django.db import models
from datetime import timedelta
from django.utils import timezone
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager, AbstractUser
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    def create_user(self, phone_number, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(phone_number, password, **extra_fields)

    def create_superuser(self, phone_number, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        return self._create_user(phone_number, password, **extra_fields)

    def _create_user(self, phone_number, password=None, **extra_fields):
        if not phone_number:
            raise ValueError('The Phone Number field must be set')
        user = self.model(phone_number=phone_number, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user


class MyUser(AbstractUser):
    username = None
    phone_number = models.CharField(max_length=15, unique=True)
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    email = models.EmailField(null=True, blank=True)
    age = models.PositiveIntegerField(null=True, blank=True)
    bio = models.TextField(null=True, blank=True)
    photo = models.ImageField(upload_to='user_photos/', null=True, blank=True)
    reading_goal = models.PositiveIntegerField(default=12)
    favorite_genres = models.JSONField(default=list)
    
    USERNAME_FIELD = 'phone_number'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    objects = UserManager()

    def __str__(self):
        return self.phone_number

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def current_reading_streak(self):
        """Calculate current reading streak in days"""
        from apps.book.models import BookReading
        
        today = timezone.now().date()
        streak = 0
        current_date = today
        
        # Check each day backwards from today
        while True:
            has_reading = BookReading.objects.filter(
                book__user=self,
                date_read__date=current_date
            ).exists()
            
            if has_reading:
                streak += 1
                current_date -= timedelta(days=1)
            else:
                break
                
            # Prevent infinite loop
            if streak > 365:
                break
                
        return streak


class PhoneVerificationCode(models.Model):
    phone_number = models.CharField(max_length=15)
    code = models.CharField(max_length=5)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def is_expired(self):
        return timezone.now() > self.created_at + timedelta(minutes=5)
    
    def __str__(self):
        return f"{self.phone_number} - {self.code}"

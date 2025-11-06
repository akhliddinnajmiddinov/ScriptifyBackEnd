from rest_framework import serializers
from .models import Book, BookReading, ReadingGoal, Achievement, UserAchievement, Notification
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField()
    current_reading_streak = serializers.ReadOnlyField()
    
    class Meta:
        model = User
        fields = ['id', 'phone_number', 'first_name', 'last_name', 'full_name', 
                 'email', 'age', 'bio', 'photo', 'reading_goal', 'favorite_genres',
                 'current_reading_streak', 'date_joined']


class BookSerializer(serializers.ModelSerializer):
    user_data = UserSerializer(read_only=True, source='user')
    progress_percentage = serializers.ReadOnlyField()
    is_completed = serializers.ReadOnlyField()

    def create(self, validated_data):
        validated_data["user"] = self.context['request'].user
        return super().create(validated_data)

    class Meta:
        model = Book
        exclude = ["user"]


class BookReadingSerializer(serializers.ModelSerializer):
    book = serializers.PrimaryKeyRelatedField(queryset=Book.objects.all(), write_only=True)
    book_data = BookSerializer(read_only=True, source='book')

    def validate(self, data):
        # Get book from data or instance
        book = data.get('book', getattr(self.instance, 'book', None))
        if not book:
            raise serializers.ValidationError({"book": "Book is required."})

        # Ensure user owns the book
        request = self.context.get('request')
        if request and book.user != request.user:
            raise serializers.ValidationError({"book": "You can only add reading sessions to your own books."})

        # Get end_page, falling back to instance values
        end_page = data.get('end_page', getattr(self.instance, 'end_page', None))

        if end_page is not None:
            pages_read = book.pages_read or 0
            if end_page <= pages_read:
                raise serializers.ValidationError({
                    'end_page': f"end_page ({end_page}) must be greater than the book's pages_read ({pages_read})."
                })

        # Validate end_page <= num_pages
        if end_page is not None:
            if end_page > book.num_pages:
                raise serializers.ValidationError({
                    'end_page': f"end_page ({end_page}) cannot exceed the book's total pages ({book.num_pages})."
                })

        return data

    def create(self, validated_data, *args, **kwargs):
        book_reading = super().create(validated_data, *args, **kwargs)
        book = book_reading.book
        book.pages_read = max(book.pages_read or 0, book_reading.end_page)
        book.save()
        return book_reading

    def update(self, instance, validated_data, *args, **kwargs):
        if "book" in validated_data:
            raise serializers.ValidationError({
                "book": "You cannot update the book of BookReading."
            })
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if 'end_page' in validated_data:
            book = instance.book
            book.pages_read = max(book.pages_read or 0, validated_data['end_page'])
            book.save()
        return instance

    class Meta:
        model = BookReading
        fields = "__all__"


class ReadingGoalSerializer(serializers.ModelSerializer):
    books_progress = serializers.ReadOnlyField()
    
    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)

    class Meta:
        model = ReadingGoal
        exclude = ['user']


class AchievementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Achievement
        fields = '__all__'


class UserAchievementSerializer(serializers.ModelSerializer):
    achievement_data = AchievementSerializer(read_only=True, source='achievement')
    
    class Meta:
        model = UserAchievement
        fields = ['id', 'achievement', 'achievement_data', 'earned_at']


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        exclude = ['user']

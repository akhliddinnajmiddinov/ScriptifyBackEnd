from django.conf import settings
from .models import Book, BookReading
from django.db.models import Sum

User = settings.AUTH_USER_MODEL

class Statistics:
    def get_user_stats(self, user: User):
        return BookReading.objects.filter(book__user=user).aggregate(total_time_read=Sum("time_read"))
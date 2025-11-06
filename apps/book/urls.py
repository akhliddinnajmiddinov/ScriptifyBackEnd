from django.urls import path
from .views import (
    BookAPIView, BookListAPIView, BookReadingAPIView, BookReadingListAPIView,
    dashboard_stats, monthly_stats, ReadingGoalListAPIView,
    AchievementListAPIView, AvailableAchievementsAPIView,
    NotificationListAPIView, NotificationAPIView
)

urlpatterns = [
    # Books
    path("", BookListAPIView.as_view(), name="book"),
    path("<int:pk>/", BookAPIView.as_view(), name="book_one"),
    
    # Reading Sessions
    path("reading/", BookReadingListAPIView.as_view(), name="book_reading"),
    path("reading/<int:pk>/", BookReadingAPIView.as_view(), name="book_reading_one"),
    
    # Statistics
    path("stats/dashboard/", dashboard_stats, name="dashboard_stats"),
    path("stats/monthly/", monthly_stats, name="monthly_stats"),
    
    # Reading Goals
    path("goals/", ReadingGoalListAPIView.as_view(), name="reading_goals"),
    
    # Achievements
    path("achievements/", AchievementListAPIView.as_view(), name="user_achievements"),
    path("achievements/available/", AvailableAchievementsAPIView.as_view(), name="available_achievements"),
    
    # Notifications
    path("notifications/", NotificationListAPIView.as_view(), name="notifications"),
    path("notifications/<int:pk>/", NotificationAPIView.as_view(), name="notification_detail"),
]

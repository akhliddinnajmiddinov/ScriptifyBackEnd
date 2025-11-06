from django.shortcuts import get_object_or_404
from django.db.models import Count, Sum, Avg, Q
from django.utils import timezone
from datetime import datetime, timedelta
from .serializers import *
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_400_BAD_REQUEST,
    HTTP_204_NO_CONTENT,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT
)
from rest_framework.renderers import JSONRenderer, MultiPartRenderer
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView
from rest_framework.decorators import api_view, permission_classes
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from .models import Book, BookReading, ReadingGoal, Achievement, UserAchievement, Notification
from django.utils import timezone

class BookListAPIView(APIView):
    """
    API endpoint for getting list of all books belonging to the authenticated user and post, put, delete book
    """
    renderer_classes = [JSONRenderer]
    permission_classes = [IsAuthenticated]
    serializer_class = BookSerializer

    @extend_schema(
        summary="Retrieve books",
        description="Fetches all books belonging to the authenticated user",
        responses={200: serializer_class, 404: OpenApiResponse(description="Object not found")},
        tags=["Book"]
    )
    def get(self, request, *args, **kwargs):
        queryset = Book.objects.filter(user=request.user).order_by('-id')
        
        # Filter by status if provided
        status = request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
            
        # Search functionality
        search = request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | 
                Q(author__icontains=search) |
                Q(genre__icontains=search)
            )
        
        if request.GET.get('page') and request.GET.get('limit'):
            paginator = PageNumberPagination()
            paginator.page_size = request.GET.get('limit')
            result_page = paginator.paginate_queryset(queryset, request)
            serializer = BookSerializer(result_page, many=True)
            return paginator.get_paginated_response({"data": serializer.data})
        
        serializer = BookSerializer(queryset, many=True)
        return Response({"data": serializer.data}, status=HTTP_200_OK)

    @extend_schema(
        summary="Create a new book",
        description="Adds a new book entry for the authenticated user.",
        request=serializer_class,
        responses={201: serializer_class, 400: OpenApiResponse(description="Bad Request: Validation Error")},
        tags=["Book"],
        parameters=[]
    )
    def post(self, request, *args, **kwargs):
        serializer = BookSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            book = serializer.save()
            return Response({
                "success": True,
                "message": "Book created successfully", 
                "data": serializer.data
            }, status=HTTP_201_CREATED)
        return Response({
            "success": False,
            "error": "Validation failed",
            "message": serializer.errors
        }, status=HTTP_400_BAD_REQUEST)


class BookAPIView(APIView):
    """
    API endpoint for getting specific book belonging to the authenticated user
    """
    renderer_classes = [JSONRenderer]
    permission_classes = [IsAuthenticated]
    serializer_class = BookSerializer

    @extend_schema(
        summary="Retrieve specific book",
        description="Fetches a specific book by its ID belonging to the authenticated user",
        responses={200: serializer_class, 404: OpenApiResponse(description="Object not found")},
        tags=["Book"]
    )
    def get(self, request, pk: int, *args, **kwargs):
        try:
            instance = Book.objects.get(pk=pk, user=request.user)
            serializer = BookSerializer(instance=instance)
            return Response({
                "success": True,
                "data": serializer.data
            }, status=HTTP_200_OK)
        except Book.DoesNotExist:
            return Response({
                "success": False,
                "error": "Book not found",
                "message": "The requested book does not exist or you don't have permission to access it."
            }, status=HTTP_404_NOT_FOUND)

    @extend_schema(
        summary="Update an existing book",
        description="Modifies the details of an existing book entry identified by its ID.",
        request=serializer_class,
        responses={200: serializer_class, 400: OpenApiResponse(description="Bad Request: Validation Error")},
        tags=["Book"]
    )
    def put(self, request, pk: int, *args, **kwargs):
        try:
            instance = Book.objects.get(pk=pk, user=request.user)
            serializer = BookSerializer(instance=instance, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response({
                    "success": True,
                    "message": "Book updated successfully", 
                    "data": serializer.data
                }, status=HTTP_200_OK)
            return Response({
                "success": False,
                "error": "Validation failed",
                "message": serializer.errors
            }, status=HTTP_400_BAD_REQUEST)
        except Book.DoesNotExist:
            return Response({
                "success": False,
                "error": "Book not found",
                "message": "The requested book does not exist or you don't have permission to access it."
            }, status=HTTP_404_NOT_FOUND)

    @extend_schema(
        summary="Delete a book",
        description="Removes a book entry identified by its ID.",
        responses={204: OpenApiResponse(description="Book deleted successfully")},
        tags=["Book"]
    )
    def delete(self, request, pk: int):
        try:
            instance = Book.objects.get(pk=pk, user=request.user)
            serializer_data = BookSerializer(instance=instance).data
            instance.delete()
            return Response({
                "success": True,
                "message": "Book deleted successfully", 
                "data": serializer_data
            }, status=HTTP_204_NO_CONTENT)
        except Book.DoesNotExist:
            return Response({
                "success": False,
                "error": "Book not found",
                "message": "The requested book does not exist or you don't have permission to access it."
            }, status=HTTP_404_NOT_FOUND)


class BookReadingListAPIView(APIView):
    """
    API endpoint for managing book reading sessions.
    """
    renderer_classes = [JSONRenderer]
    permission_classes = [IsAuthenticated]
    serializer_class = BookReadingSerializer
    object_class = BookReading

    @extend_schema(
        summary="Get the list of book reading sessions",
        description="Retrieves the list of book reading sessions belonging to authenticated user",
        responses={
            200: serializer_class,
            404: OpenApiResponse(description="Object not found")
        },
        tags=["BookReading"]
    )
    def get(self, request, *args, **kwargs):
        queryset = self.object_class.objects.filter(book__user=request.user).order_by('-date_read')  

        book_id = self.request.query_params.get('book_id')
        if book_id:
            try:
                book = Book.objects.get(id=book_id, user=request.user)
                queryset = queryset.filter(book=book)
            except Book.DoesNotExist:
                return Response({
                    "success": False,
                    "error": "Book not found",
                    "message": "The specified book does not exist."
                }, status=HTTP_404_NOT_FOUND)

        if request.GET.get('page') and request.GET.get('limit'):
            paginator = PageNumberPagination()
            paginator.page_size = request.GET.get('limit')
            result_page = paginator.paginate_queryset(queryset, request)
            serializer = self.serializer_class(result_page, many=True)
            return paginator.get_paginated_response({"data": serializer.data})
        
        serializer = self.serializer_class(queryset, many=True)
        return Response({"data": serializer.data}, status=HTTP_200_OK)

    @extend_schema(
        summary="Create a new book reading session",
        description="Creates a new book reading session for the authenticated user",
        request=serializer_class,
        responses={201: serializer_class, 400: OpenApiResponse(description="Bad Request: Validation Error")},
        tags=["BookReading"]
    )
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data, context={"request": request})
        if serializer.is_valid():
            reading_session = serializer.save()
            return Response({
                "success": True,
                "message": "Reading session created successfully!", 
                "data": serializer.data
            }, status=HTTP_201_CREATED)
        
        return Response({
            "success": False,
            "error": "Validation failed",
            "message": serializer.errors
        }, status=HTTP_400_BAD_REQUEST)


class BookReadingAPIView(APIView):
    """
    API endpoint for managing individual book reading sessions.
    """
    renderer_classes = [JSONRenderer]
    permission_classes = [IsAuthenticated]
    serializer_class = BookReadingSerializer
    object_class = BookReading

    @extend_schema(
        summary="Get specific book reading session",
        description="Retrieves a specific book reading session for the authenticated user",
        responses={
            200: serializer_class,
            404: OpenApiResponse(description="Reading session not found")
        },
        tags=["BookReading"]
    )
    def get(self, request, pk: int, *args, **kwargs):
        try:
            book_reading = self.object_class.objects.get(pk=pk, book__user=request.user)
            return Response({
                "success": True,
                "data": self.serializer_class(book_reading).data
            }, status=HTTP_200_OK)
        except self.object_class.DoesNotExist:
            return Response({
                "success": False,
                "error": "Reading session not found",
                "message": "The requested reading session does not exist."
            }, status=HTTP_404_NOT_FOUND)

    @extend_schema(
        summary="Delete a book reading session",
        description="Deletes a specific book reading session identified by its primary key.",
        responses={
            204: OpenApiResponse(description="Reading session deleted successfully")
        },
        tags=["BookReading"]
    )
    def delete(self, request, pk: int):
        try:
            obj = self.object_class.objects.get(pk=pk, book__user=request.user)
            book = obj.book

            # Check if this is the last reading session for the book
            last_book_reading = self.object_class.objects.filter(book=book).order_by("-date_read").first()
            if obj.pk != last_book_reading.pk:
                return Response({
                    "success": False,
                    "error": "Cannot delete reading session",
                    "message": f"You can only delete the most recent reading session for {book.name}"
                }, status=HTTP_400_BAD_REQUEST)
            
            obj.delete()

            # Update book progress after deletion
            last_book_reading = self.object_class.objects.filter(book=book).order_by("-date_read").first()
            if not last_book_reading:
                book.pages_read = 0
                book.status = 'unread'
            else:
                book.pages_read = last_book_reading.end_page
                if book.pages_read >= book.num_pages:
                    book.status = 'read'
                elif book.pages_read > 0:
                    book.status = 'reading'
            book.save()

            return Response({
                "success": True,
                "message": "Reading session deleted successfully"
            }, status=HTTP_204_NO_CONTENT)
        except self.object_class.DoesNotExist:
            return Response({
                "success": False,
                "error": "Reading session not found",
                "message": "The requested reading session does not exist."
            }, status=HTTP_404_NOT_FOUND)


# Statistics Views
@api_view(['GET'])
@permission_classes([IsAuthenticated])
@extend_schema(
    summary="Get dashboard statistics",
    description="Retrieves comprehensive reading statistics for the authenticated user",
    responses={
        200: {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "total_books": {"type": "integer"},
                        "books_read": {"type": "integer"},
                        "currently_reading": {"type": "integer"},
                        "pages_read": {"type": "integer"},
                        "reading_time_hours": {"type": "number"},
                        "current_streak": {"type": "integer"},
                        "average_rating": {"type": "number"},
                        "goal_progress": {"type": "object"}
                    }
                }
            }
        }
    },
    tags=["Statistics"]
)
def dashboard_stats(request):
    user = request.user
    current_year = timezone.now().year
    
    # Basic stats
    total_books = Book.objects.filter(user=user).count()
    books_read = Book.objects.filter(user=user, status='read').count()
    currently_reading = Book.objects.filter(user=user, status='reading').count()
    
    # Pages and time stats
    pages_stats = BookReading.objects.filter(book__user=user).aggregate(
        total_pages=Sum('end_page'),
        total_time=Sum('time_read')
    )
    
    # Reading goal progress
    try:
        current_goal = ReadingGoal.objects.get(user=user, year=current_year)
        goal_progress = current_goal.books_progress
    except ReadingGoal.DoesNotExist:
        goal_progress = None
    
    # Average rating
    avg_rating = Book.objects.filter(user=user, rating__isnull=False).aggregate(
        avg_rating=Avg('rating')
    )['avg_rating']
    
    data = {
        "total_books": total_books,
        "books_read": books_read,
        "currently_reading": currently_reading,
        "pages_read": pages_stats['total_pages'] or 0,
        "reading_time_hours": round((pages_stats['total_time'] or 0) / 60, 1),
        "current_streak": user.current_reading_streak,
        "average_rating": round(avg_rating, 1) if avg_rating else 0,
        "goal_progress": goal_progress
    }
    
    return Response({
        "success": True,
        "data": data
    }, status=HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@extend_schema(
    summary="Get monthly reading statistics",
    description="Retrieves monthly reading data for the current year",
    responses={
        200: {
            "type": "object",
            "properties": {
                "data": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "month": {"type": "string"},
                            "books": {"type": "integer"}
                        }
                    }
                }
            }
        }
    },
    tags=["Statistics"]
)
def monthly_stats(request):
    user = request.user
    current_year = timezone.now().year
    
    monthly_data = []
    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
              'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    
    for i, month in enumerate(months, 1):
        books_count = Book.objects.filter(
            user=user,
            status='read',
            finish_date__year=current_year,
            finish_date__month=i
        ).count()
        
        monthly_data.append({
            "month": month,
            "books": books_count
        })
    
    return Response({"data": monthly_data}, status=HTTP_200_OK)


# Reading Goals Views
class ReadingGoalListAPIView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ReadingGoalSerializer

    @extend_schema(
        summary="Get reading goals",
        description="Retrieves reading goals for the authenticated user",
        tags=["Reading Goals"]
    )
    def get(self, request):
        goals = ReadingGoal.objects.filter(user=request.user).order_by('-year')
        serializer = ReadingGoalSerializer(goals, many=True)
        return Response({
            "success": True,
            "data": serializer.data
        }, status=HTTP_200_OK)

    @extend_schema(
        summary="Create reading goal",
        description="Creates a new reading goal for the authenticated user",
        request=serializer_class,
        tags=["Reading Goals"]
    )
    def post(self, request):
        serializer = ReadingGoalSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            serializer.save()
            return Response({
                "success": True,
                "message": "Reading goal created successfully", 
                "data": serializer.data
            }, status=HTTP_201_CREATED)
        return Response({
            "success": False,
            "error": "Validation failed",
            "message": serializer.errors
        }, status=HTTP_400_BAD_REQUEST)


# Achievements Views
class AchievementListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Get user achievements",
        description="Retrieves achievements earned by the authenticated user",
        tags=["Achievements"]
    )
    def get(self, request):
        user_achievements = UserAchievement.objects.filter(user=request.user).order_by('-earned_at')
        serializer = UserAchievementSerializer(user_achievements, many=True)
        return Response({
            "success": True,
            "data": serializer.data
        }, status=HTTP_200_OK)


class AvailableAchievementsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Get available achievements",
        description="Retrieves all available achievements and user's progress",
        tags=["Achievements"]
    )
    def get(self, request):
        achievements = Achievement.objects.filter(is_active=True)
        user_achievements = UserAchievement.objects.filter(user=request.user).values_list('achievement_id', flat=True)
        
        data = []
        for achievement in achievements:
            data.append({
                "id": achievement.id,
                "name": achievement.name,
                "description": achievement.description,
                "icon": achievement.icon,
                "condition_type": achievement.condition_type,
                "condition_value": achievement.condition_value,
                "points": achievement.points,
                "is_earned": achievement.id in user_achievements
            })
        
        return Response({
            "success": True,
            "data": data
        }, status=HTTP_200_OK)


# Notifications Views
class NotificationListAPIView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer

    @extend_schema(
        summary="Get notifications",
        description="Retrieves notifications for the authenticated user",
        tags=["Notifications"]
    )
    def get(self, request):
        notifications = Notification.objects.filter(user=request.user).order_by('-created_at')
        serializer = NotificationSerializer(notifications, many=True)
        return Response({
            "success": True,
            "data": serializer.data
        }, status=HTTP_200_OK)

    @extend_schema(
        summary="Mark all notifications as read",
        description="Marks all notifications as read for the authenticated user",
        tags=["Notifications"]
    )
    def post(self, request):
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return Response({
            "success": True,
            "message": "All notifications marked as read"
        }, status=HTTP_200_OK)


class NotificationAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Mark notification as read",
        description="Marks a specific notification as read",
        tags=["Notifications"]
    )
    def post(self, request, pk):
        try:
            notification = Notification.objects.get(pk=pk, user=request.user)
            notification.is_read = True
            notification.save()
            return Response({
                "success": True,
                "message": "Notification marked as read"
            }, status=HTTP_200_OK)
        except Notification.DoesNotExist:
            return Response({
                "success": False,
                "error": "Notification not found",
                "message": "The requested notification does not exist."
            }, status=HTTP_404_NOT_FOUND)

    @extend_schema(
        summary="Delete notification",
        description="Deletes a specific notification",
        tags=["Notifications"]
    )
    def delete(self, request, pk):
        try:
            notification = Notification.objects.get(pk=pk, user=request.user)
            notification.delete()
            return Response({
                "success": True,
                "message": "Notification deleted"
            }, status=HTTP_204_NO_CONTENT)
        except Notification.DoesNotExist:
            return Response({
                "success": False,
                "error": "Notification not found",
                "message": "The requested notification does not exist."
            }, status=HTTP_404_NOT_FOUND)

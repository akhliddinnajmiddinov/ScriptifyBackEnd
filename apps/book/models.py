from django.db import models
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator

User = get_user_model()

class Book(models.Model):
    STATUS_CHOICES = [
        ('unread', 'Unread'),
        ('reading', 'Currently Reading'),
        ('read', 'Read'),
        ('paused', 'Paused')
    ]
    
    name = models.CharField(verbose_name="book name", max_length=200)
    author = models.CharField(verbose_name="name of author this book", max_length=200)
    num_pages = models.IntegerField(verbose_name="number of pages of book")
    pages_read = models.IntegerField(verbose_name="pages read before", null=True, blank=True, default=0) 
    user = models.ForeignKey(User, verbose_name="Owner of this book", on_delete=models.CASCADE)
    start_date = models.DateField(verbose_name="Date User started reading this book", null=True, blank=True)
    finish_date = models.DateField(verbose_name="Date User finished reading this book", null=True, blank=True)
    image = models.ImageField(verbose_name="Image of this book", upload_to="book_images/", null=True, blank=True)
    
    # New fields
    description = models.TextField(verbose_name="Book description", null=True, blank=True)
    year = models.PositiveIntegerField(verbose_name="Publication year", null=True, blank=True)
    genre = models.CharField(verbose_name="Book genre", max_length=50, null=True, blank=True)
    isbn = models.CharField(verbose_name="ISBN", max_length=13, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='unread')
    rating = models.PositiveIntegerField(
        verbose_name="User rating (1-5)", 
        null=True, 
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} by {self.author}"

    @property
    def progress_percentage(self):
        if self.num_pages and self.pages_read:
            return min((self.pages_read / self.num_pages) * 100, 100)
        return 0

    @property
    def is_completed(self):
        return self.pages_read >= self.num_pages if self.pages_read else False


class BookReading(models.Model):
    book = models.ForeignKey(Book, verbose_name="book read", on_delete=models.CASCADE)
    date_read = models.DateTimeField(verbose_name="Time user started reading this book", auto_now_add=True)
    time_read = models.IntegerField(verbose_name="total time of this reading session (in minutes)")
    end_page = models.IntegerField(verbose_name="number page reached in this session")
    notes = models.TextField(verbose_name="Reading notes", null=True, blank=True)
    
    def save(self, *args, **kwargs):
        # Validation: Ensure end_page does not exceed book.num_pages
        if self.end_page > self.book.num_pages:
            raise ValidationError({
                'end_page': f'end_page ({self.end_page}) cannot exceed the book\'s total pages ({self.book.num_pages}).'
            })
        
        # Validation: Ensure end_page is not lte book.pages_read
        if self.end_page <= (self.book.pages_read or 0):
            raise ValidationError({
                'end_page': f'end_page ({self.end_page}) cannot be lte pages_read ({self.book.pages_read}).'
            })

        # Update book progress
        self.book.pages_read = max(self.book.pages_read or 0, self.end_page)
        
        # Update book status based on progress
        if self.book.pages_read >= self.book.num_pages:
            self.book.status = 'read'
            if not self.book.finish_date:
                from django.utils import timezone
                self.book.finish_date = timezone.now().date()
        elif self.book.pages_read > 0:
            self.book.status = 'reading'
            if not self.book.start_date:
                from django.utils import timezone
                self.book.start_date = timezone.now().date()
        
        self.book.save()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Reading session for {self.book.name} - {self.date_read}"


class ReadingGoal(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    year = models.PositiveIntegerField()
    target_books = models.PositiveIntegerField()
    target_pages = models.PositiveIntegerField(null=True, blank=True)
    target_hours = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['user', 'year']

    def __str__(self):
        return f"{self.user.phone_number}'s {self.year} goal: {self.target_books} books"

    @property
    def books_progress(self):
        from django.db.models import Count
        books_read = Book.objects.filter(
            user=self.user,
            status='read',
            finish_date__year=self.year
        ).count()
        return {
            'current': books_read,
            'target': self.target_books,
            'percentage': (books_read / self.target_books * 100) if self.target_books else 0
        }


class Achievement(models.Model):
    CONDITION_TYPES = [
        ('books_read', 'Books Read'),
        ('pages_read', 'Pages Read'),
        ('reading_streak', 'Reading Streak'),
        ('reading_time', 'Reading Time'),
        ('first_book', 'First Book'),
        ('genre_diversity', 'Genre Diversity')
    ]
    
    name = models.CharField(max_length=100)
    description = models.TextField()
    icon = models.CharField(max_length=50)  # FontAwesome class or emoji
    condition_type = models.CharField(max_length=50, choices=CONDITION_TYPES)
    condition_value = models.PositiveIntegerField()
    points = models.PositiveIntegerField(default=10)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class UserAchievement(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    achievement = models.ForeignKey(Achievement, on_delete=models.CASCADE)
    earned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'achievement']

    def __str__(self):
        return f"{self.user.phone_number} - {self.achievement.name}"


class Notification(models.Model):
    NOTIFICATION_TYPES = [
        ('achievement', 'Achievement'),
        ('goal', 'Goal'),
        ('reminder', 'Reminder'),
        ('milestone', 'Milestone')
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=100)
    message = models.TextField()
    type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} - {self.user.phone_number}"

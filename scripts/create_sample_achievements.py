import os
import sys
import django

# Add the project root to the Python path
sys.path.append('/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'book_arena.settings')
django.setup()

from apps.book.models import Achievement

def create_sample_achievements():
    """Create sample achievements for the book reading app"""
    
    achievements_data = [
        {
            'name': 'First Steps',
            'description': 'Read your first book',
            'icon': '📚',
            'condition_type': 'books_read',
            'condition_value': 1,
            'points': 10
        },
        {
            'name': 'Bookworm',
            'description': 'Read 5 books',
            'icon': '🐛',
            'condition_type': 'books_read',
            'condition_value': 5,
            'points': 25
        },
        {
            'name': 'Reading Machine',
            'description': 'Read 10 books',
            'icon': '🤖',
            'condition_type': 'books_read',
            'condition_value': 10,
            'points': 50
        },
        {
            'name': 'Scholar',
            'description': 'Read 25 books',
            'icon': '🎓',
            'condition_type': 'books_read',
            'condition_value': 25,
            'points': 100
        },
        {
            'name': 'Page Turner',
            'description': 'Read 1000 pages',
            'icon': '📖',
            'condition_type': 'pages_read',
            'condition_value': 1000,
            'points': 30
        },
        {
            'name': 'Speed Reader',
            'description': 'Read 5000 pages',
            'icon': '⚡',
            'condition_type': 'pages_read',
            'condition_value': 5000,
            'points': 75
        },
        {
            'name': 'Marathon Reader',
            'description': 'Read 10000 pages',
            'icon': '🏃‍♂️',
            'condition_type': 'pages_read',
            'condition_value': 10000,
            'points': 150
        },
        {
            'name': 'Consistent Reader',
            'description': 'Read for 7 days in a row',
            'icon': '🔥',
            'condition_type': 'reading_streak',
            'condition_value': 7,
            'points': 40
        },
        {
            'name': 'Reading Habit',
            'description': 'Read for 30 days in a row',
            'icon': '💪',
            'condition_type': 'reading_streak',
            'condition_value': 30,
            'points': 100
        },
        {
            'name': 'Reading Legend',
            'description': 'Read for 100 days in a row',
            'icon': '👑',
            'condition_type': 'reading_streak',
            'condition_value': 100,
            'points': 250
        },
        {
            'name': 'Time Keeper',
            'description': 'Read for 10 hours total',
            'icon': '⏰',
            'condition_type': 'reading_time',
            'condition_value': 600,  # 10 hours in minutes
            'points': 35
        },
        {
            'name': 'Dedicated Reader',
            'description': 'Read for 50 hours total',
            'icon': '⌚',
            'condition_type': 'reading_time',
            'condition_value': 3000,  # 50 hours in minutes
            'points': 80
        },
        {
            'name': 'Genre Explorer',
            'description': 'Read books from 5 different genres',
            'icon': '🗺️',
            'condition_type': 'genre_diversity',
            'condition_value': 5,
            'points': 60
        }
    ]
    
    created_count = 0
    for achievement_data in achievements_data:
        achievement, created = Achievement.objects.get_or_create(
            name=achievement_data['name'],
            defaults=achievement_data
        )
        if created:
            created_count += 1
            print(f"Created achievement: {achievement.name}")
        else:
            print(f"Achievement already exists: {achievement.name}")
    
    print(f"\nTotal achievements created: {created_count}")
    print(f"Total achievements in database: {Achievement.objects.count()}")

if __name__ == '__main__':
    create_sample_achievements()

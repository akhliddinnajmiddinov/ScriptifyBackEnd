from django.contrib import admin
from .models import Book, BookReading
# Register your models here.

admin.site.register(Book)
admin.site.register(BookReading)
#!/bin/bash
# Create initial migration for scripts app

echo "Creating migrations for scripts app..."
python manage.py makemigrations scripts

echo "Running migrations..."
python manage.py migrate scripts

echo "Initializing default scripts..."
python manage.py shell < scripts/init_scripts.py

echo "Done!"

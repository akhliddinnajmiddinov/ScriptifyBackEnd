"""
Script to initialize the database with default scripts.
Run this after migrations: python manage.py shell < scripts/init_scripts.py
"""
from apps.scripts.models import Script
import json

# Input schema for Kleinanzeigen scraper
kleinanzeigen_input_schema = {
    "title": "Kleinanzeigen Scraper Configuration",
    "type": "object",
    "steps": [
        {
            "title": "Search Configuration",
            "fields": [
                {
                    "name": "searchQuery",
                    "label": "Search Query",
                    "type": "text",
                    "required": True,
                    "defaultValue": "Druckerpatrone",
                    "placeholder": "e.g., Druckerpatrone"
                },
                {
                    "name": "brands",
                    "label": "Brands to Scrape",
                    "type": "dynamicArray",
                    "required": True,
                    "fields": [
                        {
                            "name": "brand",
                            "label": "Brand Name",
                            "type": "text",
                            "placeholder": "e.g., Canon, HP, Epson"
                        }
                    ]
                },
                {
                    "name": "maxPages",
                    "label": "Maximum Pages",
                    "type": "slider",
                    "min": 1,
                    "max": 100,
                    "step": 1,
                    "defaultValue": 5
                }
            ]
        }
    ]
}

# Output schema for Kleinanzeigen scraper
kleinanzeigen_output_schema = {
    "idField": "link",
    "columns": [
        {"key": "brand", "header": "Brand", "type": "text", "size": 100},
        {"key": "title", "header": "Title", "type": "text", "size": 300},
        {"key": "price", "header": "Price", "type": "text", "size": 80},
        {"key": "image_urls", "header": "Images", "type": "array<image>", "size": 160},
        {"key": "description", "header": "Description", "type": "text", "size": 400},
        {"key": "link", "header": "Link", "type": "link", "size": 100, "linkText": "View"}
    ]
}

def init_scripts():
    """Create default scripts in database"""
    
    # Kleinanzeigen Product Scraper
    script, created = Script.objects.update_or_create(
        name='Kleinanzeigen Product Scraper',
        defaults={
            'description': 'Scrapes products from Kleinanzeigen classifieds site',
            'celery_task': 'scripts.tasks.scrape_kleinanzeigen_brand',
            'input_schema': kleinanzeigen_input_schema,
            'output_schema': kleinanzeigen_output_schema,
            'is_active': True
        }
    )
    
    if created:
        print(f"✓ Created script: {script.name}")
    else:
        print(f"✓ Updated script: {script.name}")

if __name__ == '__main__':
    init_scripts()

# Run this from Django shell
init_scripts()

"""
Migration: Add MinPriceTask model and min_listing_data column to asin table.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('listings', '0011_buildlog_buildlogitem_buildcomponent_and_more'),
    ]

    operations = [
        # 1. Create the MinPriceTask table (fully managed by Django)
        # migrations.CreateModel(
        #     name='MinPriceTask',
        #     fields=[
        #         ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        #         ('status', models.CharField(choices=[
        #             ('PENDING', 'Pending'),
        #             ('RUNNING', 'Running'),
        #             ('SUCCESS', 'Success'),
        #             ('FAILURE', 'Failure'),
        #             ('CANCELLED', 'Cancelled'),
        #         ], default='PENDING', max_length=20)),
        #         ('celery_task_id', models.CharField(blank=True, max_length=255, null=True)),
        #         ('total_asins', models.IntegerField(default=0)),
        #         ('processed_asins', models.IntegerField(default=0)),
        #         ('started_at', models.DateTimeField(blank=True, null=True)),
        #         ('finished_at', models.DateTimeField(blank=True, null=True)),
        #         ('error_message', models.TextField(blank=True, default='')),
        #     ],
        #     options={
        #         'db_table': 'min_price_task',
        #         'ordering': ['-id'],
        #     },
        # ),
        # # 2. Add min_listing_data column to the unmanaged asin table via raw SQL
        # migrations.RunSQL(
        #     sql="ALTER TABLE asin ADD COLUMN IF NOT EXISTS min_listing_data jsonb NULL;",
        #     reverse_sql="ALTER TABLE asin DROP COLUMN IF EXISTS min_listing_data;",
        # ),
    ]

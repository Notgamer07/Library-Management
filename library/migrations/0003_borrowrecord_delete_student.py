# Generated by Django 5.1.7 on 2025-03-30 05:20

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('library', '0002_book'),
    ]

    operations = [
        migrations.CreateModel(
            name='BorrowRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('roll_no', models.CharField(max_length=255, unique=True)),
                ('book_title', models.CharField(max_length=255)),
                ('borrowed_book', models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.DeleteModel(
            name='Student',
        ),
    ]

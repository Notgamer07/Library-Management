# Generated by Django 5.1.7 on 2025-04-04 13:52

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('library', '0003_borrowrecord_delete_student'),
    ]

    operations = [
        migrations.AddField(
            model_name='borrowrecord',
            name='returned_date',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

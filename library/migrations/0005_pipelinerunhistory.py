from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('library', '0004_borrowrecord_returned_date'),
    ]

    operations = [
        migrations.CreateModel(
            name='PipelineRunHistory',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('mode', models.CharField(
                    choices=[('DAEMON', 'Scheduled Daemon'), ('RUN_ONCE', 'Single Cycle')],
                    default='RUN_ONCE',
                    max_length=10
                )),
                ('started_at', models.DateTimeField()),
                ('ended_at', models.DateTimeField(blank=True, null=True)),
                ('status', models.CharField(
                    choices=[
                        ('RUNNING', 'Running'),
                        ('COMPLETED', 'Completed'),
                        ('CANCELLED', 'Cancelled'),
                        ('FAILED', 'Failed'),
                    ],
                    default='RUNNING',
                    max_length=10
                )),
                ('rows_landing_to_bronze', models.IntegerField(default=0)),
                ('rows_bronze_to_silver', models.IntegerField(default=0)),
                ('gold_refreshed', models.BooleanField(default=False)),
                ('error_message', models.TextField(blank=True, null=True)),
            ],
            options={
                'verbose_name': 'Pipeline Run',
                'verbose_name_plural': 'Pipeline Runs',
                'ordering': ['-started_at'],
            },
        ),
    ]

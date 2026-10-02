from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('library', '0005_pipelinerunhistory'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pipelinerunhistory',
            name='mode',
            field=models.CharField(
                choices=[
                    ('landing_to_bronze', 'Landing to Bronze'),
                    ('bronze_to_silver', 'Bronze to Silver'),
                    ('silver_to_gold', 'Silver to Gold'),
                    ('ALL', 'Full Medallion Cycle'),
                    ('DAEMON', 'Scheduled Daemon'),
                    ('RUN_ONCE', 'Single Cycle'),
                ],
                default='landing_to_bronze',
                max_length=50
            ),
        ),
        migrations.AlterField(
            model_name='pipelinerunhistory',
            name='status',
            field=models.CharField(
                choices=[
                    ('STARTING', 'Starting'),
                    ('RUNNING', 'Running'),
                    ('COMPLETED', 'Completed'),
                    ('CANCELLED', 'Cancelled'),
                    ('FAILED', 'Failed'),
                ],
                default='RUNNING',
                max_length=20
            ),
        ),
    ]

from django.db import migrations, models


class CreateModelIfNotExists(migrations.CreateModel):
    """
    Subclasses CreateModel to ensure idempotency.
    If the target table already exists (e.g. created by database schema init scripts
    like schema_silver.sql or existing container volumes), database_forwards safely skips
    table creation rather than throwing ProgrammingError relation already exists.
    """
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.name)
        if self.allow_migrate_model(schema_editor.connection.alias, model):
            table_name = model._meta.db_table
            if table_name in schema_editor.connection.introspection.table_names():
                return
            super().database_forwards(app_label, schema_editor, from_state, to_state)


class Migration(migrations.Migration):

    dependencies = [
        ('library', '0004_borrowrecord_returned_date'),
    ]

    operations = [
        CreateModelIfNotExists(
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

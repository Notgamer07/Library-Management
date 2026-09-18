from django.db import models


class Book(models.Model):
    title = models.CharField(max_length=255)
    author = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=6, decimal_places=2)

    def __str__(self):
        return self.title


class BorrowRecord(models.Model):
    name = models.CharField(max_length=255)
    roll_no = models.CharField(max_length=255, unique=True)
    book_title = models.CharField(max_length=255)
    borrowed_book = models.DateTimeField(auto_now_add=True)
    returned_date = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'{self.name} - {self.book_title}'


class PipelineRunHistory(models.Model):
    """
    Records each completed or cancelled Medallion ETL pipeline run.
    Written by pipeline_manager.py when a run finishes (normally or via cancel).
    """
    MODE_CHOICES = [
        ('landing_to_bronze', 'Landing to Bronze'),
        ('bronze_to_silver', 'Bronze to Silver'),
        ('silver_to_gold', 'Silver to Gold'),
        ('ALL', 'Full Medallion Cycle'),
        ('DAEMON', 'Scheduled Daemon'),
        ('RUN_ONCE', 'Single Cycle'),
    ]
    STATUS_CHOICES = [
        ('STARTING', 'Starting'),
        ('RUNNING', 'Running'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
        ('FAILED', 'Failed'),
    ]

    mode = models.CharField(max_length=50, choices=MODE_CHOICES, default='landing_to_bronze')
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='RUNNING')

    # Row transfer counts per stage
    rows_landing_to_bronze = models.IntegerField(default=0)
    rows_bronze_to_silver = models.IntegerField(default=0)
    gold_refreshed = models.BooleanField(default=False)

    error_message = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-started_at']
        verbose_name = 'Pipeline Run'
        verbose_name_plural = 'Pipeline Runs'

    def __str__(self):
        return f"[{self.mode}] {self.started_at} → {self.status}"

    @property
    def duration_seconds(self):
        if self.ended_at and self.started_at:
            return int((self.ended_at - self.started_at).total_seconds())
        return None
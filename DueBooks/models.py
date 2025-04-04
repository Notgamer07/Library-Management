from django.db import models
from datetime import timedelta, datetime

# Create your models here.
class BorrowRecord(models.Model):
    name = models.CharField(max_length=255)
    roll_no = models.CharField(max_length=255, unique=True)
    book_title = models.CharField(max_length=255)
    borrowed_book = models.DateTimeField(auto_now_add=True)
    returned_date = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'{self.name} - {self.book_title}'

    # Method to calculate the due date (7 days after the borrowed date)
    def due_date(self):
        return self.borrowed_book + timedelta(days=7)

    # Method to calculate the number of overdue days
    def days_overdue(self):
        overdue = (datetime.now() - self.due_date()).days
        return overdue if overdue > 0 else 0
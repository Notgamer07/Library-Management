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
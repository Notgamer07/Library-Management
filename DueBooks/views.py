from django.shortcuts import render
from .models import BorrowRecord
from django.utils import timezone

# Create your views here.
def show(request):
    # Get all borrow records where the book is overdue
    borrow_records = BorrowRecord.objects.all()
    
    # Filter out only the records that are overdue
    due_books = []
    print(len(borrow_records),'I am displaying')  # This will output the number of records to the console
    for record in borrow_records:
        due_date = record.due_date()
        days_overdue = record.days_overdue()
        if days_overdue > 0:  # If the book is overdue
            due_books.append({
                'title': record.book_title,
                'author': record.book_title,  # Assuming author info is part of the book title or can be fetched
                'borrower_name': record.name,
                'student_id': record.roll_no,
                'due_date': due_date.strftime('%Y-%m-%d'),  # Format date to string
                'days_overdue': days_overdue
            })
    
    return render(request, 'render/location.html', {'due_books': due_books})
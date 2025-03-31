from django.shortcuts import render
from .models import BorrowRecord
from django.db import connection

def show(request):
    # Get all borrow records
    borrow_records = BorrowRecord.objects.all()
    print("Executed SQL Query:", connection.queries)

    # Prepare the list of borrowed books
    borrowed_books = []
    print(len(borrow_records), 'I am displaying')  # This will output the number of records to the console

    for record in borrow_records:
        borrowed_books.append({
            'book_title': record.book_title,
            'borrower_name': record.name,
            'student_id': record.roll_no,
            'borrowed_date': record.borrowed_book.strftime('%Y-%m-%d %H:%M:%S'),  # Format date to string
        })

    return render(request, 'render/location.html', {'borrowed_books': borrowed_books})

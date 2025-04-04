from django.shortcuts import render
from library.models import BorrowRecord
from datetime import timedelta, datetime

def show(request):
    # Get all borrow records
    borrow_records = BorrowRecord.objects.all()

    borrowed_books = []

    for record in borrow_records:
        due_date = record.borrowed_book + timedelta(days=7)  # Due date is 7 days after borrowing
        today = datetime.now(record.borrowed_book.tzinfo)  # Get current date with timezone
        overdue_days = (today - due_date).days if today > due_date else None  # Calculate overdue days

        borrowed_books.append({
            'book_title': record.book_title,
            'borrower_name': record.name,
            'student_id': record.roll_no,
            'borrowed_date': record.borrowed_book.strftime('%Y-%m-%d %H:%M:%S'),
            'due_date': due_date.strftime('%Y-%m-%d %H:%M:%S'),
            'days_overdue': overdue_days if overdue_days else '---'  # Show N/A if not overdue
        })

    return render(request, 'render/location.html', {'due_books': borrowed_books})

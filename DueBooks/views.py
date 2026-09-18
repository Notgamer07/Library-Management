from django.shortcuts import render
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from datetime import datetime

def show(request):
    """Renders active and returned due books from Silver 3NF borrow_records table."""
    borrowed_books = []
    
    query = """
        SELECT 
            br.record_id AS id,
            bk.title AS book_title,
            bw.name AS borrower_name,
            bw.student_id AS student_id,
            br.borrowed_at,
            br.due_date,
            br.returned_at,
            br.status
        FROM borrow_records br
        JOIN borrowers bw ON br.borrower_id = bw.borrower_id
        JOIN books bk ON br.book_id = bk.book_id
        ORDER BY br.record_id DESC;
    """
    
    with connection.cursor() as cursor:
        cursor.execute(query)
        for row in cursor.fetchall():
            rec_id, book_title, borrower_name, student_id, borrowed_at, due_date, returned_at, status = row
            
            return_status = returned_at.strftime('%Y-%m-%d %H:%M:%S') if returned_at else 'Not Returned'
            
            now_time = returned_at if returned_at else datetime.now(due_date.tzinfo)
            overdue_days = (now_time - due_date).days if now_time > due_date else None

            borrowed_books.append({
                'id': rec_id,
                'book_title': book_title,
                'borrower_name': borrower_name,
                'student_id': student_id,
                'borrowed_date': borrowed_at.strftime('%Y-%m-%d %H:%M:%S') if borrowed_at else 'N/A',
                'due_date': due_date.strftime('%Y-%m-%d %H:%M:%S') if due_date else 'N/A',
                'returned_date': return_status,
                'days_overdue': overdue_days if overdue_days else 'N/A'
            })

    return render(request, 'render/location.html', {'due_books': borrowed_books})


@csrf_exempt
def mark_as_returned(request):
    """Executes atomic stored procedure `sp_return_book` upon AJAX request."""
    if request.method == "POST":
        record_id = request.POST.get("record_id")
        if not record_id:
            return JsonResponse({'status': 'error', 'message': 'Missing record_id'})
        
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT success, message, returned_at, fine_amount FROM sp_return_book(%s);", [int(record_id)])
                row = cursor.fetchone()
                if row and row[0]:
                    ret_date = row[2].strftime('%Y-%m-%d %H:%M:%S') if row[2] else 'Returned'
                    return JsonResponse({
                        'status': 'success',
                        'returned_date': ret_date,
                        'fine_amount': float(row[3]) if row[3] else 0.0
                    })
                else:
                    msg = row[1] if row else 'Return transaction failed'
                    return JsonResponse({'status': 'error', 'message': msg})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})

    return JsonResponse({'status': 'error', 'message': 'Invalid request'})
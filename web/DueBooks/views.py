from django.shortcuts import render
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator
from datetime import datetime


def show(request):
    """
    Renders active and returned due books from Silver 3NF borrow_records table
    with database-level search filtering, status filtering, and customizable pagination.
    """
    # 1. Parse Query Parameters
    search_query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', 'all').strip().lower()

    page_size_str = request.GET.get('page_size', '15').strip()
    try:
        page_size = int(page_size_str)
        if page_size not in [10, 15, 25, 50, 100]:
            page_size = 15
    except ValueError:
        page_size = 15

    page_number_str = request.GET.get('page', '1').strip()
    try:
        page_number = max(1, int(page_number_str))
    except ValueError:
        page_number = 1

    # 2. Build SQL WHERE Filters
    where_clauses = []
    params = []

    if search_query:
        where_clauses.append(
            "(LOWER(bk.title) LIKE %s OR LOWER(bw.name) LIKE %s OR LOWER(bw.student_id) LIKE %s)"
        )
        q_wildcard = f"%{search_query.lower()}%"
        params.extend([q_wildcard, q_wildcard, q_wildcard])

    if status_filter == 'active':
        where_clauses.append("br.returned_at IS NULL AND br.due_date >= CURRENT_TIMESTAMP")
    elif status_filter == 'overdue':
        where_clauses.append("br.returned_at IS NULL AND br.due_date < CURRENT_TIMESTAMP")
    elif status_filter == 'returned':
        where_clauses.append("br.returned_at IS NOT NULL")

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    # 3. Fetch Total Count & Overview Counters
    total_count = 0
    total_active = 0
    total_overdue = 0
    total_returned = 0

    try:
        with connection.cursor() as cursor:
            # Filtered total count for pagination
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM borrow_records br
                JOIN borrowers bw ON br.borrower_id = bw.borrower_id
                JOIN books bk ON br.book_id = bk.book_id
                {where_sql};
                """,
                params
            )
            count_res = cursor.fetchone()
            total_count = count_res[0] if count_res else 0

            # Global status overview counts
            cursor.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE returned_at IS NULL AND due_date >= CURRENT_TIMESTAMP) AS active_loans,
                    COUNT(*) FILTER (WHERE returned_at IS NULL AND due_date < CURRENT_TIMESTAMP) AS overdue_loans,
                    COUNT(*) FILTER (WHERE returned_at IS NOT NULL) AS returned_loans
                FROM borrow_records;
                """
            )
            overview_res = cursor.fetchone()
            if overview_res:
                total_active = overview_res[0] or 0
                total_overdue = overview_res[1] or 0
                total_returned = overview_res[2] or 0
    except Exception:
        pass

    # 4. Initialize Django Paginator on total range
    paginator = Paginator(range(total_count), page_size) if total_count > 0 else Paginator([0], page_size)
    page_obj = paginator.get_page(page_number)

    # 5. Fetch Paginated Records via Database LIMIT and OFFSET
    borrowed_books = []
    if total_count > 0:
        offset = (page_obj.number - 1) * page_size
        query_sql = f"""
            SELECT 
                br.record_id AS id,
                bk.title AS book_title,
                bw.name AS borrower_name,
                bw.student_id AS student_id,
                br.borrowed_at,
                br.due_date,
                br.returned_at,
                br.status,
                br.fine_amount
            FROM borrow_records br
            JOIN borrowers bw ON br.borrower_id = bw.borrower_id
            JOIN books bk ON br.book_id = bk.book_id
            {where_sql}
            ORDER BY br.record_id DESC
            LIMIT %s OFFSET %s;
        """
        fetch_params = params + [page_size, offset]

        try:
            with connection.cursor() as cursor:
                cursor.execute(query_sql, fetch_params)
                for row in cursor.fetchall():
                    rec_id, book_title, borrower_name, student_id, borrowed_at, due_date, returned_at, status, fine_amount = row
                    
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
                        'days_overdue': overdue_days if overdue_days else 'N/A',
                        'fine_amount': float(fine_amount) if fine_amount else 0.0
                    })
        except Exception:
            pass

    page_obj.object_list = borrowed_books

    context = {
        'active_tab': 'due_books',
        'due_books': borrowed_books,
        'page_obj': page_obj,
        'total_records': total_count,
        'search_query': search_query,
        'status_filter': status_filter,
        'page_size': page_size,
        'total_active': total_active,
        'total_overdue': total_overdue,
        'total_returned': total_returned,
    }

    return render(request, 'render/location.html', context)


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
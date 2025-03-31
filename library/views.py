from django.shortcuts import render, redirect, get_object_or_404
from .models import Book, BorrowRecord

def add_student(request):
    if request.method == "POST":
        name = request.POST.get('name')
        roll_no = request.POST.get('roll_no')
        book_title = request.POST.get('book_title')
        if not name or not roll_no or not book_title:  
            return render(request, "render/library.html", {"error": "All fields are required!"})
        # Save the borrowed book record in the database
        BorrowRecord.objects.create(
            name=name,
            roll_no=roll_no,
            book_title=book_title
        )

        return redirect('home')
    return render(request, 'render/library.html')

def home(request):
    return render(request, 'render/library.html')

def book_list(request):
    books = Book.objects.all()
    return render(request, 'render/books.html', {'books': books})

def delete_book(request, book_id):
    book = get_object_or_404(Book, id=book_id)
    book.delete()
    return redirect('book_list')

def add_book(request):
    if request.method == 'POST':
        title = request.POST['title']
        author = request.POST['author']
        price = request.POST['price']
        Book.objects.create(title=title, author=author, price=price)
        if not title or not author or not price:  
            return render(request, "render/book_list.html", {"error": "All fields are required!"})
    return redirect('book_list')

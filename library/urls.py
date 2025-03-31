from django.urls import path
from . import views
from django.http import HttpResponseNotFound

urlpatterns = [
    path('', views.home, name='home'),
    path('favicon.ico', lambda request: HttpResponseNotFound()),
    path('add_student/', views.add_student, name='add_student'),
    path('books/', views.book_list, name='book_list'),
    path('books/add/', views.add_book, name='add_book'), 
    path('books/delete/<int:book_id>/', views.delete_book, name='delete_book'),
]

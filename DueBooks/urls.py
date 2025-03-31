from django.urls import path
from . import views

urlpatterns = [
    path('location/',views.show,name='dueBook'),
]
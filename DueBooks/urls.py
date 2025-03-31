from django.urls import path
from . import views
from django.http import HttpResponseNotFound

urlpatterns = [
    path('location/',views.show,name='dueBook'),
    path('favicon.ico', lambda request: HttpResponseNotFound()),
]
from django.urls import path
from . import views
from django.http import HttpResponseNotFound

urlpatterns = [
    path('location/',views.show,name='dueBook'),
    path('favicon.ico', lambda request: HttpResponseNotFound()),
    path("return-book/", views.mark_as_returned, name="return-book"),
]
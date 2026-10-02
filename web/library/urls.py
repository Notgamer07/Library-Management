from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('health', views.health_check, name='health'),
    path('health/', views.health_check, name='health_slash'),
    path('add_student/', views.add_student, name='add_student'),
    path('books/', views.book_list, name='book_list'),
    path('books/add/', views.add_book, name='add_book'), 
    path('books/delete/<int:book_id>/', views.delete_book, name='delete_book'),
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
    # Pipeline API endpoints
    path('api/pipeline/status/', views.api_pipeline_status, name='api_pipeline_status'),
    path('api/pipeline/start/', views.api_pipeline_start, name='api_pipeline_start'),
    path('api/pipeline/stop/', views.api_pipeline_stop, name='api_pipeline_stop'),
    path('api/pipeline/run-once/', views.api_pipeline_run_once, name='api_pipeline_run_once'),
    path('api/pipeline/history/', views.api_pipeline_history, name='api_pipeline_history'),
    # Resource Monitor API endpoint
    path('api/resource-monitor/', views.api_resource_monitor, name='api_resource_monitor'),
]

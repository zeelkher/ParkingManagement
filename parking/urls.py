from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.user_login, name='login'),
    path('logout/', views.user_logout, name='logout'),
    path('', views.dashboard, name='dashboard'),
    path('entry/', views.vehicle_entry, name='vehicle_entry'),
    path('exit/', views.vehicle_exit, name='vehicle_exit'),
    path('history/', views.history, name='history'),
    path('parking-management/', views.parking_management, name='parking_management'),
    path('advance-booking/', views.advance_booking, name='advance_booking'),
    path('advance-booking/checkin/<int:booking_id>/', views.checkin_advance_booking, name='checkin_advance_booking'),
    path('advance-booking/cancel/<int:booking_id>/', views.cancel_advance_booking, name='cancel_advance_booking'),
    path('advance-booking/pass/<int:booking_id>/', views.booking_pass, name='booking_pass'),
    path('reports/', views.reports, name='reports'),
    path('reports/export-csv/', views.export_reports_csv, name='export_reports_csv'),
    path('receipt/<int:record_id>/', views.receipt, name='receipt'),
    path('delete/<int:record_id>/', views.delete_record, name='delete_record'),
    path('clear-history/', views.clear_history, name='clear_history'),
]

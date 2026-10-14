from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.user_login, name='login'),
    path('logout/', views.user_logout, name='logout'),
    path('', views.dashboard, name='dashboard'),
    path('entry/', views.vehicle_entry, name='vehicle_entry'),
    path('exit/', views.vehicle_exit, name='vehicle_exit'),
    path('history/', views.history, name='history'),
    path('analytics/', views.analytics_dashboard, name='analytics'),
    path('analytics/export-excel/', views.export_analytics_excel, name='export_analytics_excel'),
    path('analytics/seed-demo/', views.seed_demo_analytics, name='seed_demo_analytics'),
    path('analytics/clear-demo/', views.clear_demo_analytics, name='clear_demo_analytics'),
    path('parking-management/', views.parking_management, name='parking_management'),
    path('receipt/<int:record_id>/', views.receipt, name='receipt'),
    path('delete/<int:record_id>/', views.delete_record, name='delete_record'),
    path('clear-history/', views.clear_history, name='clear_history'),

    # Operator Advance Booking Management
    path('booking-settings/', views.booking_form_settings, name='booking_form_settings'),
    path('booking-requests/', views.booking_requests, name='booking_requests'),
    path('booking-requests/<int:booking_id>/action/', views.booking_request_action, name='booking_request_action'),
    path('api/booking-lookup/', views.booking_lookup_api, name='booking_lookup_api'),

    # Public Customer Advance Booking Pages
    path('booking/', views.public_advance_booking, name='advance_booking'),
    path('advance-booking/', views.public_advance_booking, name='advance_booking_alias'),
    path('booking/confirmation/<str:reference>/', views.public_booking_confirmation, name='booking_confirmation'),
    path('booking/status/', views.public_booking_status, name='booking_status'),
    path('booking/cancel/<str:reference>/', views.public_booking_cancel, name='booking_cancel'),
]

from .models import AdvanceBooking

def advance_booking_context(request):
    if hasattr(request, 'user') and request.user.is_authenticated:
        pending_count = AdvanceBooking.objects.filter(status='Pending').count()
        return {
            'pending_bookings_count': pending_count
        }
    return {
        'pending_bookings_count': 0
    }

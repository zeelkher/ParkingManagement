"""
PARK NEST Email Utility
-----------------------
Sends booking confirmation and rejection emails to customers.
Uses hosted HTTPS URL for the PARK NEST brand logo and pure HTML/CSS for
status badges, completely avoiding MIME image attachments so recipients
see a clean email with no attached files.

Configuration via environment variables (set in .env):
    EMAIL_HOST          SMTP server hostname
    EMAIL_PORT          SMTP port (587 for STARTTLS, 465 for SSL)
    EMAIL_HOST_USER     SMTP username / sender login
    EMAIL_HOST_PASSWORD SMTP password or app password
    EMAIL_USE_TLS       'True' to use STARTTLS (recommended for port 587)
    EMAIL_USE_SSL       'True' to use implicit SSL (port 465)
    DEFAULT_FROM_EMAIL  From address shown to recipients
    EMAIL_LOGO_URL      (Optional) Custom HTTPS URL for the logo image
"""

import logging
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)

# Default public CDN / raw URL for the PARK NEST white logo
_DEFAULT_LOGO_URL = (
    'https://raw.githubusercontent.com/zeelkher/ParkingManagement/main/'
    'parking/static/images/logo_white_transparent.png'
)


def _base_context(booking):
    """Build shared context fields used in both email templates."""
    return {
        'booking': booking,
        'owner_first_name': (booking.owner_name or 'Customer').split()[0].title(),
        'logo_url': getattr(settings, 'EMAIL_LOGO_URL', _DEFAULT_LOGO_URL),
    }


def send_booking_confirmation_email(booking) -> tuple[bool, str]:
    """
    Send a booking-confirmed email to the customer when an operator
    confirms the booking and assigns a parking slot.

    Parameters
    ----------
    booking : AdvanceBooking instance  (status='Confirmed', assigned_slot set)

    Returns
    -------
    (success: bool, message: str)
    """
    if not booking.email:
        logger.info("No email on booking %s — confirmation email skipped.", booking.booking_reference)
        return False, "No email address provided for this booking."

    try:
        slot = booking.assigned_slot
        context = _base_context(booking)
        context.update({
            'slot_number': slot.number if slot else '—',
            'floor_name':  slot.parking_floor.name if slot else '',
            'area_name':   slot.parking_floor.parking_area.name if slot else '',
        })

        subject   = f"Booking Confirmed: {booking.booking_reference} — PARK NEST"
        text_body = render_to_string('parking/email/booking_confirmed.txt',  context)
        html_body = render_to_string('parking/email/booking_confirmed.html', context)

        msg = EmailMultiAlternatives(subject=subject, body=text_body, to=[booking.email])
        msg.attach_alternative(html_body, 'text/html')
        # No attached files — logo loads via HTTPS, badges rendered in pure CSS/HTML
        msg.send()

        logger.info("Confirmation email sent to %s for booking %s.", booking.email, booking.booking_reference)
        return True, "Confirmation email sent successfully."

    except Exception as exc:
        logger.error("Confirmation email failed for %s: %s", booking.booking_reference, exc)
        return False, "Email delivery failed — please check server logs."


def send_booking_rejection_email(booking, reason: str = '') -> tuple[bool, str]:
    """
    Send a booking-rejected email to the customer.

    Parameters
    ----------
    booking : AdvanceBooking instance  (status='Rejected')
    reason  : Optional rejection reason text from the operator

    Returns
    -------
    (success: bool, message: str)
    """
    if not booking.email:
        logger.info("No email on booking %s — rejection email skipped.", booking.booking_reference)
        return False, "No email address provided for this booking."

    try:
        context = _base_context(booking)
        context['rejection_reason'] = reason

        subject   = f"Booking Update: {booking.booking_reference} — PARK NEST"
        text_body = render_to_string('parking/email/booking_rejected.txt',  context)
        html_body = render_to_string('parking/email/booking_rejected.html', context)

        msg = EmailMultiAlternatives(subject=subject, body=text_body, to=[booking.email])
        msg.attach_alternative(html_body, 'text/html')
        # No attached files — logo loads via HTTPS, badges rendered in pure CSS/HTML
        msg.send()

        logger.info("Rejection email sent to %s for booking %s.", booking.email, booking.booking_reference)
        return True, "Rejection email sent successfully."

    except Exception as exc:
        logger.error("Rejection email failed for %s: %s", booking.booking_reference, exc)
        return False, "Email delivery failed — please check server logs."

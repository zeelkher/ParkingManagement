"""
PARK NEST Email Utility — Django email backend
-----------------------------------------------
Sends booking confirmation emails to customers when an operator confirms
a booking and assigns a parking slot.

Configuration is done entirely through environment variables (never hard-coded):
    EMAIL_HOST          SMTP server hostname
    EMAIL_PORT          SMTP port (typically 587 for STARTTLS, 465 for SSL)
    EMAIL_HOST_USER     SMTP username / sender login
    EMAIL_HOST_PASSWORD SMTP password or app password
    EMAIL_USE_TLS       'True' to use STARTTLS (recommended for port 587)
    EMAIL_USE_SSL       'True' to use implicit SSL (use for port 465, mutually exclusive with TLS)
    DEFAULT_FROM_EMAIL  From address shown to recipients (e.g. "PARK NEST <no-reply@example.com>")

Set these in your .env file.  See .env.example for a template.
"""

import logging
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def send_booking_confirmation_email(booking) -> tuple[bool, str]:
    """
    Send a booking-confirmed email to the customer.

    Parameters
    ----------
    booking : AdvanceBooking instance (status must already be 'Confirmed',
              assigned_slot must be set)

    Returns
    -------
    (success: bool, message: str)
    """
    if not booking.email:
        logger.info(
            "No email address on booking %s — email not sent.",
            booking.booking_reference,
        )
        return False, "No email address provided for this booking."

    try:
        # Build slot / area / floor context
        slot = booking.assigned_slot
        slot_number = slot.number if slot else "—"
        floor_name = slot.parking_floor.name if slot else ""
        area_name = slot.parking_floor.parking_area.name if slot else ""

        context = {
            "booking": booking,
            "slot_number": slot_number,
            "floor_name": floor_name,
            "area_name": area_name,
            "owner_first_name": (booking.owner_name or "Customer").split()[0].title(),
        }

        subject = f"✅ PARK NEST — Booking {booking.booking_reference} Confirmed"
        text_body = render_to_string(
            "parking/email/booking_confirmed.txt", context
        )
        html_body = render_to_string(
            "parking/email/booking_confirmed.html", context
        )

        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            to=[booking.email],
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send()

        logger.info(
            "Booking confirmation email sent to %s for booking %s.",
            booking.email,
            booking.booking_reference,
        )
        return True, "Confirmation email sent successfully."

    except Exception as exc:
        # Log full details server-side; never expose credentials in the message.
        logger.error(
            "Failed to send booking confirmation email for %s: %s",
            booking.booking_reference,
            exc,
        )
        return False, "Email delivery failed — please check server logs."


def send_booking_rejection_email(booking, reason: str = '') -> tuple[bool, str]:
    """
    Send a booking-rejected email to the customer.

    Parameters
    ----------
    booking         : AdvanceBooking instance (status must already be 'Rejected')
    reason          : Optional rejection reason text provided by the operator

    Returns
    -------
    (success: bool, message: str)
    """
    if not booking.email:
        logger.info(
            "No email address on booking %s — rejection email not sent.",
            booking.booking_reference,
        )
        return False, "No email address provided for this booking."

    try:
        context = {
            "booking": booking,
            "rejection_reason": reason,
            "owner_first_name": (booking.owner_name or "Customer").split()[0].title(),
        }

        subject = f"PARK NEST — Booking {booking.booking_reference} Update"
        text_body = render_to_string(
            "parking/email/booking_rejected.txt", context
        )
        html_body = render_to_string(
            "parking/email/booking_rejected.html", context
        )

        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            to=[booking.email],
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send()

        logger.info(
            "Booking rejection email sent to %s for booking %s.",
            booking.email,
            booking.booking_reference,
        )
        return True, "Rejection email sent successfully."

    except Exception as exc:
        logger.error(
            "Failed to send booking rejection email for %s: %s",
            booking.booking_reference,
            exc,
        )
        return False, "Email delivery failed — please check server logs."


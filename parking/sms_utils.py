"""
PARK NEST SMS Utility — Fast2SMS (free tier, India)
---------------------------------------------------
Free API:  https://www.fast2sms.com/  (No DLT required for DND-route quick SMS)
Sign up → Dashboard → Dev API key
Set FAST2SMS_API_KEY in environment or parking_system/settings.py

Usage:
    from parking.sms_utils import send_sms
    ok, msg = send_sms("9876543210", "Your booking BK-1234-5678 is confirmed.")
"""

import os
import json
import urllib.request
import urllib.parse
import logging

logger = logging.getLogger(__name__)

# ── Pull the key from env (or Django settings at runtime) ──────────────────
def _get_api_key():
    from django.conf import settings
    return getattr(settings, 'FAST2SMS_API_KEY', os.environ.get('FAST2SMS_API_KEY', ''))


def send_sms(mobile: str, message: str) -> tuple[bool, str]:
    """
    Send an SMS via Fast2SMS Quick-SMS (DND route — free plan).
    Returns (success: bool, status_message: str).

    Parameters
    ----------
    mobile  : 10-digit Indian mobile number (without +91 / 0 prefix)
    message : SMS text (max ~160 chars for single SMS)
    """
    api_key = _get_api_key()
    if not api_key:
        logger.warning("FAST2SMS_API_KEY not configured — SMS not sent.")
        return False, "SMS service not configured."

    # Normalise mobile — strip +91, leading 0, spaces
    mobile = str(mobile).strip().replace(' ', '').replace('-', '')
    if mobile.startswith('+91'):
        mobile = mobile[3:]
    elif mobile.startswith('91') and len(mobile) == 12:
        mobile = mobile[2:]
    if not mobile.isdigit() or len(mobile) != 10:
        return False, f"Invalid mobile number: {mobile}"

    url = "https://www.fast2sms.com/dev/bulkV2"
    payload = urllib.parse.urlencode({
        'authorization': api_key,
        'message': message,
        'language': 'english',
        'route': 'q',          # 'q' = Quick SMS (DND-friendly, free plan)
        'numbers': mobile,
    }).encode('utf-8')

    req = urllib.request.Request(url, data=payload, method='POST')
    req.add_header('cache-control', 'no-cache')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')

    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read().decode('utf-8'))
            if body.get('return') is True:
                logger.info("SMS sent to %s: %s", mobile, body.get('message'))
                return True, "SMS sent successfully."
            else:
                logger.warning("Fast2SMS error: %s", body)
                return False, body.get('message', ['SMS failed'])[0]
    except Exception as exc:
        logger.error("SMS send exception: %s", exc)
        return False, f"SMS error: {exc}"


def send_booking_confirmation_sms(mobile: str, ref: str, owner_name: str = '') -> tuple[bool, str]:
    """Send booking submission confirmation SMS."""
    name = owner_name.split()[0].title() if owner_name else 'Customer'
    msg = (
        f"Hi {name}, your PARK NEST advance booking is received!\n"
        f"Ref: {ref}\n"
        f"Track status: /booking/status/\n"
        f"Keep this ref safe. — PARK NEST"
    )
    return send_sms(mobile, msg)


def send_booking_approved_sms(mobile: str, ref: str, slot_label: str, owner_name: str = '') -> tuple[bool, str]:
    """Send slot-confirmed SMS when operator approves a booking."""
    name = owner_name.split()[0].title() if owner_name else 'Customer'
    msg = (
        f"Hi {name}, your PARK NEST booking {ref} is CONFIRMED!\n"
        f"Assigned Slot: {slot_label}\n"
        f"Please show this SMS at the gate. — PARK NEST"
    )
    return send_sms(mobile, msg)


def send_booking_rejected_sms(mobile: str, ref: str, reason: str = '', owner_name: str = '') -> tuple[bool, str]:
    """Send rejection SMS."""
    name = owner_name.split()[0].title() if owner_name else 'Customer'
    reason_text = f" Reason: {reason}" if reason else ""
    msg = (
        f"Hi {name}, booking {ref} could not be confirmed.{reason_text} "
        f"Please re-book at /booking/ — PARK NEST"
    )
    return send_sms(mobile, msg)

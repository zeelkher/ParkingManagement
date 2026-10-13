from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.db import IntegrityError, transaction
from django.db.models import Sum, Q
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache
from django.urls import reverse
from django.http import JsonResponse
from .models import (
    ParkingArea, ParkingFloor, ParkingRecord, ParkingSlot, Vehicle,
    BookingFormConfig, BookingCustomQuestion, AdvanceBooking
)
from .forms import (
    ParkingAreaForm, ParkingFloorForm, ParkingSlotForm, VehicleEntryForm, VehicleExitForm,
    BookingFormSettingsForm, BookingCustomQuestionForm, PublicAdvanceBookingForm, BookingStatusCheckForm
)
import math
import secrets
import os
import re
import pathlib
from .sms_utils import send_booking_confirmation_sms, send_booking_approved_sms, send_booking_rejected_sms

# ── Load .env on startup (if it exists) ────────────────────────────────────
_ENV_PATH = pathlib.Path(__file__).resolve().parent.parent / '.env'
if _ENV_PATH.exists():
    for _line in _ENV_PATH.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith('#') and '=' in _line:
            _k, _v = _line.split('=', 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))


def _write_env_key(env_path: pathlib.Path, key: str, value: str):
    """Persist a single key=value pair to a .env file."""
    content = env_path.read_text() if env_path.exists() else ''
    pattern = re.compile(rf'^{re.escape(key)}\s*=.*$', re.MULTILINE)
    new_line = f'{key}={value}'
    if pattern.search(content):
        content = pattern.sub(new_line, content)
    else:
        content = content.rstrip('\n') + '\n' + new_line + '\n'
    env_path.write_text(content)


def build_parking_layout(occupied_slots_map):
    """Return the configured places/floors/slots for dashboard and check-in."""
    floors = ParkingFloor.objects.select_related('parking_area').prefetch_related('slots').all()
    layout = []
    for floor in floors:
        floor_is_maint = floor.is_under_maintenance or floor.parking_area.is_under_maintenance
        spaces = [
            {
                'id': slot.id,
                'number': slot.number,
                'occupied': slot.id in occupied_slots_map,
                'vehicle_type': occupied_slots_map.get(slot.id),
                'under_maintenance': floor_is_maint or slot.is_under_maintenance,
            }
            for slot in floor.slots.all()
        ]
        layout.append({
            'id': floor.id,
            'area_id': floor.parking_area_id,
            'label': f'{floor.parking_area.name} • {floor.name}',
            'spaces': spaces,
            'total_slots': len(spaces),
            'occupied_slots': sum(1 for space in spaces if space['occupied']),
            'under_maintenance_slots': sum(1 for space in spaces if space['under_maintenance']),
        })
    return layout

def calculate_fee(vehicle_type, total_hours):
    hours = math.ceil(total_hours)
    if hours == 0:
        hours = 1
    fee_rates = {
        'Bike':       (20, 10),
        'Motorcycle': (20, 10),
        'Car':        (50, 20),
        'Auto':       (30, 15),
        'Auto-rickshaw': (30, 15),
        'Truck':      (100, 50),
        'Lorry':      (100, 50),
        'Tempo':      (100, 50),
        'Bus':        (120, 60),
    }
    first_hour, add_hour = fee_rates.get(vehicle_type, (50, 20))
    return first_hour + max(0, hours - 1) * add_hour


def add_numbered_slots(floor, prefix, requested_count):
    """Generate floor slots, padded to match the parking area's total capacity."""
    existing_count = floor.slots.count()
    if requested_count <= existing_count:
        return 0

    digits = len(str(floor.parking_area.total_slots))
    created = 0
    for position in range(1, requested_count + 1):
        _, was_created = ParkingSlot.objects.get_or_create(
            parking_floor=floor,
            number=f'{prefix}-{position:0{digits}d}',
            defaults={'sort_order': position},
        )
        created += was_created
    return created


def user_login(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                return redirect('dashboard')
            else:
                return render(request, 'parking/login.html', {'form': form, 'error': 'Invalid username or password.'})
        else:
            return render(request, 'parking/login.html', {'form': form, 'error': 'Invalid credentials entered.'})
    else:
        form = AuthenticationForm()
    return render(request, 'parking/login.html', {'form': form})


def user_logout(request):
    logout(request)
    return redirect('login')


@login_required(login_url='login')
def dashboard(request):
    active_records = ParkingRecord.objects.filter(status='Active').select_related('vehicle')
    occupied_slots = active_records.count()
    occupied_slots_map = {r.parking_slot_id: r.vehicle.vehicle_type for r in active_records if r.parking_slot_id}
    active_slot_ids = set(occupied_slots_map.keys())

    # Total slots represents total capacity - only affected when a slot is added or deleted
    total_slots = ParkingSlot.objects.count()

    # Available slots: slots that are not under maintenance and not occupied
    available_slots = ParkingSlot.objects.filter(
        is_under_maintenance=False,
        parking_floor__is_under_maintenance=False,
        parking_floor__parking_area__is_under_maintenance=False,
    ).exclude(id__in=active_slot_ids).count()

    percent_occupied = int((occupied_slots / total_slots) * 100) if total_slots else 0

    today = timezone.now().date()
    todays_entries = ParkingRecord.objects.filter(entry_time__date=today).count()
    todays_revenue = ParkingRecord.objects.filter(
        exit_time__date=today, status='Exited'
    ).aggregate(Sum('parking_fee'))['parking_fee__sum'] or 0

    context = {
        'total_slots': total_slots,
        'available_slots': available_slots,
        'occupied_slots': occupied_slots,
        'percent_occupied': percent_occupied,
        'todays_entries': todays_entries,
        'todays_revenue': todays_revenue,
        'active_records': active_records,
        'parking_floors': build_parking_layout(occupied_slots_map),
    }
    return render(request, 'parking/dashboard.html', context)


@login_required(login_url='login')
def vehicle_entry(request):
    active_records = ParkingRecord.objects.filter(status='Active').select_related('vehicle')
    active_slot_ids = set(r.parking_slot_id for r in active_records if r.parking_slot_id)
    active_slots_map = {r.parking_slot_id: r.vehicle.vehicle_type for r in active_records if r.parking_slot_id}
    available_slots = ParkingSlot.objects.filter(
        is_under_maintenance=False,
        parking_floor__is_under_maintenance=False,
        parking_floor__parking_area__is_under_maintenance=False,
    ).exclude(id__in=active_slot_ids).select_related(
        'parking_floor__parking_area'
    )
    parking_floors = build_parking_layout(active_slots_map)
    floor_area_map = {str(f['id']): str(f['area_id']) for f in parking_floors}
    slot_floor_map = {str(s['id']): str(f['id']) for f in parking_floors for s in f['spaces']}
    floor_slots_map = {
        str(f['id']): [
            {
                'id': str(s['id']),
                'number': s['number'],
                'occupied': bool(s['occupied']),
                'under_maintenance': bool(s['under_maintenance']),
            }
            for s in f['spaces']
        ]
        for f in parking_floors
    }

    if request.method == 'POST':
        form = VehicleEntryForm(request.POST, available_slots=available_slots)
        if form.is_valid():
            vehicle_number = form.cleaned_data['vehicle_number']
            owner_name     = form.cleaned_data['owner_name']
            mobile         = form.cleaned_data['mobile']
            vehicle_type   = form.cleaned_data['vehicle_type']
            plate_type     = form.cleaned_data['plate_type']
            state_code     = form.cleaned_data['state_code']
            parking_slot  = form.cleaned_data['parking_slot']
            entry_time     = form.cleaned_data['entry_time']

            # Check if vehicle is CURRENTLY parked (active session exists)
            active_record = ParkingRecord.objects.filter(
                vehicle__vehicle_number=vehicle_number, status='Active'
            ).first()
            if active_record:
                return render(request, 'parking/vehicle_entry.html', {
                    'form': form,
                    'error': f'Vehicle {vehicle_number} is already parked at {active_record.parking_number} ({active_record.floor_name}). Please check it out first before re-entry.',
                    'parking_floors': parking_floors,
                    'floor_area_map': floor_area_map,
                    'slot_floor_map': slot_floor_map,
                    'floor_slots_map': floor_slots_map,
                })

            # Get or create vehicle; update details on every entry
            vehicle, created = Vehicle.objects.get_or_create(
                vehicle_number=vehicle_number,
                defaults={
                    'owner_name': owner_name,
                    'mobile': mobile,
                    'vehicle_type': vehicle_type,
                    'plate_type': plate_type,
                    'state_code': state_code,
                }
            )
            if not created:
                vehicle.owner_name  = owner_name
                vehicle.mobile      = mobile
                vehicle.vehicle_type = vehicle_type
                vehicle.plate_type  = plate_type
                vehicle.state_code  = state_code
                vehicle.save()

            # Re-check just before saving in case another operator selected this slot.
            if ParkingRecord.objects.filter(parking_slot=parking_slot, status='Active').exists():
                return render(request, 'parking/vehicle_entry.html', {
                    'form': form,
                    'error': f'{parking_slot.label} was just occupied. Please select another free slot.',
                    'parking_floors': parking_floors,
                    'floor_area_map': floor_area_map,
                    'slot_floor_map': slot_floor_map,
                    'floor_slots_map': floor_slots_map,
                })

            record = ParkingRecord.objects.create(
                vehicle=vehicle, parking_slot=parking_slot, slot_number=parking_slot.id,
                entry_time=entry_time
            )

            # Link advance booking if submitted with a reference
            booking_ref = request.POST.get('booking_reference', '').strip().upper()
            if booking_ref:
                adv = AdvanceBooking.objects.filter(booking_reference=booking_ref).first()
                if adv:
                    adv.status = 'Checked In'
                    adv.checked_in_at = timezone.now()
                    adv.parking_record = record
                    adv.save()
                    messages.success(request, f'Advance booking {adv.booking_reference} checked in successfully!')

            return redirect('dashboard')
    else:
        booking_ref_param = request.GET.get('booking_ref', '').strip().upper()
        imported_booking = None
        initial_data = {'entry_time': timezone.localtime().strftime('%Y-%m-%dT%H:%M')}
        if booking_ref_param:
            imported_booking = AdvanceBooking.objects.filter(
                booking_reference=booking_ref_param
            ).select_related('assigned_slot__parking_floor__parking_area').first()
            if imported_booking:
                initial_data.update({
                    'vehicle_number': imported_booking.vehicle_number,
                    'owner_name': imported_booking.owner_name,
                    'mobile': imported_booking.mobile,
                    'vehicle_type': imported_booking.vehicle_type,
                    'plate_type': imported_booking.plate_type,
                    'state_code': imported_booking.state_code,
                    'bh_series': imported_booking.plate_type == 'bh_series' or (imported_booking.state_code == 'BH'),
                })
                if imported_booking.assigned_slot:
                    initial_data['parking_area'] = imported_booking.assigned_slot.parking_floor.parking_area_id
                    initial_data['parking_floor'] = imported_booking.assigned_slot.parking_floor_id
                    initial_data['parking_slot'] = imported_booking.assigned_slot_id

        form = VehicleEntryForm(
            available_slots=available_slots,
            initial=initial_data
        )
    return render(request, 'parking/vehicle_entry.html', {
        'form': form,
        'parking_floors': parking_floors,
        'floor_area_map': floor_area_map,
        'slot_floor_map': slot_floor_map,
        'floor_slots_map': floor_slots_map,
        'imported_booking': imported_booking,
    })


@login_required(login_url='login')
def vehicle_exit(request):
    # Build list of currently parked vehicles grouped by area, for the quick-checkout list
    active_records = (
        ParkingRecord.objects
        .filter(status='Active')
        .select_related('vehicle', 'parking_slot__parking_floor__parking_area')
        .order_by('parking_slot__parking_floor__parking_area__name', 'parking_slot__parking_floor__name', 'parking_slot__number')
    )
    # Group by area
    from collections import defaultdict
    by_area = defaultdict(list)
    for rec in active_records:
        area_name = rec.parking_slot.parking_floor.parking_area.name if rec.parking_slot else 'Unassigned'
        by_area[area_name].append(rec)
    parked_by_area = dict(by_area)

    if request.method == 'POST':
        form = VehicleExitForm(request.POST)
        if form.is_valid():
            vehicle_number = form.cleaned_data['vehicle_number']
            exit_time = form.cleaned_data['exit_time']
            try:
                record = ParkingRecord.objects.select_related('vehicle').get(
                    vehicle__vehicle_number=vehicle_number, status='Active'
                )
                if exit_time <= record.entry_time:
                    form.add_error('exit_time', 'Exit date and time must be after the entry date and time.')
                    return render(request, 'parking/vehicle_exit.html', {'form': form, 'parked_by_area': parked_by_area})
                record.exit_time   = exit_time
                duration           = record.exit_time - record.entry_time
                total_hours        = duration.total_seconds() / 3600
                record.total_hours = total_hours
                record.parking_fee = calculate_fee(record.vehicle.vehicle_type, total_hours)
                record.status      = 'Exited'
                record.save()
                return redirect('receipt', record_id=record.id)
            except ParkingRecord.DoesNotExist:
                # Check if this vehicle exists at all and already exited
                already_exited = ParkingRecord.objects.filter(
                    vehicle__vehicle_number=vehicle_number, status='Exited'
                ).order_by('-exit_time').first()
                if already_exited:
                    return render(request, 'parking/vehicle_exit.html', {
                        'form': form,
                        'parked_by_area': parked_by_area,
                        'error': f'Vehicle {vehicle_number} has already checked out. It is not currently parked.',
                    })
                return render(request, 'parking/vehicle_exit.html', {
                    'form': form,
                    'parked_by_area': parked_by_area,
                    'error': f'Vehicle {vehicle_number} not found in active parking records. Please verify the number.',
                })
    else:
        form = VehicleExitForm(initial={
            'exit_time': timezone.localtime().strftime('%Y-%m-%dT%H:%M')
        })
    return render(request, 'parking/vehicle_exit.html', {'form': form, 'parked_by_area': parked_by_area})


@login_required(login_url='login')
def history(request):
    query = request.GET.get('q', '').strip().upper()
    if query:
        records = ParkingRecord.objects.filter(
            vehicle__vehicle_number__icontains=query
        ).order_by('-entry_time').select_related('vehicle')
        if not records.exists():
            records = ParkingRecord.objects.filter(
                vehicle__owner_name__icontains=query
            ).order_by('-entry_time').select_related('vehicle')
    else:
        records = ParkingRecord.objects.all().order_by('-entry_time').select_related('vehicle')
    return render(request, 'parking/history.html', {'records': records, 'query': query})


@login_required(login_url='login')
def receipt(request, record_id):
    record = get_object_or_404(
        ParkingRecord.objects.select_related('vehicle', 'parking_slot__parking_floor__parking_area'),
        id=record_id,
    )
    area = record.parking_slot.parking_floor.parking_area
    payment_qr_data = area.payment_qr_data
    payment_qr_image = area.payment_qr_image
    return render(request, 'parking/receipt.html', {
        'record': record,
        'qr_data': payment_qr_data or f'PARKSAFE-RECEIPT-{record.id}-{record.vehicle.vehicle_number}-FEE-{record.parking_fee}',
        'is_payment_qr': bool(payment_qr_data or payment_qr_image),
        'payment_qr_image': payment_qr_image,
    })


@never_cache
@login_required(login_url='login')
def parking_management(request):
    """Require a fresh staff password before showing the management controls."""
    if request.method == 'POST' and request.POST.get('action') == 'management_reauth':
        user = authenticate(
            request,
            username=request.POST.get('username', ''),
            password=request.POST.get('password', ''),
        )
        if user is not None and user.is_staff:
            login(request, user)
            access_token = secrets.token_urlsafe(32)
            request.session['parking_management_access_token'] = access_token
            return redirect(f"{reverse('parking_management')}?access={access_token}")
        return render(request, 'parking/management_reauth.html', {
            'error': 'Enter valid staff username and password.',
        })

    if request.method == 'POST':
        if not request.session.pop('parking_management_post_authorized', False):
            return render(request, 'parking/management_reauth.html')
        return _parking_management(request)

    access_token = request.GET.get('access', '')
    expected_token = request.session.pop('parking_management_access_token', '')
    if not access_token or not expected_token or not secrets.compare_digest(access_token, expected_token):
        return render(request, 'parking/management_reauth.html')

    # The displayed page may submit one management action. The next visit requires re-authentication.
    request.session['parking_management_post_authorized'] = True
    return _parking_management(request)


@staff_member_required(login_url='login')
@never_cache
def _parking_management(request):
    """Staff-only management screen; no Django admin interface is required."""
    form_map = {
        'area': (ParkingAreaForm, ParkingArea),
        'floor': (ParkingFloorForm, ParkingFloor),
        'slot': (ParkingSlotForm, ParkingSlot),
    }
    if request.method == 'POST':
        action = request.POST.get('action', '')
        if action == 'save_layout':
            areas = list(ParkingArea.objects.prefetch_related('floors__slots').all())
            try:
                with transaction.atomic():
                    for area in areas:
                        total_slots = int(request.POST[f'area_total_slots_{area.id}'])
                        if total_slots < 1:
                            raise ValueError('Total slots must be at least 1.')
                        planned_slots = sum(
                            max(floor.slots.count(), int(request.POST[f'floor_slot_count_{floor.id}']))
                            for floor in area.floors.all()
                        )
                        if planned_slots > total_slots:
                            raise ValueError(f'{area.name} has {planned_slots} planned slots, exceeding its capacity of {total_slots}.')
                        area.name = request.POST[f'area_name_{area.id}'].strip()
                        area.address = request.POST[f'area_address_{area.id}'].strip()
                        area.payment_qr_data = request.POST[f'area_payment_qr_data_{area.id}'].strip()
                        qr_img_key = f'area_payment_qr_image_{area.id}'
                        if qr_img_key in request.FILES:
                            area.payment_qr_image = request.FILES[qr_img_key]
                        elif request.POST.get(f'delete_area_payment_qr_image_{area.id}') == '1':
                            if area.payment_qr_image:
                                area.payment_qr_image.delete(save=False)
                            area.payment_qr_image = None
                        area.total_slots = total_slots
                        area.is_under_maintenance = f'area_maintenance_{area.id}' in request.POST
                        area.save()
                        for floor in area.floors.all():
                            floor.name = request.POST[f'floor_name_{floor.id}'].strip()
                            floor.sort_order = int(request.POST[f'floor_sort_order_{floor.id}'])
                            floor.is_under_maintenance = f'floor_maintenance_{floor.id}' in request.POST
                            floor.save()
                            prefix = request.POST[f'floor_slot_prefix_{floor.id}'].strip().upper().replace(' ', '')
                            add_numbered_slots(floor, prefix, int(request.POST[f'floor_slot_count_{floor.id}']))
                            for slot in floor.slots.all():
                                slot.number = request.POST[f'slot_number_{slot.id}'].strip().upper()
                                slot.sort_order = int(request.POST[f'slot_sort_order_{slot.id}'])
                                slot.is_under_maintenance = f'slot_maintenance_{slot.id}' in request.POST
                                slot.save()
            except (KeyError, ValueError, IntegrityError) as error:
                messages.error(request, f'Could not save layout: {error}')
            else:
                messages.success(request, 'Parking layout saved.')
            return redirect('parking_management')
        kind = action.replace('add_', '').replace('update_', '').replace('delete_', '')
        form_class, model = form_map.get(kind, (None, None))
        if action.startswith('delete_') and model:
            item = get_object_or_404(model, pk=request.POST.get('id'))
            if kind == 'slot' and item.records.exists():
                messages.error(request, 'A slot with parking records cannot be removed.')
            elif kind == 'slot' and item.is_under_maintenance:
                messages.error(request, 'Cannot delete a slot that is under maintenance.')
            elif kind == 'floor' and item.slots.exists():
                messages.error(request, 'Remove or move its slots before removing a floor.')
            elif kind == 'floor' and item.is_under_maintenance:
                messages.error(request, 'Cannot delete a floor that is under maintenance.')
            elif kind == 'floor' and item.slots.filter(is_under_maintenance=True).exists():
                messages.error(request, 'Cannot delete a floor with slots under maintenance. Mark slots as available first.')
            elif kind == 'area' and item.floors.exists():
                messages.error(request, 'Remove its floors before removing a parking area.')
            elif kind == 'area' and item.is_under_maintenance:
                messages.error(request, 'Cannot delete a parking area that is under maintenance.')
            elif kind == 'area' and item.floors.filter(is_under_maintenance=True).exists():
                messages.error(request, 'Cannot delete a parking area with floors under maintenance. Mark floors as available first.')
            elif kind == 'area' and item.floors.prefetch_related('slots').filter(slots__is_under_maintenance=True).exists():
                messages.error(request, 'Cannot delete a parking area with slots under maintenance. Mark slots as available first.')
            else:
                item.delete()
                messages.success(request, f'{kind.title()} removed.')
            return redirect('parking_management')
        if form_class and action.startswith(('add_', 'update_')):
            instance = get_object_or_404(model, pk=request.POST.get('id')) if action.startswith('update_') else None
            form = form_class(request.POST, request.FILES, instance=instance)
            if form.is_valid():
                item = form.save()
                if kind == 'floor':
                    added = add_numbered_slots(
                        item, form.cleaned_data['slot_prefix'], form.cleaned_data['slot_count']
                    )
                    messages.success(request, f'Floor saved. {added} slot(s) created automatically.')
                else:
                    messages.success(request, f'{kind.title()} saved.')
                return redirect('parking_management')
            messages.error(request, f'Could not save {kind}: {form.errors.as_text()}')

    return render(request, 'parking/parking_management.html', {
        'area_form': ParkingAreaForm(),
        'floor_form': ParkingFloorForm(),
        'slot_form': ParkingSlotForm(),
        'areas': ParkingArea.objects.prefetch_related('floors__slots').all(),
    })


@login_required(login_url='login')
@require_POST
def delete_record(request, record_id):
    # Retrieve confirmation credentials submitted from the security modal
    username = request.POST.get('confirm_username', '')
    password = request.POST.get('confirm_password', '')
    # Authenticate user credentials in the Django backend
    user = authenticate(username=username, password=password)
    # Check if user is authenticated and belongs to the staff group
    if user is not None and user.is_staff:
        # Fetch and delete the specific parking record
        record = get_object_or_404(ParkingRecord, id=record_id)
        record.delete()
        messages.success(request, 'Record deleted successfully.')
    else:
        # Flag authentication failure back to the frontend alert messages
        messages.error(request, 'Authentication failed. Record was not deleted.')
    # Redirect back to the caller URL (usually history page)
    next_url = request.POST.get('next', 'history')
    return redirect(next_url)


@login_required(login_url='login')
@require_POST
def clear_history(request):
    # Retrieve confirmation credentials submitted from the security modal
    username = request.POST.get('confirm_username', '')
    password = request.POST.get('confirm_password', '')
    # Authenticate credentials in the Django backend
    user = authenticate(username=username, password=password)
    # Check if user is authenticated and belongs to the staff group
    if user is not None and user.is_staff:
        # Clean all records from database history
        ParkingRecord.objects.all().delete()
        messages.success(request, 'All records cleared successfully.')
    else:
        # Flag authentication failure back to the frontend alert messages
        messages.error(request, 'Authentication failed. History was not cleared.')
    # Redirect back to the caller URL (usually history page)
    next_url = request.POST.get('next', 'history')
    return redirect(next_url)


# ════════════════════════════════════════════════════════════
# ADVANCE BOOKING MANAGEMENT & CUSTOMER VIEWS
# ════════════════════════════════════════════════════════════

@login_required(login_url='login')
def booking_form_settings(request):
    """Operator setup: configure visibility, required fields, custom questions, and publish state."""
    config = BookingFormConfig.get_solo()

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'save_settings':
            settings_form = BookingFormSettingsForm(request.POST, instance=config)
            if settings_form.is_valid():
                settings_form.save()
                messages.success(request, 'Booking form settings published and updated successfully!')
                return redirect('booking_form_settings')
            else:
                messages.error(request, f'Could not update settings: {settings_form.errors.as_text()}')
        elif action == 'add_question':
            q_form = BookingCustomQuestionForm(request.POST)
            if q_form.is_valid():
                q = q_form.save(commit=False)
                q.form_config = config
                q.save()
                messages.success(request, f'Custom question "{q.question_text}" added.')
                return redirect('booking_form_settings')
            else:
                messages.error(request, f'Could not add question: {q_form.errors.as_text()}')
        elif action == 'delete_question':
            q_id = request.POST.get('question_id')
            q = get_object_or_404(BookingCustomQuestion, id=q_id, form_config=config)
            q_name = q.question_text
            q.delete()
            messages.success(request, f'Question "{q_name}" removed.')
            return redirect('booking_form_settings')
        elif action == 'toggle_question':
            q_id = request.POST.get('question_id')
            q = get_object_or_404(BookingCustomQuestion, id=q_id, form_config=config)
            q.is_active = not q.is_active
            q.save()
            messages.success(request, f'Question "{q.question_text}" {"activated" if q.is_active else "deactivated"}.')
            return redirect('booking_form_settings')
        elif action == 'save_sms_key':
            new_key = request.POST.get('fast2sms_api_key', '').strip()
            # Persist to a .env-style file or update the environment
            env_path = __import__('pathlib').Path(__file__).resolve().parent.parent / '.env'
            _write_env_key(env_path, 'FAST2SMS_API_KEY', new_key)
            # Also update in-process for current server session
            import os
            os.environ['FAST2SMS_API_KEY'] = new_key
            from django.conf import settings as djsettings
            djsettings.FAST2SMS_API_KEY = new_key
            if new_key:
                messages.success(request, 'SMS API key saved. SMS notifications are now active.')
            else:
                messages.info(request, 'SMS API key cleared. SMS notifications are disabled.')
            return redirect('booking_form_settings')

    settings_form = BookingFormSettingsForm(instance=config)
    question_form = BookingCustomQuestionForm()
    questions = config.custom_questions.all().order_by('sort_order', 'id')
    public_url = request.build_absolute_uri(reverse('advance_booking'))

    from django.conf import settings as django_settings
    import os
    from .sms_utils import _get_api_key
    sms_key = _get_api_key()
    sms_configured = bool(sms_key)
    # Show masked key: first 4 chars + asterisks
    sms_key_masked = (sms_key[:4] + '••••••••••••' + sms_key[-3:]) if len(sms_key) > 8 else ('••••••••' if sms_key else '')

    return render(request, 'parking/booking_settings.html', {
        'config': config,
        'settings_form': settings_form,
        'question_form': question_form,
        'questions': questions,
        'public_url': public_url,
        'sms_configured': sms_configured,
        'sms_key_masked': sms_key_masked,
    })


@login_required(login_url='login')
def booking_requests(request):
    """Operator review queue: examine incoming requests, inspect slots, confirm or reject."""
    status_filter = request.GET.get('status', 'all').strip()
    query = request.GET.get('q', '').strip()

    bookings_qs = AdvanceBooking.objects.select_related(
        'preferred_area', 'assigned_slot__parking_floor__parking_area', 'confirmed_by', 'parking_record'
    ).all()

    if status_filter and status_filter.lower() != 'all':
        bookings_qs = bookings_qs.filter(status__iexact=status_filter)

    if query:
        bookings_qs = bookings_qs.filter(
            Q(booking_reference__icontains=query) |
            Q(vehicle_number__icontains=query) |
            Q(owner_name__icontains=query) |
            Q(mobile__icontains=query)
        )

    # Status counts for navigation pills
    pending_count = AdvanceBooking.objects.filter(status='Pending').count()
    confirmed_count = AdvanceBooking.objects.filter(status='Confirmed').count()
    checked_in_count = AdvanceBooking.objects.filter(status='Checked In').count()
    rejected_count = AdvanceBooking.objects.filter(status='Rejected').count()
    cancelled_count = AdvanceBooking.objects.filter(status='Cancelled').count()
    all_count = AdvanceBooking.objects.count()

    # Slot availability data
    active_slot_ids = set(ParkingRecord.objects.filter(status='Active').values_list('parking_slot_id', flat=True))
    available_slots = ParkingSlot.objects.filter(
        is_under_maintenance=False,
        parking_floor__is_under_maintenance=False,
        parking_floor__parking_area__is_under_maintenance=False,
    ).exclude(id__in=active_slot_ids).select_related('parking_floor__parking_area').order_by(
        'parking_floor__parking_area__name', 'parking_floor__sort_order', 'sort_order'
    )

    return render(request, 'parking/booking_requests.html', {
        'bookings': bookings_qs,
        'status_filter': status_filter,
        'query': query,
        'pending_count': pending_count,
        'confirmed_count': confirmed_count,
        'checked_in_count': checked_in_count,
        'rejected_count': rejected_count,
        'cancelled_count': cancelled_count,
        'all_count': all_count,
        'available_slots': available_slots,
    })


@login_required(login_url='login')
@require_POST
def booking_request_action(request, booking_id):
    """Handle Confirm, Reject, Cancel, or Immediate Check-in for an Advance Booking."""
    booking = get_object_or_404(AdvanceBooking, id=booking_id)
    action = request.POST.get('action')

    if action == 'confirm':
        slot_id = request.POST.get('slot_id')
        operator_notes = request.POST.get('operator_notes', '').strip()
        if not slot_id:
            messages.error(request, 'Please select a parking slot to confirm this booking.')
            return redirect('booking_requests')

        slot = get_object_or_404(ParkingSlot, id=slot_id)
        if slot.is_under_maintenance or slot.parking_floor.is_under_maintenance or slot.parking_floor.parking_area.is_under_maintenance:
            messages.error(request, f'Slot {slot.number} is under maintenance. Please choose an active bay.')
            return redirect('booking_requests')
        if ParkingRecord.objects.filter(parking_slot=slot, status='Active').exists():
            messages.error(request, f'Slot {slot.number} is currently occupied by an active vehicle.')
            return redirect('booking_requests')

        booking.assigned_slot = slot
        booking.status = 'Confirmed'
        booking.confirmed_by = request.user
        booking.confirmed_at = timezone.now()
        booking.operator_notes = operator_notes
        booking.save()
        messages.success(request, f'Booking {booking.booking_reference} confirmed for Slot {slot.label}.')
        # Send slot-confirmed SMS
        if booking.mobile:
            send_booking_approved_sms(booking.mobile, booking.booking_reference, slot.label, booking.owner_name)

    elif action == 'reject':
        reason = request.POST.get('rejection_reason', '').strip()
        booking.status = 'Rejected'
        booking.rejection_reason = reason
        booking.operator_notes = request.POST.get('operator_notes', '').strip()
        booking.save()
        messages.warning(request, f'Booking {booking.booking_reference} has been rejected.')
        # Send rejection SMS
        if booking.mobile:
            send_booking_rejected_sms(booking.mobile, booking.booking_reference, reason, booking.owner_name)

    elif action == 'cancel':
        booking.status = 'Cancelled'
        booking.save()
        messages.info(request, f'Booking {booking.booking_reference} marked as cancelled.')

    elif action == 'check_in':
        if booking.status != 'Confirmed' or not booking.assigned_slot:
            messages.error(request, 'Only confirmed bookings with an assigned slot can be checked in.')
            return redirect('booking_requests')

        slot = booking.assigned_slot
        if ParkingRecord.objects.filter(parking_slot=slot, status='Active').exists():
            messages.error(request, f'Slot {slot.number} is currently occupied! Please reassign slot before check in.')
            return redirect('booking_requests')

        vehicle, _ = Vehicle.objects.get_or_create(
            vehicle_number=booking.vehicle_number,
            defaults={
                'owner_name': booking.owner_name or 'VISITOR',
                'mobile': booking.mobile,
                'vehicle_type': booking.vehicle_type,
                'plate_type': booking.plate_type,
                'state_code': booking.state_code,
            }
        )
        if booking.owner_name:
            vehicle.owner_name = booking.owner_name
        vehicle.mobile = booking.mobile
        vehicle.vehicle_type = booking.vehicle_type
        vehicle.plate_type = booking.plate_type
        vehicle.state_code = booking.state_code
        vehicle.save()

        record = ParkingRecord.objects.create(
            vehicle=vehicle,
            parking_slot=slot,
            slot_number=slot.id,
            entry_time=timezone.now(),
            status='Active'
        )
        booking.status = 'Checked In'
        booking.checked_in_at = timezone.now()
        booking.parking_record = record
        booking.save()
        messages.success(request, f'Vehicle {vehicle.vehicle_number} checked in! Parking record active at {slot.label}.')

    return redirect('booking_requests')


@login_required(login_url='login')
def booking_lookup_api(request):
    """Quick AJAX lookup by booking reference or vehicle number for the arrival operator."""
    q = request.GET.get('q', '').strip()
    if not q:
        return JsonResponse({'success': False, 'message': 'No query provided.'})

    booking = AdvanceBooking.objects.filter(
        Q(booking_reference__iexact=q) | Q(vehicle_number__iexact=q)
    ).select_related('assigned_slot__parking_floor__parking_area').first()

    if not booking:
        booking = AdvanceBooking.objects.filter(
            Q(booking_reference__icontains=q) | Q(vehicle_number__icontains=q)
        ).select_related('assigned_slot__parking_floor__parking_area').first()

    if not booking:
        return JsonResponse({'success': False, 'message': f'No booking found matching "{q}".'})

    slot_info = None
    if booking.assigned_slot:
        s = booking.assigned_slot
        slot_info = {
            'id': s.id,
            'number': s.number,
            'floor_id': s.parking_floor_id,
            'floor_name': s.parking_floor.name,
            'area_id': s.parking_floor.parking_area_id,
            'area_name': s.parking_floor.parking_area.name,
        }

    return JsonResponse({
        'success': True,
        'booking': {
            'id': booking.id,
            'reference': booking.booking_reference,
            'status': booking.status,
            'vehicle_number': booking.vehicle_number,
            'owner_name': booking.owner_name,
            'mobile': booking.mobile,
            'vehicle_type': booking.vehicle_type,
            'plate_type': booking.plate_type,
            'state_code': booking.state_code,
            'expected_arrival': booking.expected_arrival_time.strftime('%Y-%m-%d %H:%M') if booking.expected_arrival_time else '',
            'duration_hours': booking.expected_duration_hours,
            'slot': slot_info,
        }
    })


# ── Customer Public Views (No Login Required) ──

def public_advance_booking(request):
    """Customer-facing permanent advance booking form page."""
    config = BookingFormConfig.get_solo()

    if not config.is_published:
        return render(request, 'parking/public_advance_booking_disabled.html', {'config': config})

    if request.method == 'POST':
        form = PublicAdvanceBookingForm(request.POST, config=config)
        if form.is_valid():
            vehicle_number = form.cleaned_data.get('vehicle_number', '').strip().upper()
            owner_name = form.cleaned_data.get('owner_name', '').strip()
            mobile = form.cleaned_data.get('mobile', '').strip()
            vehicle_type = form.cleaned_data.get('vehicle_type', 'Car')
            plate_type = form.cleaned_data.get('plate_type', 'white_black')
            state_code = form.cleaned_data.get('state_code', '').strip().upper()
            if form.cleaned_data.get('bh_series'):
                plate_type = 'bh_series'
                state_code = 'BH'

            preferred_area = form.cleaned_data.get('preferred_area')
            notes = form.cleaned_data.get('notes', '').strip()
            expected_arrival_time = form.cleaned_data.get('expected_arrival_time') or (timezone.now() + timezone.timedelta(hours=config.advance_booking_lead_hours))
            expected_duration_hours = form.cleaned_data.get('expected_duration_hours', 2.0)

            # Extract dynamic custom question responses
            custom_answers = {}
            for q in config.custom_questions.filter(is_active=True):
                val = form.cleaned_data.get(f'custom_question_{q.id}')
                if val is not None and val != '':
                    custom_answers[str(q.id)] = {
                        'question': q.question_text,
                        'answer': 'Yes' if isinstance(val, bool) and val else ('No' if isinstance(val, bool) else str(val)),
                    }

            ref = AdvanceBooking.generate_reference()
            booking = AdvanceBooking.objects.create(
                booking_reference=ref,
                status='Pending',
                owner_name=owner_name,
                mobile=mobile,
                vehicle_number=vehicle_number,
                vehicle_type=vehicle_type,
                plate_type=plate_type,
                state_code=state_code,
                preferred_area=preferred_area,
                notes=notes,
                expected_arrival_time=expected_arrival_time,
                expected_duration_hours=expected_duration_hours,
                custom_answers=custom_answers,
            )
            # Send confirmation SMS with reference number (non-blocking)
            if mobile:
                send_booking_confirmation_sms(mobile, ref, owner_name)
            return redirect('booking_confirmation', reference=ref)
    else:
        # Default arrival time: rounded forward by lead hours
        now = timezone.localtime()
        default_arr = now + timezone.timedelta(hours=max(1, config.advance_booking_lead_hours))
        minute = (default_arr.minute // 15 + 1) * 15
        if minute >= 60:
            default_arr = default_arr.replace(minute=0) + timezone.timedelta(hours=1)
        else:
            default_arr = default_arr.replace(minute=minute)
        default_arr = default_arr.replace(second=0, microsecond=0)

        form = PublicAdvanceBookingForm(
            config=config,
            initial={
                'expected_arrival_time': default_arr.strftime('%Y-%m-%dT%H:%M'),
                'expected_duration_hours': 2.0,
                'plate_type': 'white_black',
            }
        )

    return render(request, 'parking/public_advance_booking.html', {
        'form': form,
        'config': config,
    })


def public_booking_confirmation(request, reference):
    """Customer-facing confirmation screen displaying generated reference and pending status."""
    booking = get_object_or_404(
        AdvanceBooking.objects.select_related('preferred_area', 'assigned_slot__parking_floor__parking_area'),
        booking_reference=reference
    )
    config = BookingFormConfig.get_solo()
    return render(request, 'parking/public_booking_confirmation.html', {
        'booking': booking,
        'config': config,
    })


def public_booking_status(request):
    """Customer-facing booking status check screen (reference + mobile number)."""
    config = BookingFormConfig.get_solo()
    booking = None
    search_performed = False
    error_message = None

    ref = (request.GET.get('ref') or request.POST.get('booking_reference') or '').strip().upper()
    mobile = (request.GET.get('mobile') or request.POST.get('mobile') or '').strip()

    if ref or mobile:
        search_performed = True
        if not ref or not mobile:
            error_message = 'Please provide both your Booking Reference and registered Mobile Number.'
        else:
            booking = AdvanceBooking.objects.filter(
                booking_reference=ref,
                mobile=mobile
            ).select_related(
                'assigned_slot__parking_floor__parking_area', 'preferred_area', 'parking_record'
            ).first()

            if not booking:
                error_message = f'No advance booking found for Reference "{ref}" with mobile "{mobile}". Please verify and try again.'

    form = BookingStatusCheckForm(initial={'booking_reference': ref, 'mobile': mobile})

    return render(request, 'parking/public_booking_status.html', {
        'form': form,
        'booking': booking,
        'search_performed': search_performed,
        'error_message': error_message,
        'config': config,
    })


@require_POST
def public_booking_cancel(request, reference):
    """Allows customer to cancel their pending or confirmed advance booking."""
    mobile = request.POST.get('mobile', '').strip()
    booking = get_object_or_404(AdvanceBooking, booking_reference=reference, mobile=mobile)
    if booking.status in ['Pending', 'Confirmed']:
        booking.status = 'Cancelled'
        booking.save()
        messages.info(request, f'Your booking {booking.booking_reference} has been cancelled successfully.')
    return redirect(f"{reverse('booking_status')}?ref={reference}&mobile={mobile}")


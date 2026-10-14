from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.db import IntegrityError, transaction
from django.db.models import Sum, Count, Q
from django.http import HttpResponse
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache
from django.urls import reverse
from .models import ParkingArea, ParkingFloor, ParkingRecord, ParkingSlot, Vehicle, AdvanceBooking, VEHICLE_TYPES
from .forms import ParkingAreaForm, ParkingFloorForm, ParkingSlotForm, VehicleEntryForm, VehicleExitForm, AdvanceBookingForm
import math
import secrets
import csv
from datetime import datetime

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

            ParkingRecord.objects.create(
                vehicle=vehicle, parking_slot=parking_slot, slot_number=parking_slot.id,
                entry_time=entry_time
            )
            return redirect('dashboard')
    else:
        form = VehicleEntryForm(
            available_slots=available_slots,
            initial={'entry_time': timezone.localtime().strftime('%Y-%m-%dT%H:%M')}
        )
    return render(request, 'parking/vehicle_entry.html', {
        'form': form,
        'parking_floors': parking_floors,
        'floor_area_map': floor_area_map,
        'slot_floor_map': slot_floor_map,
        'floor_slots_map': floor_slots_map,
    })


@login_required(login_url='login')
def vehicle_exit(request):
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
                    return render(request, 'parking/vehicle_exit.html', {'form': form})
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
                        'error': f'Vehicle {vehicle_number} has already checked out. It is not currently parked.',
                    })
                return render(request, 'parking/vehicle_exit.html', {
                    'form': form,
                    'error': f'Vehicle {vehicle_number} not found in active parking records. Please verify the number.',
                })
    else:
        form = VehicleExitForm(initial={
            'exit_time': timezone.localtime().strftime('%Y-%m-%dT%H:%M')
        })
    return render(request, 'parking/vehicle_exit.html', {'form': form})


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


# ══════════════════════════════════════════════════════════
# ADVANCE BOOKING SYSTEM
# ══════════════════════════════════════════════════════════

@login_required(login_url='login')
def advance_booking(request):
    """Manage slot pre-reservations and advance bookings."""
    active_slot_ids = set(ParkingRecord.objects.filter(status='Active').values_list('parking_slot_id', flat=True))
    available_slots = ParkingSlot.objects.filter(
        is_under_maintenance=False,
        parking_floor__is_under_maintenance=False,
        parking_floor__parking_area__is_under_maintenance=False,
    ).exclude(id__in=active_slot_ids)

    status_filter = request.GET.get('status', '').strip()
    query = request.GET.get('q', '').strip().upper()

    bookings = AdvanceBooking.objects.select_related(
        'parking_slot__parking_floor__parking_area', 'vehicle'
    ).all()

    if status_filter:
        bookings = bookings.filter(status=status_filter)
    if query:
        bookings = bookings.filter(
            Q(vehicle_number__icontains=query) |
            Q(owner_name__icontains=query) |
            Q(booking_id__icontains=query) |
            Q(mobile__icontains=query)
        )

    # Metrics
    total_bookings = AdvanceBooking.objects.count()
    now_local = timezone.localtime()
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_bookings = AdvanceBooking.objects.filter(created_at__gte=today_start).count()
    confirmed_bookings = AdvanceBooking.objects.filter(status='Confirmed').count()
    checkedin_bookings = AdvanceBooking.objects.filter(status='Checked-in').count()

    form = AdvanceBookingForm()
    if request.method == 'POST':
        action = request.POST.get('action', '')
        if action == 'create_booking':
            form = AdvanceBookingForm(request.POST)
            if form.is_valid():
                vehicle_number = form.cleaned_data['vehicle_number']
                owner_name = form.cleaned_data['owner_name']
                mobile = form.cleaned_data['mobile']
                vehicle_type = form.cleaned_data['vehicle_type']
                plate_type = form.cleaned_data['plate_type']
                state_code = form.cleaned_data['state_code']
                parking_slot = form.cleaned_data.get('parking_slot')
                booking_from = form.cleaned_data['booking_from']
                booking_to = form.cleaned_data['booking_to']
                advance_fee = form.cleaned_data.get('advance_fee') or 0.00
                notes = form.cleaned_data.get('notes', '')

                vehicle, _ = Vehicle.objects.get_or_create(
                    vehicle_number=vehicle_number,
                    defaults={
                        'owner_name': owner_name,
                        'mobile': mobile,
                        'vehicle_type': vehicle_type,
                        'plate_type': plate_type,
                        'state_code': state_code,
                    }
                )
                if vehicle.owner_name != owner_name or vehicle.mobile != mobile:
                    vehicle.owner_name = owner_name
                    vehicle.mobile = mobile
                    vehicle.vehicle_type = vehicle_type
                    vehicle.plate_type = plate_type
                    vehicle.state_code = state_code
                    vehicle.save()

                booking = AdvanceBooking.objects.create(
                    vehicle=vehicle,
                    vehicle_number=vehicle_number,
                    owner_name=owner_name,
                    mobile=mobile,
                    vehicle_type=vehicle_type,
                    plate_type=plate_type,
                    state_code=state_code,
                    parking_slot=parking_slot,
                    booking_from=booking_from,
                    booking_to=booking_to,
                    advance_fee=advance_fee,
                    notes=notes,
                    status='Confirmed',
                )
                messages.success(request, f'Advance booking #{booking.booking_id} created successfully for {vehicle_number}!')
                return redirect('advance_booking')
            else:
                messages.error(request, 'Please correct the errors in the reservation form.')

    # Layout for modal or slot selector
    active_slots_map = {r.parking_slot_id: r.vehicle.vehicle_type for r in ParkingRecord.objects.filter(status='Active').select_related('vehicle') if r.parking_slot_id}
    parking_floors = build_parking_layout(active_slots_map)

    context = {
        'bookings': bookings,
        'form': form,
        'status_filter': status_filter,
        'query': query,
        'total_bookings': total_bookings,
        'today_bookings': today_bookings,
        'confirmed_bookings': confirmed_bookings,
        'checkedin_bookings': checkedin_bookings,
        'available_slots': available_slots,
        'parking_floors': parking_floors,
    }
    return render(request, 'parking/advance_booking.html', context)


@login_required(login_url='login')
@require_POST
def checkin_advance_booking(request, booking_id):
    """Instantly check in an advance booking into an active parking session."""
    booking = get_object_or_404(AdvanceBooking, id=booking_id)
    if booking.status != 'Confirmed':
        messages.error(request, f'Booking is currently {booking.status} and cannot be checked in.')
        return redirect('advance_booking')

    # Check if vehicle is already parked actively
    active_record = ParkingRecord.objects.filter(
        vehicle__vehicle_number=booking.vehicle_number, status='Active'
    ).first()
    if active_record:
        messages.error(
            request,
            f'Vehicle {booking.vehicle_number} is already active in slot {active_record.parking_number}. Please check it out first.'
        )
        return redirect('advance_booking')

    # Check slot availability
    slot = booking.parking_slot
    if not slot or slot.records.filter(status='Active').exists() or slot.is_under_maintenance:
        # Auto-pick the first available free slot
        active_slot_ids = set(ParkingRecord.objects.filter(status='Active').values_list('parking_slot_id', flat=True))
        slot = ParkingSlot.objects.filter(
            is_under_maintenance=False,
            parking_floor__is_under_maintenance=False,
            parking_floor__parking_area__is_under_maintenance=False,
        ).exclude(id__in=active_slot_ids).first()

        if not slot:
            messages.error(request, 'No free parking slots available right now! Cannot check-in vehicle.')
            return redirect('advance_booking')
        booking.parking_slot = slot

    vehicle, _ = Vehicle.objects.get_or_create(
        vehicle_number=booking.vehicle_number,
        defaults={
            'owner_name': booking.owner_name,
            'mobile': booking.mobile,
            'vehicle_type': booking.vehicle_type,
            'plate_type': booking.plate_type,
            'state_code': booking.state_code,
        }
    )

    record = ParkingRecord.objects.create(
        vehicle=vehicle,
        parking_slot=slot,
        slot_number=slot.id,
        entry_time=timezone.now(),
        status='Active'
    )

    booking.status = 'Checked-in'
    booking.parking_record = record
    booking.save()

    messages.success(
        request,
        f'Vehicle {booking.vehicle_number} checked in successfully into slot {slot.number} ({slot.parking_floor.name})!'
    )
    return redirect('advance_booking')


@login_required(login_url='login')
@require_POST
def cancel_advance_booking(request, booking_id):
    """Cancel a reserved advance booking."""
    booking = get_object_or_404(AdvanceBooking, id=booking_id)
    if booking.status == 'Checked-in':
        messages.error(request, 'Cannot cancel a booking that is already checked in.')
    else:
        booking.status = 'Cancelled'
        booking.save()
        messages.success(request, f'Advance booking #{booking.booking_id} has been cancelled.')
    return redirect('advance_booking')


@login_required(login_url='login')
def booking_pass(request, booking_id):
    """View and print booking confirmation pass."""
    booking = get_object_or_404(
        AdvanceBooking.objects.select_related('vehicle', 'parking_slot__parking_floor__parking_area'),
        id=booking_id
    )
    qr_data = f'PARKSAFE-ADVANCE-{booking.booking_id}-{booking.vehicle_number}'
    return render(request, 'parking/booking_pass.html', {
        'booking': booking,
        'qr_data': qr_data,
    })


# ══════════════════════════════════════════════════════════
# PARKING & FINANCIAL REPORTS
# ══════════════════════════════════════════════════════════

def _filter_records_by_period(queryset, period, start_date_str, end_date_str):
    """Helper to apply period filters to parking records."""
    now = timezone.localtime()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    date_from = None
    date_to = None

    if period == 'today':
        date_from = today_start
        date_to = today_end
    elif period == 'yesterday':
        yest = now - timezone.timedelta(days=1)
        date_from = yest.replace(hour=0, minute=0, second=0, microsecond=0)
        date_to = yest.replace(hour=23, minute=59, second=59, microsecond=999999)
    elif period == 'week':
        date_from = (now - timezone.timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        date_to = today_end
    elif period == 'month':
        date_from = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        date_to = today_end
    elif period == 'custom' and start_date_str and end_date_str:
        try:
            s_dt = datetime.strptime(start_date_str, '%Y-%m-%d')
            e_dt = datetime.strptime(end_date_str, '%Y-%m-%d')
            date_from = timezone.make_aware(s_dt.replace(hour=0, minute=0, second=0))
            date_to = timezone.make_aware(e_dt.replace(hour=23, minute=59, second=59))
        except (ValueError, TypeError):
            date_from = today_start
            date_to = today_end

    if date_from and date_to:
        queryset = queryset.filter(entry_time__gte=date_from, entry_time__lte=date_to)

    return queryset, date_from, date_to


@login_required(login_url='login')
def reports(request):
    """Analytics, revenue and operational report dashboard."""
    period = request.GET.get('period', 'today')
    vtype = request.GET.get('vtype', '').strip()
    status_filter = request.GET.get('status', '').strip()
    start_date_str = request.GET.get('start_date', '').strip()
    end_date_str = request.GET.get('end_date', '').strip()

    records = ParkingRecord.objects.select_related('vehicle', 'parking_slot__parking_floor__parking_area').all()
    records, date_from, date_to = _filter_records_by_period(records, period, start_date_str, end_date_str)

    if vtype:
        records = records.filter(vehicle__vehicle_type=vtype)
    if status_filter:
        records = records.filter(status=status_filter)

    records = records.order_by('-entry_time')

    total_entries = records.count()
    active_count = records.filter(status='Active').count()
    exited_records = records.filter(status='Exited')
    exited_count = exited_records.count()
    total_revenue = exited_records.aggregate(Sum('parking_fee'))['parking_fee__sum'] or 0

    # Advance bookings in corresponding period
    adv_qs = AdvanceBooking.objects.all()
    if date_from and date_to:
        adv_qs = adv_qs.filter(created_at__gte=date_from, created_at__lte=date_to)
    total_advance_bookings = adv_qs.count()
    total_advance_revenue = adv_qs.aggregate(Sum('advance_fee'))['advance_fee__sum'] or 0
    grand_revenue = total_revenue + total_advance_revenue

    # Average duration
    avg_hours = 0
    if exited_count > 0:
        total_dur_hours = sum((r.total_hours or 0) for r in exited_records)
        avg_hours = round(total_dur_hours / exited_count, 1)

    # Vehicle type breakdown
    vehicle_types_stats = []
    vtype_counts = records.values('vehicle__vehicle_type').annotate(
        count=Count('id'),
        fee_sum=Sum('parking_fee')
    ).order_by('-count')

    for item in vtype_counts:
        vt = item['vehicle__vehicle_type'] or 'Unknown'
        cnt = item['count']
        fee = item['fee_sum'] or 0
        pct = round((cnt / total_entries * 100), 1) if total_entries > 0 else 0
        vehicle_types_stats.append({
            'type': vt,
            'count': cnt,
            'fee': fee,
            'percentage': pct,
        })

    # Hourly distribution
    hourly_counts = [0] * 24
    for r in records:
        entry_local = timezone.localtime(r.entry_time)
        hourly_counts[entry_local.hour] += 1

    peak_hour = None
    peak_hour_count = 0
    for hour, count in enumerate(hourly_counts):
        if count > peak_hour_count:
            peak_hour_count = count
            peak_hour = f"{hour:02d}:00 - {(hour + 1) % 24:02d}:00"

    context = {
        'records': records[:150],  # Limit to 150 for speedy rendering
        'total_record_count': total_entries,
        'period': period,
        'vtype': vtype,
        'status_filter': status_filter,
        'start_date': start_date_str,
        'end_date': end_date_str,
        'total_entries': total_entries,
        'active_count': active_count,
        'exited_count': exited_count,
        'total_revenue': total_revenue,
        'total_advance_bookings': total_advance_bookings,
        'total_advance_revenue': total_advance_revenue,
        'grand_revenue': grand_revenue,
        'avg_hours': avg_hours,
        'peak_hour': peak_hour or '—',
        'peak_hour_count': peak_hour_count,
        'vehicle_types_stats': vehicle_types_stats,
        'hourly_counts': hourly_counts,
        'VEHICLE_TYPES': VEHICLE_TYPES,
        'date_from': date_from,
        'date_to': date_to,
    }
    return render(request, 'parking/reports.html', context)


@login_required(login_url='login')
def export_reports_csv(request):
    """Download CSV spreadsheet of filtered parking records."""
    period = request.GET.get('period', 'today')
    vtype = request.GET.get('vtype', '').strip()
    status_filter = request.GET.get('status', '').strip()
    start_date_str = request.GET.get('start_date', '').strip()
    end_date_str = request.GET.get('end_date', '').strip()

    records = ParkingRecord.objects.select_related('vehicle', 'parking_slot__parking_floor__parking_area').all()
    records, _, _ = _filter_records_by_period(records, period, start_date_str, end_date_str)

    if vtype:
        records = records.filter(vehicle__vehicle_type=vtype)
    if status_filter:
        records = records.filter(status=status_filter)

    records = records.order_by('-entry_time')

    response = HttpResponse(content_type='text/csv')
    timestamp = timezone.now().strftime('%Y%m%d_%H%M')
    response['Content-Disposition'] = f'attachment; filename="parksafe_report_{period}_{timestamp}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Ticket ID', 'Vehicle Number', 'Owner Name', 'Mobile Number',
        'Vehicle Type', 'Category', 'Parking Slot', 'Floor', 'Parking Area',
        'Entry Time', 'Exit Time', 'Duration (Hours)', 'Parking Fee (INR)', 'Status'
    ])

    for r in records:
        writer.writerow([
            r.id,
            r.vehicle.vehicle_number,
            r.vehicle.owner_name,
            f'+91 {r.vehicle.mobile}',
            r.vehicle.vehicle_type,
            r.vehicle.get_plate_colors()[2],
            r.parking_number,
            r.floor_name,
            r.parking_area_name,
            timezone.localtime(r.entry_time).strftime('%Y-%m-%d %H:%M:%S') if r.entry_time else '',
            timezone.localtime(r.exit_time).strftime('%Y-%m-%d %H:%M:%S') if r.exit_time else 'Active',
            round(r.total_hours, 2) if r.total_hours else '',
            r.parking_fee if r.parking_fee is not None else '',
            r.status,
        ])

    return response


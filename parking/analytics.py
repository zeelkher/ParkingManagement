import math
from datetime import datetime, timedelta, time
from collections import defaultdict
from decimal import Decimal

from django.utils import timezone
from django.db.models import Sum, Avg, Count, Q
from .models import ParkingRecord, ParkingArea, ParkingFloor, ParkingSlot, Vehicle, PLATE_TYPES, VEHICLE_TYPES

PLATE_LABELS = dict(PLATE_TYPES)
VEHICLE_TYPE_LIST = [vt[0] for vt in VEHICLE_TYPES]

WEEKDAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def parse_date_range(range_type='last30', start_date_str=None, end_date_str=None):
    """
    Parse range type or custom dates and return (start_datetime, end_datetime, range_label).
    """
    now = timezone.now()
    today = now.date()

    if range_type == 'today':
        start_dt = timezone.make_aware(datetime.combine(today, time.min))
        end_dt = timezone.make_aware(datetime.combine(today, time.max))
        label = "Today"
    elif range_type == 'last7':
        start_date = today - timedelta(days=6)
        start_dt = timezone.make_aware(datetime.combine(start_date, time.min))
        end_dt = timezone.make_aware(datetime.combine(today, time.max))
        label = "Last 7 Days"
    elif range_type == 'last30':
        start_date = today - timedelta(days=29)
        start_dt = timezone.make_aware(datetime.combine(start_date, time.min))
        end_dt = timezone.make_aware(datetime.combine(today, time.max))
        label = "Last 30 Days"
    elif range_type == 'this_month':
        start_date = today.replace(day=1)
        start_dt = timezone.make_aware(datetime.combine(start_date, time.min))
        end_dt = timezone.make_aware(datetime.combine(today, time.max))
        label = f"This Month ({now.strftime('%b %Y')})"
    elif range_type == 'last_month':
        first_of_this_month = today.replace(day=1)
        last_day_prev_month = first_of_this_month - timedelta(days=1)
        first_day_prev_month = last_day_prev_month.replace(day=1)
        start_dt = timezone.make_aware(datetime.combine(first_day_prev_month, time.min))
        end_dt = timezone.make_aware(datetime.combine(last_day_prev_month, time.max))
        label = f"Last Month ({first_day_prev_month.strftime('%b %Y')})"
    elif range_type == 'this_year':
        start_date = today.replace(month=1, day=1)
        start_dt = timezone.make_aware(datetime.combine(start_date, time.min))
        end_dt = timezone.make_aware(datetime.combine(today, time.max))
        label = f"This Year ({now.year})"
    elif range_type == 'custom' and start_date_str and end_date_str:
        try:
            s_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            e_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            if s_date > e_date:
                s_date, e_date = e_date, s_date
            start_dt = timezone.make_aware(datetime.combine(s_date, time.min))
            end_dt = timezone.make_aware(datetime.combine(e_date, time.max))
            label = f"{s_date.strftime('%d %b %Y')} – {e_date.strftime('%d %b %Y')}"
        except (ValueError, TypeError):
            # Fallback to last 30
            start_date = today - timedelta(days=29)
            start_dt = timezone.make_aware(datetime.combine(start_date, time.min))
            end_dt = timezone.make_aware(datetime.combine(today, time.max))
            label = "Last 30 Days"
    else: # 'all' or default
        start_dt = None
        end_dt = None
        label = "All Time"

    return start_dt, end_dt, label


def filter_parking_records(range_type='all', start_date_str=None, end_date_str=None,
                           vehicle_type=None, parking_area_id=None, status=None, plate_type=None):
    """
    Return filtered queryset based on specified parameters.
    """
    qs = ParkingRecord.objects.select_related(
        'vehicle', 'parking_slot__parking_floor__parking_area'
    ).all()

    start_dt, end_dt, range_label = parse_date_range(range_type, start_date_str, end_date_str)

    if start_dt and end_dt:
        qs = qs.filter(entry_time__gte=start_dt, entry_time__lte=end_dt)

    if vehicle_type and vehicle_type != 'all':
        qs = qs.filter(vehicle__vehicle_type=vehicle_type)

    if parking_area_id and str(parking_area_id) != 'all':
        qs = qs.filter(parking_slot__parking_floor__parking_area_id=parking_area_id)

    if status and status != 'all':
        qs = qs.filter(status=status)

    if plate_type and plate_type != 'all':
        qs = qs.filter(vehicle__plate_type=plate_type)

    return qs, {
        'start_dt': start_dt,
        'end_dt': end_dt,
        'range_label': range_label,
        'range_type': range_type,
        'start_date_str': start_date_str or '',
        'end_date_str': end_date_str or '',
        'vehicle_type': vehicle_type or 'all',
        'parking_area_id': str(parking_area_id or 'all'),
        'status': status or 'all',
        'plate_type': plate_type or 'all',
    }


def format_duration_hm(hours_float):
    """Format decimal hours into e.g. '2h 35m'."""
    if not hours_float or hours_float <= 0:
        return "0m"
    total_minutes = int(round(hours_float * 60))
    days = total_minutes // 1440
    rem = total_minutes % 1440
    hrs = rem // 60
    mins = rem % 60

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hrs > 0 or days > 0:
        parts.append(f"{hrs}h")
    if mins > 0 or not parts:
        parts.append(f"{mins}m")
    return " ".join(parts)


def compute_analytics(queryset):
    """
    Computes all analytical aggregations, KPIs, distributions, and chart datasets.
    Evaluates cleanly in Python to remain 100% resilient across all database engines.
    """
    records_list = list(queryset.order_by('entry_time'))
    total_records = len(records_list)

    total_revenue = Decimal('0.00')
    exited_count = 0
    active_count = 0
    total_duration_hours = 0.0
    duration_valid_count = 0

    # Hourly buckets 0..23
    hourly_entries = [0] * 24
    hourly_exits = [0] * 24
    hourly_revenue = [Decimal('0.00')] * 24

    # Day of week buckets 0..6 (Monday..Sunday)
    weekday_entries = [0] * 7
    weekday_exits = [0] * 7
    weekday_revenue = [Decimal('0.00')] * 7

    # Groupings
    daily_map = defaultdict(lambda: {'entries': 0, 'exits': 0, 'revenue': Decimal('0.00')})
    monthly_map = defaultdict(lambda: {'entries': 0, 'exits': 0, 'revenue': Decimal('0.00'), 'sort_key': ''})
    yearly_map = defaultdict(lambda: {'entries': 0, 'exits': 0, 'revenue': Decimal('0.00')})

    vehicle_type_map = defaultdict(lambda: {'count': 0, 'revenue': Decimal('0.00'), 'duration_sum': 0.0, 'duration_count': 0})
    plate_type_map = defaultdict(int)

    area_map = defaultdict(lambda: {'entries': 0, 'revenue': Decimal('0.00'), 'active': 0, 'name': ''})
    floor_map = defaultdict(lambda: {'entries': 0, 'revenue': Decimal('0.00'), 'active': 0, 'area_name': '', 'floor_name': ''})

    # Duration tiers (<1h, 1-3h, 3-6h, 6-12h, >12h)
    duration_tiers = {
        '< 1 hr': 0,
        '1 – 3 hrs': 0,
        '3 – 6 hrs': 0,
        '6 – 12 hrs': 0,
        '> 12 hrs': 0,
    }

    ev_count = 0

    for r in records_list:
        v = r.vehicle
        v_type = v.vehicle_type if v else 'Other'
        p_type = v.plate_type if v else 'white_black'
        fee = r.parking_fee or Decimal('0.00')
        dur = r.total_hours or 0.0

        if p_type in ('green_white', 'green_yellow'):
            ev_count += 1

        plate_type_map[p_type] += 1

        # Status & revenue
        if r.status == 'Exited':
            exited_count += 1
            total_revenue += fee
            if dur > 0:
                total_duration_hours += dur
                duration_valid_count += 1

                # Duration tier classification
                if dur < 1.0:
                    duration_tiers['< 1 hr'] += 1
                elif dur < 3.0:
                    duration_tiers['1 – 3 hrs'] += 1
                elif dur < 6.0:
                    duration_tiers['3 – 6 hrs'] += 1
                elif dur < 12.0:
                    duration_tiers['6 – 12 hrs'] += 1
                else:
                    duration_tiers['> 12 hrs'] += 1
        else:
            active_count += 1

        # Vehicle type aggregation
        vehicle_type_map[v_type]['count'] += 1
        vehicle_type_map[v_type]['revenue'] += fee
        if dur > 0:
            vehicle_type_map[v_type]['duration_sum'] += dur
            vehicle_type_map[v_type]['duration_count'] += 1

        # Area & Floor aggregation
        if r.parking_slot and r.parking_slot.parking_floor:
            floor = r.parking_slot.parking_floor
            area = floor.parking_area
            area_id = area.id
            floor_id = floor.id

            area_map[area_id]['name'] = area.name
            area_map[area_id]['entries'] += 1
            area_map[area_id]['revenue'] += fee
            if r.status == 'Active':
                area_map[area_id]['active'] += 1

            floor_map[floor_id]['area_name'] = area.name
            floor_map[floor_id]['floor_name'] = floor.name
            floor_map[floor_id]['entries'] += 1
            floor_map[floor_id]['revenue'] += fee
            if r.status == 'Active':
                floor_map[floor_id]['active'] += 1

        # Time aggregations
        if r.entry_time:
            # Convert to local timezone if needed
            entry_local = timezone.localtime(r.entry_time) if timezone.is_aware(r.entry_time) else r.entry_time
            h = entry_local.hour
            hourly_entries[h] += 1

            wd = entry_local.weekday() # 0 = Monday, 6 = Sunday
            weekday_entries[wd] += 1

            d_key = entry_local.strftime('%Y-%m-%d')
            daily_map[d_key]['entries'] += 1

            m_key = entry_local.strftime('%Y-%m')
            monthly_map[m_key]['entries'] += 1
            monthly_map[m_key]['sort_key'] = m_key

            y_key = str(entry_local.year)
            yearly_map[y_key]['entries'] += 1

        if r.exit_time:
            exit_local = timezone.localtime(r.exit_time) if timezone.is_aware(r.exit_time) else r.exit_time
            exit_h = exit_local.hour
            hourly_exits[exit_h] += 1
            hourly_revenue[exit_h] += fee

            exit_wd = exit_local.weekday()
            weekday_exits[exit_wd] += 1
            weekday_revenue[exit_wd] += fee

            exit_d_key = exit_local.strftime('%Y-%m-%d')
            daily_map[exit_d_key]['exits'] += 1
            daily_map[exit_d_key]['revenue'] += fee

            exit_m_key = exit_local.strftime('%Y-%m')
            monthly_map[exit_m_key]['exits'] += 1
            monthly_map[exit_m_key]['revenue'] += fee
            monthly_map[exit_m_key]['sort_key'] = exit_m_key

            exit_y_key = str(exit_local.year)
            yearly_map[exit_y_key]['exits'] += 1
            yearly_map[exit_y_key]['revenue'] += fee

    # Compute Averages & Peak Metrics
    avg_revenue_per_vehicle = float(total_revenue / exited_count) if exited_count > 0 else 0.0
    avg_duration_hours = (total_duration_hours / duration_valid_count) if duration_valid_count > 0 else 0.0
    avg_duration_formatted = format_duration_hm(avg_duration_hours)

    # Peak hour analysis
    peak_hour = max(range(24), key=lambda i: hourly_entries[i]) if total_records > 0 else 12
    peak_hour_count = hourly_entries[peak_hour] if total_records > 0 else 0
    h_start = peak_hour % 12 or 12
    h_end = (peak_hour + 1) % 12 or 12
    am_pm_start = "AM" if peak_hour < 12 else "PM"
    am_pm_end = "AM" if (peak_hour + 1) < 12 or (peak_hour + 1) == 24 else "PM"
    peak_hour_str = f"{h_start}:00 {am_pm_start} – {h_end}:00 {am_pm_end}"

    # Busiest day analysis
    busiest_day_idx = max(range(7), key=lambda i: weekday_entries[i]) if total_records > 0 else 0
    busiest_day_str = WEEKDAY_NAMES[busiest_day_idx]
    busiest_day_count = weekday_entries[busiest_day_idx] if total_records > 0 else 0

    ev_percentage = round((ev_count / total_records * 100), 1) if total_records > 0 else 0.0

    # Hourly series data
    hourly_labels = []
    for h in range(24):
        lbl = f"{h%12 or 12} {'AM' if h<12 else 'PM'}"
        hourly_labels.append(lbl)

    hourly_chart_data = {
        'labels': hourly_labels,
        'entries': hourly_entries,
        'exits': hourly_exits,
        'revenue': [float(rev) for rev in hourly_revenue],
    }

    # Weekday series data
    weekday_chart_data = {
        'labels': WEEKDAY_NAMES,
        'entries': weekday_entries,
        'exits': weekday_exits,
        'revenue': [float(rev) for rev in weekday_revenue],
    }

    # Daily trends (sorted by date)
    sorted_daily_keys = sorted(daily_map.keys())
    daily_labels = []
    daily_entries = []
    daily_exits = []
    daily_revenues = []
    for d_str in sorted_daily_keys:
        try:
            d_obj = datetime.strptime(d_str, '%Y-%m-%d')
            daily_labels.append(d_obj.strftime('%d %b'))
        except ValueError:
            daily_labels.append(d_str)
        daily_entries.append(daily_map[d_str]['entries'])
        daily_exits.append(daily_map[d_str]['exits'])
        daily_revenues.append(float(daily_map[d_str]['revenue']))

    daily_chart_data = {
        'dates': sorted_daily_keys,
        'labels': daily_labels,
        'entries': daily_entries,
        'exits': daily_exits,
        'revenue': daily_revenues,
    }

    # Monthly trends (sorted by year-month)
    sorted_monthly_keys = sorted(monthly_map.keys())
    monthly_labels = []
    monthly_entries = []
    monthly_exits = []
    monthly_revenues = []
    for m_str in sorted_monthly_keys:
        try:
            m_obj = datetime.strptime(m_str, '%Y-%m')
            monthly_labels.append(m_obj.strftime('%b %Y'))
        except ValueError:
            monthly_labels.append(m_str)
        monthly_entries.append(monthly_map[m_str]['entries'])
        monthly_exits.append(monthly_map[m_str]['exits'])
        monthly_revenues.append(float(monthly_map[m_str]['revenue']))

    monthly_chart_data = {
        'months': sorted_monthly_keys,
        'labels': monthly_labels,
        'entries': monthly_entries,
        'exits': monthly_exits,
        'revenue': monthly_revenues,
    }

    # Yearly trends (sorted by year)
    sorted_yearly_keys = sorted(yearly_map.keys())
    yearly_labels = sorted_yearly_keys
    yearly_entries = [yearly_map[y]['entries'] for y in sorted_yearly_keys]
    yearly_exits = [yearly_map[y]['exits'] for y in sorted_yearly_keys]
    yearly_revenues = [float(yearly_map[y]['revenue']) for y in sorted_yearly_keys]

    yearly_chart_data = {
        'labels': yearly_labels,
        'entries': yearly_entries,
        'exits': yearly_exits,
        'revenue': yearly_revenues,
    }

    # Vehicle type breakdown list
    vehicle_types_data = []
    for v_type, data in sorted(vehicle_type_map.items(), key=lambda x: x[1]['count'], reverse=True):
        count = data['count']
        rev = float(data['revenue'])
        pct = round((count / total_records * 100), 1) if total_records > 0 else 0
        avg_dur = round(data['duration_sum'] / data['duration_count'], 2) if data['duration_count'] > 0 else 0
        vehicle_types_data.append({
            'type': v_type,
            'count': count,
            'percentage': pct,
            'revenue': rev,
            'avg_duration': avg_dur,
            'avg_duration_str': format_duration_hm(avg_dur),
        })

    # Plate type breakdown
    plate_types_data = []
    for p_code, count in sorted(plate_type_map.items(), key=lambda x: x[1], reverse=True):
        lbl = PLATE_LABELS.get(p_code, p_code.replace('_', ' ').title())
        pct = round((count / total_records * 100), 1) if total_records > 0 else 0
        plate_types_data.append({
            'code': p_code,
            'label': lbl,
            'count': count,
            'percentage': pct,
        })

    # Area performance
    areas_data = []
    for area_id, data in area_map.items():
        total_slots = ParkingSlot.objects.filter(parking_floor__parking_area_id=area_id).count()
        areas_data.append({
            'area_id': area_id,
            'name': data['name'],
            'total_slots': total_slots,
            'entries': data['entries'],
            'revenue': float(data['revenue']),
            'active': data['active'],
        })

    # Floor performance
    floors_data = []
    for floor_id, data in floor_map.items():
        total_slots = ParkingSlot.objects.filter(parking_floor_id=floor_id).count()
        floors_data.append({
            'floor_id': floor_id,
            'area_name': data['area_name'],
            'floor_name': data['floor_name'],
            'total_slots': total_slots,
            'entries': data['entries'],
            'revenue': float(data['revenue']),
            'active': data['active'],
        })

    return {
        'kpis': {
            'total_records': total_records,
            'active_records': active_count,
            'exited_records': exited_count,
            'total_revenue': float(total_revenue),
            'avg_revenue': round(avg_revenue_per_vehicle, 2),
            'avg_duration_hours': round(avg_duration_hours, 2),
            'avg_duration_formatted': avg_duration_formatted,
            'peak_hour_str': peak_hour_str,
            'peak_hour_count': peak_hour_count,
            'busiest_day_str': busiest_day_str,
            'busiest_day_count': busiest_day_count,
            'ev_count': ev_count,
            'ev_percentage': ev_percentage,
        },
        'daily_chart_data': daily_chart_data,
        'monthly_chart_data': monthly_chart_data,
        'yearly_chart_data': yearly_chart_data,
        'hourly_chart_data': hourly_chart_data,
        'weekday_chart_data': weekday_chart_data,
        'vehicle_types_data': vehicle_types_data,
        'plate_types_data': plate_types_data,
        'duration_tiers': duration_tiers,
        'areas_data': areas_data,
        'floors_data': floors_data,
    }

import random
from datetime import datetime, timedelta
from decimal import Decimal

from django.utils import timezone
from .models import ParkingRecord, ParkingSlot, Vehicle, VEHICLE_TYPES, PLATE_TYPES
import math

def _calculate_fee(vehicle_type, total_hours):
    hours = math.ceil(total_hours)
    if hours == 0:
        hours = 1
    fee_rates = {
        'Bike': (20, 10),
        'Motorcycle': (20, 10),
        'Car': (50, 20),
        'Auto': (30, 15),
        'Auto-rickshaw': (30, 15),
        'Truck': (100, 50),
        'Lorry': (100, 50),
        'Tempo': (100, 50),
        'Bus': (120, 60),
    }
    first_hour, add_hour = fee_rates.get(vehicle_type, (50, 20))
    return first_hour + max(0, hours - 1) * add_hour

SAMPLE_OWNERS = [
    "Rajesh Sharma", "Priya Patel", "Amit Verma", "Sunita Nair", "Vikram Rathore",
    "Ananya Iyer", "Karan Malhotra", "Deepika Joshi", "Rohan Mehta", "Neha Gupta",
    "Suresh Kumar", "Pooja Reddy", "Manish Singh", "Kavita Deshmukh", "Arjun Bhatia",
    "Sneha Kulkarni", "Gaurav Chopra", "Divya Menon", "Harish Rawat", "Meera Nambiar"
]

SAMPLE_STATES = ['MH', 'GJ', 'DL', 'KA', 'TN', 'HR', 'UP', 'TS', 'RJ', 'WB']

PLATE_WEIGHTS = [
    ('white_black', 55),
    ('yellow_black', 18),
    ('green_white', 12),
    ('green_yellow', 5),
    ('bh_series', 5),
    ('black_yellow', 3),
    ('dealer_trade', 2),
]

VEHICLE_WEIGHTS = [
    ('Car', 50),
    ('Bike', 22),
    ('Motorcycle', 10),
    ('Auto-rickshaw', 6),
    ('Truck', 4),
    ('Bus', 3),
    ('Van', 3),
    ('Tempo', 2),
]


def seed_realistic_analytics_data(record_count=80):
    """
    Generate realistic parking records across the last 6-12 months
    to showcase rich analytics, trends, peak hours, and reports.
    """
    slots = list(ParkingSlot.objects.filter(is_under_maintenance=False))
    if not slots:
        return 0

    now = timezone.now()
    created_count = 0

    # Weighted random selector
    def pick_weighted(choices_weights):
        items, weights = zip(*choices_weights)
        return random.choices(items, weights=weights, k=1)[0]

    for i in range(record_count):
        # Pick date within past 180 days, biased towards recent weeks
        days_ago = int(random.triangular(0, 180, 20))
        target_date = now - timedelta(days=days_ago)

        # Realistic rush hour distribution (peaks around 9-11 AM and 5-8 PM)
        hour_weights = [
            1, 1, 1, 1, 2, 4, # 00 - 05
            8, 14, 22, 28, 26, 20, # 06 - 11
            18, 16, 15, 17, 24, 30, # 12 - 17
            28, 22, 16, 10, 6, 3    # 18 - 23
        ]
        hour = random.choices(range(24), weights=hour_weights, k=1)[0]
        minute = random.randint(0, 59)
        second = random.randint(0, 59)

        entry_dt = target_date.replace(hour=hour, minute=minute, second=second)

        # Stay duration: majority 1 - 4 hours, some longer
        duration_hours = round(random.triangular(0.3, 14.0, 2.2), 2)
        exit_dt = entry_dt + timedelta(hours=duration_hours)

        # 95% exited, 5% active (only if entry was within last 12 hours)
        is_active = (days_ago == 0 and hour >= (now.hour - 4) and random.random() < 0.3)

        v_type = pick_weighted(VEHICLE_WEIGHTS)
        p_type = pick_weighted(PLATE_WEIGHTS)
        st_code = random.choice(SAMPLE_STATES)
        v_num = f"{st_code} {random.randint(10, 99):02d} {chr(random.randint(65, 90))}{chr(random.randint(65, 90))} {random.randint(1000, 9999)}"

        owner = random.choice(SAMPLE_OWNERS)
        mob = f"98{random.randint(10000000, 99999999)}"

        vehicle, _ = Vehicle.objects.get_or_create(
            vehicle_number=v_num,
            defaults={
                'owner_name': owner,
                'mobile': mob,
                'vehicle_type': v_type,
                'plate_type': p_type,
                'state_code': st_code,
            }
        )

        slot = random.choice(slots)
        slot_num = slot.sort_order or 1

        if is_active:
            fee = None
            status = 'Active'
            record_exit_dt = None
            record_dur = None
        else:
            fee = Decimal(str(_calculate_fee(v_type, duration_hours)))
            status = 'Exited'
            record_exit_dt = exit_dt
            record_dur = duration_hours

        ParkingRecord.objects.create(
            vehicle=vehicle,
            parking_slot=slot,
            slot_number=slot_num,
            entry_time=entry_dt,
            exit_time=record_exit_dt,
            total_hours=record_dur,
            parking_fee=fee,
            status=status,
        )
        created_count += 1

    return created_count


def clear_demo_analytics_data():
    """Clear demo or simulated records if needed."""
    # We can delete all records or those without active sessions
    deleted, _ = ParkingRecord.objects.filter(status='Exited').delete()
    return deleted
